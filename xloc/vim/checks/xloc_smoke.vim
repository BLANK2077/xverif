set nomore
set noswapfile
set viminfo=

let s:plugin = expand('$XLOC_VIM_PLUGIN')
let s:tmp = expand('$XLOC_VIM_TMP')

if s:plugin ==# '' || s:tmp ==# ''
  cquit
endif

execute 'source' fnameescape(s:plugin)

function! s:Write(path, lines) abort
  call mkdir(fnamemodify(a:path, ':h'), 'p')
  call writefile(a:lines, a:path)
endfunction

function! s:AssertEqual(expect, actual, message) abort
  if a:expect !=# a:actual
    echom 'ASSERT FAILED: ' . a:message
    echom 'expected: ' . string(a:expect)
    echom 'actual:   ' . string(a:actual)
    cquit
  endif
endfunction

let s:repo = s:tmp . '/repo'
let s:run = s:tmp . '/run'
let s:absolute_src = s:tmp . '/abs_src.sv'
let s:relative_src = s:repo . '/tb/relative_src.sv'
let s:local_src = s:run . '/local_src.sv'
let s:log = s:run . '/sim.log'
let s:map = s:log . '.xloc.jsonl'
let s:bad_log = s:run . '/bad.log'
let s:bad_map = s:bad_log . '.xloc.jsonl'
let s:no_map_log = s:run . '/no_map.log'

call s:Write(s:absolute_src, ['abs 1', 'abs 2', 'abs 3'])
call s:Write(s:relative_src, ['rel 1', 'rel 2', 'rel 3'])
call s:Write(s:local_src, ['local 1', 'local 2'])
call s:Write(s:log, [
      \ 'UVM_ERROR L_00000001(2)',
      \ 'UVM_ERROR L_00000002(3)',
      \ 'UVM_ERROR L_00000003(2)',
      \ 'UVM_ERROR L_00000004(1)',
      \ ])
call s:Write(s:map, [
      \ '{"loc_id":"L_00000001","file":"' . substitute(s:absolute_src, '\\', '\\\\', 'g') . '"}',
      \ '{"loc_id":"L_00000002","file":"tb/relative_src.sv"}',
      \ '{"loc_id":"L_00000003","file":"local_src.sv"}',
      \ '{"loc_id":"L_00000004","file":"missing.sv"}',
      \ ])
call s:Write(s:no_map_log, ['UVM_ERROR L_0000000A(1)'])
call s:Write(s:run . '/L_0000000A', ['native gf decoy'])

let g:xloc_repo_root = s:repo

execute 'edit' fnameescape(s:log)
call s:AssertEqual('n', maparg('gf', 'n', 0, 1).mode, 'buffer gf mapping exists')

call cursor(1, 1)
XlocGF
call s:AssertEqual(fnamemodify(s:absolute_src, ':p'), expand('%:p'), 'absolute source jump')
call s:AssertEqual(2, line('.'), 'absolute source line')

execute 'edit' fnameescape(s:log)
call cursor(2, 1)
XlocGF
call s:AssertEqual(fnamemodify(s:relative_src, ':p'), expand('%:p'), 'repo-relative source jump')
call s:AssertEqual(3, line('.'), 'string line jump')

execute 'edit' fnameescape(s:log)
call cursor(3, 1)
XlocGF
call s:AssertEqual(fnamemodify(s:local_src, ':p'), expand('%:p'), 'map-dir source jump')
call s:AssertEqual(2, line('.'), 'sidecar-relative source line')

execute 'edit' fnameescape(s:log)
call cursor(4, 1)
XlocGF
call s:AssertEqual(fnamemodify(s:log, ':p'), expand('%:p'), 'missing source stays in log')

function! s:AssertInvalidMap(lines, message) abort
  call s:Write(s:bad_log, ['UVM_ERROR L_00000001(2)'])
  call s:Write(s:bad_map, a:lines)
  execute 'edit' fnameescape(s:bad_log)
  call cursor(1, 1)
  XlocGF
  call s:AssertEqual(fnamemodify(s:bad_log, ':p'), expand('%:p'), a:message)
endfunction

call s:AssertInvalidMap(['not json'], 'malformed JSON map stays in log')
call s:AssertInvalidMap([''], 'blank JSONL record stays in log')
call s:AssertInvalidMap([
      \ '{"loc_id":"L_00000001","file":"first.sv"}',
      \ '{"loc_id":"L_00000001","file":"second.sv"}',
      \ ], 'duplicate loc_id map stays in log')
call s:AssertInvalidMap([
      \ '{"loc_id":"L_00000001","file":"first.sv","line":1}',
      \ ], 'unknown field map stays in log')
call s:AssertInvalidMap([
      \ '{"loc_id":"L_00000001","file":7}',
      \ ], 'wrong field type map stays in log')

execute 'lcd' fnameescape(s:run)
execute 'edit' fnameescape(s:no_map_log)
call cursor(1, 1)
XlocGF
call s:AssertEqual(fnamemodify(s:no_map_log, ':p'), expand('%:p'),
      \ 'canonical sidecar absence must not invoke native gf')

qa!
