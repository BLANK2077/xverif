#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
XDEBUG="$ROOT_DIR/../tools/xdebug"
UART_DB="${UART_DB:-$ROOT_DIR/testdata/design/uart/simv.daidir}"
P3_DB="${P3_DB:-$ROOT_DIR/testdata/design/p3_semantics/out/simv.daidir}"
TMP_HOME="$(mktemp -d)"

cleanup() {
  printf '%s\n' '{"api_version":"xdebug.v1","action":"session.kill","target":{"session_id":"all"}}' |
    HOME="$TMP_HOME" "$XDEBUG" --json - >/dev/null 2>&1 || true
  rm -rf "$TMP_HOME"
}
trap cleanup EXIT

require_db() {
  local path="$1"
  if [[ ! -d "$path" ]]; then
    echo "missing regression database: $path" >&2
    exit 1
  fi
}

query() {
  printf '%s\n' "$1" | HOME="$TMP_HOME" "$XDEBUG" --json -
}

query_any() {
  set +e
  printf '%s\n' "$1" | HOME="$TMP_HOME" "$XDEBUG" --json -
  local rc=$?
  set -e
  return 0
}

check_json() {
  python3 -c '
import json
import sys

payload = json.load(sys.stdin)
expr = sys.argv[1]
ns = {"d": payload}
if not eval(expr, {}, ns):
    print(json.dumps(payload, indent=2), file=sys.stderr)
    raise SystemExit(f"check failed: {expr}")
' "$@"
}

require_db "$UART_DB"
require_db "$P3_DB"

printf '%s\n' '{"api_version":"xdebug.v1","action":"actions"}' | "$XDEBUG" --json - | python3 -c '
import json,sys
d=json.load(sys.stdin)["data"]
assert "trace.driver" in d["actions"]
'

printf '%s\n' '{"api_version":"xdebug.v1","action":"schema","args":{"action":"signal.statistics","kind":"request"}}' | "$XDEBUG" --json - | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["ok"] and d["summary"]["action"] == "signal.statistics" and d["summary"]["kind"] == "request"'

query "{\"api_version\":\"xdebug.v1\",\"action\":\"session.open\",\"target\":{\"daidir\":\"$UART_DB\"},\"args\":{\"name\":\"uart_ai\"}}" \
  | check_json 'd["ok"] and d["summary"]["status"] == "opened" and d["session"]["session_id"] == "uart_ai"'

query '{"api_version":"xdebug.v1","action":"trace.driver","target":{"session_id":"uart_ai"},"args":{"signal":"uart_16550.RXDin"},"limits":{"max_results":10}}' \
  | check_json 'd["ok"] and d["summary"]["mode"] == "driver" and d["summary"]["returned_count"] >= 1 and len(d["data"]["paths"]) == d["summary"]["returned_count"] and d["summary"]["total_count"] >= d["summary"]["returned_count"] and all(p.get("source_context") and p.get("signal_path") and any(row.get("active") for row in p["source_context"]) for p in d["data"]["paths"]) and "assignment" not in d["data"] and "dependency_edges" not in d["data"]'

query '{"api_version":"xdebug.v1","action":"trace.driver","target":{"session_id":"uart_ai"},"args":{"signal":"uart_16550.RXDin"},"limits":{"max_results":10}}' \
  | check_json 'd["ok"] and d["summary"]["mode"] == "driver" and len(d["data"]["paths"]) == d["summary"]["returned_count"] and d["summary"]["total_count"] >= d["summary"]["returned_count"] and "assignment" not in d["data"] and "dependency_edges" not in d["data"]'

query '{"api_version":"xdebug.v1","action":"signal.canonicalize","target":{"session_id":"uart_ai"},"args":{"signal":"uart_16550.RXDin"}}' \
  | check_json 'd["ok"] and d["data"]["canonical_path"].endswith("RXDin") and d["data"]["selection_basis"] == "unique_exact_design_match"'

query_any '{"api_version":"xdebug.v1","action":"source.context","args":{"file":"rtl/removed.sv","line":1}}' \
  | check_json 'not d["ok"] and d["error"]["code"] == "UNKNOWN_ACTION"'

query '{"api_version":"xdebug.v1","action":"expr.normalize","args":{"expr":"valid && !ready"}}' \
  | check_json 'd["ok"] and d["summary"]["source"] == "deterministic_syntax_parser" and d["summary"]["confidence"] == "syntax_validated"'

query_any '{"api_version":"xdebug.v1","action":"expr.normalize","args":{"expr":"valid &&"}}' \
  | check_json 'not d["ok"] and d["error"]["code"] == "EXPR_SYNTAX_INVALID" and d["error"]["error_layer"] == "handler" and d["error"]["invalid_arg"] == "args.expr"'

query "{\"api_version\":\"xdebug.v1\",\"action\":\"session.open\",\"target\":{\"daidir\":\"$P3_DB\"},\"args\":{\"name\":\"p3_ai\"}}" \
  | check_json 'd["ok"] and d["summary"]["status"] == "opened" and d["session"]["session_id"] == "p3_ai"'

query '{"api_version":"xdebug.v1","action":"batch","args":{"mode":"continue_on_error","requests":[{"api_version":"xdebug.v1","action":"trace.driver","target":{"session_id":"uart_ai"},"args":{"signal":"uart_16550.TXD"}},{"api_version":"xdebug.v1","action":"signal.resolve","target":{"session_id":"uart_ai"},"args":{"signal":"uart_16550.RXDin"}}]}}' \
  | check_json 'd["ok"] and d["summary"]["count"] == 2'

query '{"api_version":"xdebug.v1","action":"signal.resolve","target":{"session_id":"uart_ai"},"args":{"signal":"uart_16550.RXDin"}}' \
  | check_json 'd["ok"]'

echo "xdebug design semantics regression passed"
