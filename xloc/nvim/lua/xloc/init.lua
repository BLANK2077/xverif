local M = {}

local config = {
  auto_enable = true,
  repo_root = nil,
}

local record_cache = {}
local loc_id_pattern = "L_" .. string.rep("[0-9A-F]", 8)

local function notify(message)
  vim.notify("xloc: " .. message, vim.log.levels.WARN)
end

local function location_id_under_cursor()
  local line = vim.api.nvim_get_current_line()
  local offset = 1
  while offset <= #line do
    local first, last = line:find(loc_id_pattern, offset)
    if not first then
      return nil, nil
    end
    local before = first > 1 and line:sub(first - 1, first - 1) or ""
    local after = last < #line and line:sub(last + 1, last + 1) or ""
    if not before:match("[A-Za-z0-9_]")
        and not after:match("[A-Za-z0-9_]") then
      local id = line:sub(first, last)
      return id, tonumber(line:match(id .. "%((%d+)%)"))
    end
    offset = last + 1
  end
  return nil, nil
end

local function map_file()
  local log_file = vim.api.nvim_buf_get_name(0)
  if log_file == "" then
    return nil
  end
  local path = log_file .. ".xloc.jsonl"
  return vim.fn.filereadable(path) == 1 and path or nil
end

local function cache_entry(path)
  path = vim.fn.fnamemodify(path, ":p")
  local stat = vim.uv.fs_stat(path)
  if not stat then
    return nil
  end
  local mtime = stat.mtime.sec * 1000000000 + stat.mtime.nsec
  local entry = record_cache[path]
  if not entry or entry.mtime ~= mtime then
    entry = { mtime = mtime, records = {} }
    record_cache[path] = entry
  end
  return entry
end

local function valid_record(record)
  if type(record) ~= "table" then
    return false, "record must be a JSON object"
  end
  local key_count = 0
  for key, _ in pairs(record) do
    key_count = key_count + 1
    if key ~= "loc_id" and key ~= "file" then
      return false, "record contains unknown field: " .. tostring(key)
    end
  end
  if key_count ~= 2 then
    return false, "record must contain exactly loc_id and file"
  end
  if type(record.loc_id) ~= "string"
      or not record.loc_id:match("^" .. loc_id_pattern .. "$") then
    return false, "loc_id must match L_[0-9A-F]{8}"
  end
  if type(record.file) ~= "string" or record.file == ""
      or record.file:find("[\r\n]") then
    return false, "file must be a non-empty single-line string"
  end
  return true, nil
end

local function load_records(path)
  local records = {}
  local line_number = 0
  local ok, error_message = pcall(function()
    for line in io.lines(path) do
      line_number = line_number + 1
      if line:match("^%s*$") then
        error("blank JSONL record")
      end
      local record = vim.json.decode(line)
      local valid, reason = valid_record(record)
      if not valid then
        error(reason)
      end
      if records[record.loc_id] then
        error("duplicate loc_id " .. record.loc_id)
      end
      records[record.loc_id] = record
    end
  end)
  if not ok then
    return nil, string.format(
      "invalid map %s:%d: %s",
      path,
      line_number,
      error_message
    )
  end
  return records, nil
end

local function lookup_record(path, id)
  local entry = cache_entry(path)
  if not entry then
    return nil, "sidecar map is not readable: " .. path
  end

  if not entry.loaded then
    local records, error_message = load_records(path)
    if not records then
      return nil, error_message
    end
    entry.records = records
    entry.loaded = true
  end
  return entry.records[id], nil
end

local function record_file(record)
  return type(record.file) == "string" and record.file or nil
end

local function absolute_path(path)
  return path:match("^/") or path:match("^[A-Za-z]:[\\/]")
end

local function resolve_path(file, sidecar)
  if not file or file == "" then
    return nil
  end
  if absolute_path(file) then
    return vim.fn.fnamemodify(file, ":p")
  end

  local roots = {}
  if config.repo_root and config.repo_root ~= "" then
    table.insert(roots, config.repo_root)
  end
  table.insert(roots, vim.fn.fnamemodify(sidecar, ":p:h"))
  table.insert(roots, vim.fn.getcwd())

  for _, root in ipairs(roots) do
    local path = vim.fn.fnamemodify(root .. "/" .. file, ":p")
    if vim.fn.filereadable(path) == 1 then
      return path
    end
  end

  if config.repo_root and config.repo_root ~= "" then
    return vim.fn.fnamemodify(config.repo_root .. "/" .. file, ":p")
  end
  return vim.fn.fnamemodify(vim.fn.fnamemodify(sidecar, ":p:h") .. "/" .. file, ":p")
end

local function native_gf()
  local ok, error_message = pcall(vim.cmd, "normal! gf")
  if not ok then
    notify("native gf failed: " .. error_message)
  end
end

function M.gf()
  local id, line = location_id_under_cursor()
  if not id then
    native_gf()
    return
  end
  if not line or line <= 0 then
    notify("log location has no positive line number: " .. id)
    return
  end

  local sidecar = map_file()
  if not sidecar then
    notify("canonical sidecar map not found for " .. vim.api.nvim_buf_get_name(0))
    return
  end

  local record, map_error = lookup_record(sidecar, id)
  if map_error then
    notify(map_error)
    return
  end
  if not record then
    notify("loc_id not found: " .. id .. " in " .. sidecar)
    return
  end

  local file = record_file(record)
  if not file then
    notify("record has no file field: " .. id)
    return
  end

  local path = resolve_path(file, sidecar)
  if vim.fn.filereadable(path) ~= 1 then
    notify("source file not readable: " .. path)
    return
  end

  vim.cmd.edit(vim.fn.fnameescape(path))
  vim.api.nvim_win_set_cursor(0, { line, 0 })
  vim.cmd("normal! zz")
end

function M.maybe_map_buffer(buffer)
  if not config.auto_enable then
    return
  end
  buffer = buffer or vim.api.nvim_get_current_buf()
  local name = vim.api.nvim_buf_get_name(buffer)
  if vim.fn.fnamemodify(name, ":e") ~= "log" or vim.fn.filereadable(name .. ".xloc.jsonl") ~= 1 then
    return
  end
  vim.keymap.set("n", "gf", M.gf, { buffer = buffer, silent = true, desc = "xloc: jump to source location" })
end

function M.setup(options)
  options = options or {}
  config.auto_enable = options.auto_enable
  if config.auto_enable == nil then
    config.auto_enable = vim.g.xloc_auto_enable ~= 0
  end
  config.repo_root = options.repo_root or vim.g.xloc_repo_root

  vim.api.nvim_create_user_command("XlocGF", M.gf, { force = true })
  local group = vim.api.nvim_create_augroup("xloc_gf", { clear = true })
  vim.api.nvim_create_autocmd({ "BufReadPost", "BufNewFile" }, {
    group = group,
    pattern = "*.log",
    callback = function(args)
      M.maybe_map_buffer(args.buf)
    end,
  })
  M.maybe_map_buffer()
end

return M
