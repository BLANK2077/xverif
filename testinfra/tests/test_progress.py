import io
import json
import time
from pathlib import Path

import jsonschema

from testinfra.xverif_test.progress import ProgressReporter
from testinfra.xverif_test.plugin import _slow_items_text


ROOT = Path(__file__).resolve().parents[2]


def test_progress_records_heartbeats_phases_and_slowest_first(tmp_path: Path) -> None:
    stream = io.StringIO()
    reporter = ProgressReporter(
        "fixture-validation", tmp_path, total=2, interval_sec=0.01, stream=stream
    )
    reporter.start()
    reporter.item_start("slow", detail="builder")
    time.sleep(0.025)
    reporter.item_phase("slow", "probe_1_of_1")
    reporter.item_finish("slow")
    reporter.item_start("fast", detail="cache_validation")
    reporter.item_finish("fast")
    payload = reporter.finish(outcome="passed")

    assert payload["completed"] == payload["total"] == 2
    assert [item["id"] for item in payload["items"]] == ["slow", "fast"]
    assert [phase["name"] for phase in payload["items"][0]["phases"]] == [
        "builder", "probe_1_of_1",
    ]
    events = [json.loads(line) for line in (tmp_path / "progress.jsonl").read_text().splitlines()]
    assert "heartbeat" in {event["event"] for event in events}
    assert "active=slow:builder" in stream.getvalue()

    schema = json.loads(
        (ROOT / "testinfra/schemas/operation-timing.v1.schema.json").read_text()
    )
    jsonschema.Draft202012Validator(schema).validate(
        json.loads((tmp_path / "timing.json").read_text())
    )


def test_progress_failure_is_durable_and_clears_running_marker(tmp_path: Path) -> None:
    (tmp_path / "RUNNING").write_text("\n")
    reporter = ProgressReporter(
        "fixture-prepare", tmp_path, total=1, interval_sec=60, stream=io.StringIO()
    )
    reporter.start()
    reporter.item_start("broken", detail="builder")
    reporter.item_finish("broken", outcome="failed")
    payload = reporter.finish(outcome="failed")

    assert payload["outcome"] == "failed"
    assert payload["items"][0]["outcome"] == "failed"
    assert not (tmp_path / "RUNNING").exists()


def test_progress_line_writer_bypasses_stream_capture(tmp_path: Path) -> None:
    lines: list[str] = []
    stream = io.StringIO()
    reporter = ProgressReporter(
        "gate:fast",
        tmp_path,
        total=0,
        interval_sec=60,
        stream=stream,
        line_writer=lines.append,
        owns_running_marker=False,
    )
    reporter.start(heartbeat=False)
    reporter.finish(outcome="passed")

    assert stream.getvalue() == ""
    assert ["event=start" in lines[0], "event=finish" in lines[-1]] == [True, True]


def test_progress_can_leave_shared_running_marker_to_result_manager(tmp_path: Path) -> None:
    (tmp_path / "RUNNING").write_text("\n")
    reporter = ProgressReporter(
        "gate:fast",
        tmp_path,
        total=0,
        interval_sec=60,
        stream=io.StringIO(),
        owns_running_marker=False,
    )
    reporter.start(heartbeat=False)
    reporter.finish(outcome="passed")

    assert (tmp_path / "RUNNING").exists()


def test_slow_item_summary_includes_slowest_fixture_phase() -> None:
    text = _slow_items_text([
        {
            "id": "xdebug.axi_vip",
            "duration_sec": 12.5,
            "phases": [
                {"name": "builder", "duration_sec": 11.0},
                {"name": "probe_1_of_1", "duration_sec": 1.5},
            ],
        }
    ])
    assert text == "xdebug.axi_vip=12.5s(builder=11.0s)"


def test_progress_finish_is_idempotent(tmp_path: Path) -> None:
    reporter = ProgressReporter(
        "gate:fast", tmp_path, total=0, interval_sec=60, stream=io.StringIO()
    )
    reporter.start(heartbeat=False)
    first = reporter.finish(outcome="failed")
    second = reporter.finish(outcome="failed")

    assert second is first
    events = [json.loads(line)["event"] for line in (tmp_path / "progress.jsonl").read_text().splitlines()]
    assert events.count("finish") == 1
