# 生成的 Surface 示例

Canonical source: `skills/xverif/specs/examples.yaml`。

## CLI

```json
{
  "api_version": "xdebug.v1",
  "action": "value.at",
  "target": {
    "session_id": "case_a"
  },
  "args": {
    "list": "ready_path",
    "times": [
      "100ns",
      "120ns"
    ],
    "clock": "top.clk"
  }
}
```

## MCP

```json
{
  "tool": "xverif_debug_query",
  "args": {
    "session_id": "case_a",
    "action": "value.at",
    "args": {
      "list": "ready_path",
      "times": [
        "100ns",
        "120ns"
      ],
      "clock": "top.clk"
    }
  }
}
```

## SDK-free LSF CLI

```json
{
  "api_version": "xdebug.v1",
  "action": "value.at",
  "target": {
    "session_id": "case_a"
  },
  "args": {
    "list": "ready_path",
    "times": [
      "100ns",
      "120ns"
    ],
    "clock": "top.clk"
  }
}
```
