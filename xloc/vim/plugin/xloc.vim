" xloc Vim/gVim support.
"
" Opens source locations for L_XXXXXXXX IDs in xloc-compressed logs.
" Fixed map rule:
"   <run-dir>/sim.log
"   <run-dir>/sim.log.xloc.jsonl
"
" Optional configuration:
"   let g:xloc_repo_root = "<project-root>"
"   let g:xloc_auto_enable = 1

if exists('g:loaded_xloc_vim')
  finish
endif
let g:loaded_xloc_vim = 1

if !exists('g:xloc_auto_enable')
  let g:xloc_auto_enable = 1
endif

let s:xloc_record_cache = {}

function! s:XlocIdUnderCursor() abort
  let l:word = expand('<cWORD>')
  let l:id = matchstr(l:word, '\C\<L_[0-9A-F]\{8\}\>')

  if l:id !=# ''
    return l:id
  endif

  return matchstr(getline('.'), '\C\<L_[0-9A-F]\{8\}\>')
endfunction

function! s:XlocFindMapFile() abort
  let l:logfile = expand('%:p')

  if l:logfile ==# ''
    return ''
  endif

  let l:mapfile = l:logfile . '.xloc.jsonl'
  if filereadable(l:mapfile)
    return l:mapfile
  endif

  return ''
endfunction

function! s:XlocParseJsonLine(line) abort
  if a:line =~# '^\s*$'
    throw 'blank JSONL record'
  endif

  if !exists('*json_decode')
    throw 'json_decode() is required'
  endif

  let l:obj = json_decode(a:line)
  if type(l:obj) != type({})
    throw 'record must be a JSON object'
  endif
  if sort(keys(l:obj)) !=# ['file', 'loc_id']
    throw 'record must contain exactly loc_id and file'
  endif
  if type(l:obj.loc_id) != type('')
        \ || l:obj.loc_id !~# '\C^L_[0-9A-F]\{8\}$'
    throw 'loc_id must match L_[0-9A-F]{8}'
  endif
  if type(l:obj.file) != type('') || l:obj.file ==# ''
        \ || l:obj.file =~# "[\r\n]"
    throw 'file must be a non-empty single-line string'
  endif
  return l:obj
endfunction

function! s:XlocLookupRecord(mapfile, id) abort
  let l:mapfile = fnamemodify(a:mapfile, ':p')
  let l:mtime = getftime(l:mapfile)
  if !has_key(s:xloc_record_cache, l:mapfile)
        \ || get(s:xloc_record_cache[l:mapfile], 'mtime', -1) != l:mtime
    let l:records = {}
    let l:line_number = 0
    try
      for l:line in readfile(l:mapfile)
        let l:line_number += 1
        let l:record = s:XlocParseJsonLine(l:line)
        if has_key(l:records, l:record.loc_id)
          throw 'duplicate loc_id ' . l:record.loc_id
        endif
        let l:records[l:record.loc_id] = l:record
      endfor
    catch
      echohl WarningMsg
      echom 'xloc: invalid map ' . l:mapfile . ':' . l:line_number
            \ . ': ' . v:exception
      echohl None
      return {}
    endtry
    let s:xloc_record_cache[l:mapfile] = {
          \ 'mtime': l:mtime,
          \ 'records': l:records,
          \ }
  endif

  let l:records = s:xloc_record_cache[l:mapfile].records
  return get(l:records, a:id, {})
endfunction

function! s:XlocLineUnderCursor(id) abort
  return str2nr(matchstr(getline('.'), a:id . '(\zs\d\+\ze)'))
endfunction

function! s:XlocResolvePath(file, mapfile) abort
  let l:file = a:file
  if l:file ==# ''
    return ''
  endif

  if l:file =~# '^\(/\|[A-Za-z]:[\\/]\)'
    return fnamemodify(l:file, ':p')
  endif

  let l:roots = []
  if exists('g:xloc_repo_root') && g:xloc_repo_root !=# ''
    call add(l:roots, g:xloc_repo_root)
  endif
  call add(l:roots, fnamemodify(a:mapfile, ':p:h'))
  call add(l:roots, getcwd())

  for l:root in l:roots
    let l:path = fnamemodify(l:root . '/' . l:file, ':p')
    if filereadable(l:path)
      return l:path
    endif
  endfor

  if exists('g:xloc_repo_root') && g:xloc_repo_root !=# ''
    return fnamemodify(g:xloc_repo_root . '/' . l:file, ':p')
  endif

  return fnamemodify(fnamemodify(a:mapfile, ':p:h') . '/' . l:file, ':p')
endfunction

function! s:XlocNativeGF() abort
  try
    normal! gf
  catch /^Vim\%((\a\+)\)\=:E/
    echohl WarningMsg
    echom 'xloc: native gf failed: ' . v:exception
    echohl None
  endtry
endfunction

function! XlocGF() abort
  let l:id = s:XlocIdUnderCursor()
  if l:id ==# ''
    call s:XlocNativeGF()
    return
  endif

  let l:mapfile = s:XlocFindMapFile()
  if l:mapfile ==# ''
    echohl WarningMsg
    echom 'xloc: canonical sidecar map not found for ' . expand('%:p')
    echohl None
    return
  endif

  let l:rec = s:XlocLookupRecord(l:mapfile, l:id)
  if empty(l:rec)
    echohl WarningMsg
    echom 'xloc: loc_id not found: ' . l:id . ' in ' . l:mapfile
    echohl None
    return
  endif

  let l:file = get(l:rec, 'file', '')
  if l:file ==# ''
    echohl WarningMsg
    echom 'xloc: record has no file field: ' . l:id
    echohl None
    return
  endif

  let l:line = s:XlocLineUnderCursor(l:id)
  if l:line <= 0
    echohl WarningMsg
    echom 'xloc: log location has no positive line number: ' . l:id
    echohl None
    return
  endif
  let l:path = s:XlocResolvePath(l:file, l:mapfile)
  if !filereadable(l:path)
    echohl WarningMsg
    echom 'xloc: source file not readable: ' . l:path
    echohl None
    return
  endif

  execute 'edit +' . l:line . ' ' . fnameescape(l:path)
  normal! zz
endfunction

function! s:XlocMaybeMapBuffer() abort
  if !get(g:, 'xloc_auto_enable', 1)
    return
  endif

  if expand('%:e') !=# 'log'
    return
  endif

  if !filereadable(expand('%:p') . '.xloc.jsonl')
    return
  endif

  nnoremap <buffer> <silent> gf :<C-U>XlocGF<CR>
endfunction

command! XlocGF call XlocGF()

augroup xloc_gf
  autocmd!
  autocmd BufReadPost,BufNewFile *.log call s:XlocMaybeMapBuffer()
augroup END

call s:XlocMaybeMapBuffer()
