# SDK-free LSF CLI 内部 UDS

`xdebug_lsf` / `xcov_lsf` 会自动启动和连接本用户 manager。UDS 是内部
实现细节，不是用户请求协议；用户始终提交原生 `xdebug.v1` /
`xcov.v1` envelope。

## Readiness 和安全

- 默认 socket：`~/.xverif/lsf-cli/xverif-lsf-<uid>.sock`。
- 可用 `XVERIF_LSF_CLI_SOCKET` 覆盖内部路径，不提供 `--socket`。
- 新 manager 只在 UDS server 成功进入 `listen()` 后通过 ready pipe 发布就绪。
- 不用 socket 文件存在、固定 sleep 或静默 connect retry 代替 ready 合同。
- socket 权限为 `0600`；普通文件、symlink、异主或已被其它服务占用的路径
  fail closed。

## 空闲退出

无 live/opening/unresolved session 且没有正在执行的请求时，manager 默认
5 秒后退出并删除自己创建的 socket。使用
`XVERIF_LSF_CLI_IDLE_TIMEOUT_SEC` 设置无首尾空白的有限正数。
