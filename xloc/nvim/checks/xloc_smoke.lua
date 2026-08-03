local root = vim.env.XLOC_NVIM_PLUGIN
local tmp = vim.env.XLOC_NVIM_TMP
if not root or root == "" or not tmp or tmp == "" then
  vim.cmd.cquit()
end

vim.opt.rtp:append(root)
require("xloc").setup()

local function write(path, lines)
  vim.fn.mkdir(vim.fn.fnamemodify(path, ":h"), "p")
  vim.fn.writefile(lines, path)
end

local function assert_equal(expected, actual, message)
  if expected ~= actual then
    error(string.format("%s: expected %s, got %s", message, vim.inspect(expected), vim.inspect(actual)))
  end
end

local repo = tmp .. "/repo"
local run = tmp .. "/run"
local absolute_src = tmp .. "/abs_src.sv"
local relative_src = repo .. "/tb/relative_src.sv"
local local_src = run .. "/local_src.sv"
local log = run .. "/sim.log"
local map = log .. ".xloc.jsonl"
local bad_log = run .. "/bad.log"
local bad_map = bad_log .. ".xloc.jsonl"
local no_map_log = run .. "/no_map.log"

write(absolute_src, { "abs 1", "abs 2", "abs 3" })
write(relative_src, { "rel 1", "rel 2", "rel 3" })
write(local_src, { "local 1", "local 2" })
write(log, {
  "UVM_ERROR L_00000001(2)",
  "UVM_ERROR L_00000002(3)",
  "UVM_ERROR L_00000003(2)",
  "UVM_ERROR L_00000004(1)",
})
write(map, {
  string.format('{"loc_id":"L_00000001","file":%q}', absolute_src),
  '{"loc_id":"L_00000002","file":"tb/relative_src.sv"}',
  '{"loc_id":"L_00000003","file":"local_src.sv"}',
  '{"loc_id":"L_00000004","file":"missing.sv"}',
})
write(no_map_log, { "UVM_ERROR L_0000000A(1)" })
write(run .. "/L_0000000A", { "native gf decoy" })

vim.g.xloc_repo_root = repo
require("xloc").setup({ repo_root = repo })

vim.cmd.edit(vim.fn.fnameescape(log))
assert_equal(true, vim.fn.maparg("gf", "n", false, true).buffer == 1, "buffer gf mapping exists")

local function jump(log_line, source, source_line, message)
  vim.cmd.edit(vim.fn.fnameescape(log))
  vim.api.nvim_win_set_cursor(0, { log_line, 0 })
  vim.cmd("XlocGF")
  assert_equal(vim.fn.fnamemodify(source, ":p"), vim.api.nvim_buf_get_name(0), message .. " source")
  assert_equal(source_line, vim.api.nvim_win_get_cursor(0)[1], message .. " line")
end

jump(1, absolute_src, 2, "absolute")
jump(2, relative_src, 3, "repo relative")
jump(3, local_src, 2, "map directory")

vim.cmd.edit(vim.fn.fnameescape(log))
vim.api.nvim_win_set_cursor(0, { 4, 0 })
vim.cmd("XlocGF")
assert_equal(vim.fn.fnamemodify(log, ":p"), vim.api.nvim_buf_get_name(0), "missing source stays in log")

local function assert_invalid_map(lines, message)
  write(bad_log, { "UVM_ERROR L_00000001(2)" })
  write(bad_map, lines)
  vim.cmd.edit(vim.fn.fnameescape(bad_log))
  vim.api.nvim_win_set_cursor(0, { 1, 0 })
  vim.cmd("XlocGF")
  assert_equal(vim.fn.fnamemodify(bad_log, ":p"), vim.api.nvim_buf_get_name(0), message)
end

assert_invalid_map({ "not json" }, "malformed JSON map stays in log")
assert_invalid_map({ "" }, "blank JSONL record stays in log")
assert_invalid_map({
  '{"loc_id":"L_00000001","file":"first.sv"}',
  '{"loc_id":"L_00000001","file":"second.sv"}',
}, "duplicate loc_id map stays in log")
assert_invalid_map({
  '{"loc_id":"L_00000001","file":"first.sv","line":1}',
}, "unknown field map stays in log")
assert_invalid_map({
  '{"loc_id":"L_00000001","file":7}',
}, "wrong field type map stays in log")

vim.cmd.lcd(vim.fn.fnameescape(run))
vim.cmd.edit(vim.fn.fnameescape(no_map_log))
vim.api.nvim_win_set_cursor(0, { 1, 0 })
vim.cmd("XlocGF")
assert_equal(
  vim.fn.fnamemodify(no_map_log, ":p"),
  vim.api.nvim_buf_get_name(0),
  "canonical sidecar absence must not invoke native gf"
)

vim.cmd.qa()
