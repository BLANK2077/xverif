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
  let l:parent = fnamemodify(a:path, ':h')
  if !isdirectory(l:parent)
    call mkdir(l:parent, 'p')
  endif
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

call s:Write(s:absolute_src, ['abs 1', 'abs 2', 'abs 3'])
call s:Write(s:relative_src, ['rel 1', 'rel 2', 'rel 3'])
call s:Write(s:local_src, ['local 1', 'local 2'])
call s:Write(s:log, [
      \ 'UVM_ERROR L_00000001',
      \ 'UVM_ERROR L_00000002',
      \ 'UVM_ERROR L_00000003',
      \ 'UVM_ERROR L_00000004',
      \ ])
call s:Write(s:map, [
      \ '{"loc_id":"L_00000001","file":"' . substitute(s:absolute_src, '\\', '\\\\', 'g') . '","line":2,"msg_id":"ABS"}',
      \ '{"loc_id":"L_00000002","file":"tb/relative_src.sv","line":"3","msg_id":"REL"}',
      \ '{"loc_id":"L_00000003","filename":"local_src.sv","line":2,"msg_id":"LOCAL"}',
      \ '{"loc_id":"L_00000004","path":"missing.sv","line":"bad","msg_id":"MISSING"}',
      \ ])

let g:xloc_repo_root = s:repo

execute 'edit' fnameescape(s:log)
call s:AssertEqual(0, empty(maparg('gf', 'n')), 'buffer gf mapping exists')

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
call s:AssertEqual(2, line('.'), 'filename source line')

execute 'edit' fnameescape(s:log)
call cursor(4, 1)
XlocGF
call s:AssertEqual(fnamemodify(s:log, ':p'), expand('%:p'), 'missing source stays in log')

qa!
