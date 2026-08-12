from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO


class ProgressReporter:
    """Durable progress, heartbeat, and wall-clock timing for long operations."""

    def __init__(
        self,
        operation: str,
        run_dir: Path,
        *,
        total: int | None = None,
        interval_sec: float = 30.0,
        stream: TextIO | None = None,
        print_item_events: bool = True,
        line_writer: Callable[[str], None] | None = None,
        owns_running_marker: bool = True,
    ) -> None:
        self.operation = operation
        self.run_dir = run_dir
        self.total = total
        self.interval_sec = interval_sec
        self.stream = stream or sys.__stderr__
        self.print_item_events = print_item_events
        self.line_writer = line_writer
        self.owns_running_marker = owns_running_marker
        self.started_monotonic = time.monotonic()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.finished_at: str | None = None
        self.items: list[dict[str, Any]] = []
        self._active: dict[str, dict[str, Any]] = {}
        self._completed = 0
        self._lock = threading.Lock()
        self._emit_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._finished_payload: dict[str, Any] | None = None
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.run_dir / "progress.jsonl"

    def start(self, *, heartbeat: bool = True) -> None:
        self._emit("start")
        if heartbeat and self.interval_sec > 0:
            self._thread = threading.Thread(
                target=self._heartbeat_loop,
                name="xverif-progress",
                daemon=True,
            )
            self._thread.start()

    def set_total(self, total: int) -> None:
        with self._lock:
            self.total = total
        self._emit("total")

    def item_start(self, item_id: str, *, detail: str | None = None) -> None:
        now = time.monotonic()
        with self._lock:
            self._active[item_id] = {
                "started_monotonic": now,
                "phase_started_monotonic": now,
                "detail": detail,
                "phases": [],
            }
        self._emit("item_start", item_id=item_id, detail=detail)

    def item_phase(self, item_id: str, detail: str) -> None:
        now = time.monotonic()
        with self._lock:
            active = self._active.get(item_id)
            if active is None:
                return
            previous = active.get("detail")
            if previous is not None:
                active["phases"].append(
                    {
                        "name": previous,
                        "duration_sec": now - active["phase_started_monotonic"],
                    }
                )
            active["detail"] = detail
            active["phase_started_monotonic"] = now
        self._emit("item_phase", item_id=item_id, detail=detail)

    def item_finish(self, item_id: str, *, outcome: str = "passed") -> None:
        now = time.monotonic()
        with self._lock:
            active = self._active.pop(item_id, None)
            if active is None:
                return
            detail = active.get("detail")
            if detail is not None:
                active["phases"].append(
                    {
                        "name": detail,
                        "duration_sec": now - active["phase_started_monotonic"],
                    }
                )
            record = {
                "id": item_id,
                "outcome": outcome,
                "duration_sec": now - active["started_monotonic"],
                "phases": active["phases"],
            }
            self.items.append(record)
            self._completed += 1
        self._emit(
            "item_finish",
            item_id=item_id,
            outcome=outcome,
            duration_sec=record["duration_sec"],
        )

    def finish(self, *, outcome: str) -> dict[str, Any]:
        if self._finished_payload is not None:
            return self._finished_payload
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_sec + 1.0))
        self.finished_at = datetime.now(timezone.utc).isoformat()
        payload = self.snapshot(outcome=outcome)
        temporary = self.run_dir / ".timing.json.tmp"
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.run_dir / "timing.json")
        if self.owns_running_marker:
            (self.run_dir / "RUNNING").unlink(missing_ok=True)
        self._emit("finish", outcome=outcome)
        close = getattr(self.line_writer, "close", None)
        if close is not None:
            close()
        self._finished_payload = payload
        return payload

    def snapshot(self, *, outcome: str | None = None) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            active = [
                {
                    "id": item_id,
                    "detail": state.get("detail"),
                    "duration_sec": now - state["started_monotonic"],
                }
                for item_id, state in sorted(self._active.items())
            ]
            items = sorted(
                (dict(item) for item in self.items),
                key=lambda item: item["duration_sec"],
                reverse=True,
            )
            completed = self._completed
            total = self.total
        return {
            "schema_version": "xverif-operation-timing.v1",
            "operation": self.operation,
            "outcome": outcome or "running",
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_sec": now - self.started_monotonic,
            "completed": completed,
            "total": total,
            "active": active,
            "items": items,
        }

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self.interval_sec):
            self._emit("heartbeat")

    def _emit(self, event: str, **fields: Any) -> None:
        snapshot = self.snapshot()
        record = {
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **fields,
            "elapsed_sec": snapshot["duration_sec"],
            "completed": snapshot["completed"],
            "total": snapshot["total"],
            "active": snapshot["active"],
        }
        with self._emit_lock:
            with self.events_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
                stream.flush()
            if event in {"item_start", "item_phase", "item_finish"} and not self.print_item_events:
                return
            active = ", ".join(
                _active_label(item) for item in snapshot["active"][:4]
            ) or "none"
            total = "?" if snapshot["total"] is None else str(snapshot["total"])
            extra = ""
            if event == "item_finish":
                extra = f" item={fields['item_id']} duration={fields['duration_sec']:.1f}s"
            elif event in {"item_start", "item_phase"}:
                extra = f" item={fields['item_id']}"
                if fields.get("detail"):
                    extra += f" phase={fields['detail']}"
            elif event == "finish":
                extra = f" outcome={fields['outcome']}"
            line = (
                f"[xverif-progress] operation={self.operation} event={event} "
                f"completed={snapshot['completed']}/{total} "
                f"elapsed={snapshot['duration_sec']:.1f}s active={active}{extra}"
            )
            if self.line_writer is not None:
                self.line_writer(line)
            else:
                print(line, file=self.stream, flush=True)


def _active_label(item: dict[str, Any]) -> str:
    label = str(item["id"])
    if item.get("detail"):
        label += f":{item['detail']}"
    return f"{label}({item['duration_sec']:.1f}s)"
