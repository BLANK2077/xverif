from __future__ import annotations

from pathlib import Path
import shlex
import sys
from types import SimpleNamespace

import pytest

from xcov.actions import _code_coverage_from_urg, _coverage_from_urg, _metrics_from_urg
from xcov.errors import XcovError
from xcov.gap_export import build_gap_payload, parse_urg_gap_report
from xcov.urg_summary import REQUIRED_ARTIFACTS, parse_urg_summary


SESSION_XML = """\
<session version="1.1">
  <hvp><datadef>
    <metdef name="Line" type="ratio" aggregator="average" builtin="1" />
    <metdef name="Assert" type="ratio" aggregator="average" builtin="1" />
    <metdef name="Group" type="ratio" aggregator="average" builtin="1" />
  </datadef></hvp>
  <old_coverage>
    <scope type="instance" name="top">
      <metric name="Line" value="8/10" excl="0" />
      <metric name="Assert" value="1/2" excl="0" />
      <scope type="instance" name="u0">
        <metric name="Line" value="1/2" excl="0" />
        <metric name="Assert" value="1/1" excl="0" />
      </scope>
    </scope>
    <scope type="Groups" name="top">
      <attr type="Group Summary" value="3/4" excl="0" />
      <scope type="Cover Group" name="dut::cg">
        <scope type="Covergroup Variant" name="top.u0::cg">
          <metric name="Group" value="3/4" excl="0" />
          <attr name="Score" value="75%" />
          <scope type="Coverage Point" name="cp_direct">
            <metric name="Point" value="1/2" excl="0" />
            <attr name="Score" value="50%" />
          </scope>
          <scope type="Coverage Instance" name="cg_i">
            <metric name="Group" value="3/4" excl="0" />
            <attr name="Score" value="75%" />
            <scope type="Coverage Point" name="cp">
              <metric name="Point" value="1/2" excl="0" />
              <attr name="Score" value="50%" />
            </scope>
            <scope type="Cross Coverage" name="cx">
              <metric name="Cross" value="2/2" excl="0" />
              <attr name="Score" value="100%" />
            </scope>
          </scope>
        </scope>
      </scope>
    </scope>
    <scope type="Asserts" name="top">
      <scope type="Assertion" name="top.u0.a_ok">
        <attr type="attempt" value="12" />
        <attr type="success" value="9" />
        <attr type="failure" value="1" />
        <attr type="incomplete" value="0" />
      </scope>
      <scope type="Cover Property" name="top.u0.c_miss">
        <attr type="attempt" value="12" />
        <attr type="all match" value="0" />
        <attr type="mismatches" value="10" />
        <attr type="incomplete" value="0" />
      </scope>
    </scope>
    <scope type="assert" name="Statistics" />
  </old_coverage>
</session>
"""


def _report(tmp_path: Path, xml: str = SESSION_XML) -> Path:
    report = tmp_path / "report"
    report.mkdir()
    for name in REQUIRED_ARTIFACTS:
        content = "placeholder\n"
        if name == "session.xml":
            content = xml
        elif name == "tests.txt":
            content = (
                "Tests\n\nTotal tests in report: 1\n"
                "-------------------------------------------------------------------------------\n"
                "Data from the following tests was used to generate this report\n"
                "/shared/run/test_a\n"
            )
        (report / name).write_text(content, encoding="utf-8")
    return report


def test_urg_assert_detail_parser_builds_semantic_gaps(tmp_path):
    report = tmp_path / "asserts.txt"
    report.write_text(
        """Assertions Uncovered:
ASSERTIONS CATEGORY SEVERITY ATTEMPTS REAL SUCCESSES FAILURES INCOMPLETE
top.u0.a_missing 0 0 41 0 0 0
-------------------------------------------------------------------------------
Cover Properties Uncovered:
COVER PROPERTIES CATEGORY SEVERITY ATTEMPTS MATCHES INCOMPLETE
top.u0.c_missing 0 0 41 0 0
-------------------------------------------------------------------------------
""",
        encoding="utf-8",
    )
    rows = parse_urg_gap_report("assert", report)
    assert [(row["type"], row["scope"], row["name"]) for row in rows] == [
        ("npiCovAssert", "top.u0", "a_missing"),
        ("npiCovCoverProperty", "top.u0", "c_missing"),
    ]
    payload = build_gap_payload("assert", "sample.vdb", rows)
    assert payload["exclusion_locator"]["version"] == "xcov.urg_semantic.v1"
    assert "_exclude_targets" not in payload["gaps"][0]


def test_urg_functional_detail_parser_builds_bin_semantics(tmp_path):
    report = tmp_path / "grpinfo.txt"
    report.write_text(
        """Group : top::cg
===============================================================================
Group : top::cg
===============================================================================
Source File(s) :

/design/top.sv
Summary for Variable cp_data
User Defined Bins for cp_data
Uncovered bins
NAME COUNT AT LEAST NUMBER
other 0 1 1
-------------------------------------------------------------------------------
Summary for Cross cross_a
Automatically Generated Cross Bins for cross_a
Uncovered bins
A B COUNT AT LEAST NUMBER
[a] [b] 0 1 1
-------------------------------------------------------------------------------
""",
        encoding="utf-8",
    )
    rows = parse_urg_gap_report("functional", report)
    assert [(row["coverpoint"], row["cross"], row["bin"]) for row in rows] == [
        ("cp_data", None, "other"),
        (None, "cross_a", "[a] [b]"),
    ]
    assert all(row["type"] == "npiCovCoverBin" for row in rows)


def test_content_addressed_urg_cache_cold_warm_corrupt_and_el_invalidation(
    monkeypatch,
    tmp_path,
):
    from xcov import urg_cache

    vdb = tmp_path / "sample.vdb"
    vdb.mkdir()
    (vdb / "content.bin").write_bytes(b"coverage-v1")
    cache = tmp_path / "cache"
    monkeypatch.setattr(
        urg_cache,
        "_urg_identity",
        lambda: {"path": "vcs-bin/urg", "size_bytes": 1, "mtime_ns": 1},
    )

    class FakeRunner:
        def __init__(self):
            self.calls = []

        def run(self, argv, timeout=None):
            self.calls.append(list(argv))
            report = Path(argv[argv.index("-report") + 1])
            for name in REQUIRED_ARTIFACTS:
                content = "placeholder\n"
                if name == "session.xml":
                    content = SESSION_XML
                elif name == "tests.txt":
                    content = (
                        "Total tests in report: 1\n"
                        "Data from the following tests was used to generate this report\n"
                        "test0\n"
                    )
                (report / name).write_text(content, encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

    runner = FakeRunner()
    first, first_meta = urg_cache.load_cached_urg_summary(
        str(vdb), cache_root=cache, runner=runner,
    )
    second, second_meta = urg_cache.load_cached_urg_summary(
        str(vdb), cache_root=cache, runner=runner,
    )
    assert first.tests == second.tests == ("test0",)
    assert first_meta["hit"] is False
    assert second_meta["hit"] is True
    assert first_meta["urg_execution"]["submitted"] is True
    assert second_meta["urg_execution"] == {
        "backend": "injected",
        "submitted": False,
        "status": "cache_hit",
        "queue": None,
        "resource": None,
        "job_name": None,
        "job_id": None,
        "exit_status": None,
    }
    assert first_meta["key"] == second_meta["key"]
    assert len(runner.calls) == 1
    manifest = __import__("json").loads(
        (Path(first_meta["entry"]) / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["complete"] is True
    assert set(manifest["artifacts"]) == set(REQUIRED_ARTIFACTS)
    assert manifest["semantic_counts"] == {
        "metric_count": 3,
        "test_count": 1,
        "scope_count": 2,
        "functional_row_count": 3,
        "assertion_row_count": 2,
    }
    assert (Path(first_meta["entry"]) / "COMPLETE").read_text().strip() == first_meta["key"]

    entry = Path(second_meta["entry"])
    (entry / "report" / "session.xml").write_text("", encoding="utf-8")
    _, repaired_meta = urg_cache.load_cached_urg_summary(
        str(vdb), cache_root=cache, runner=runner,
    )
    assert repaired_meta["hit"] is False
    assert len(runner.calls) == 2
    assert any((cache / "quarantine").iterdir())

    el = tmp_path / "current.el"
    el.write_bytes(b"exclude-v1")
    _, excluded_meta = urg_cache.load_cached_urg_summary(
        str(vdb), cache_root=cache, el_path=str(el), runner=runner,
    )
    assert excluded_meta["hit"] is False
    assert excluded_meta["key"] != repaired_meta["key"]
    assert len(runner.calls) == 3
    assert "-elfile" in runner.calls[-1]
    _, manifest_meta = urg_cache.load_cached_urg_summary(
        str(vdb), cache_root=cache,
        run_manifest_digest="a" * 64, runner=runner,
    )
    assert manifest_meta["key"] not in {
        repaired_meta["key"], excluded_meta["key"],
    }
    assert len(runner.calls) == 4


def _fake_command(path: Path, body: str) -> str:
    path.write_text("#!/usr/bin/env python3\n" + body + "\n", encoding="utf-8")
    path.chmod(0o755)
    return str(path)


def _fake_lsf_commands() -> tuple[str, str]:
    return (
        shlex.join([sys.executable, "-m", "xverif_loop.lsf.fake_bsub"]),
        shlex.join([sys.executable, "-m", "xverif_loop.lsf.fake_bkill"]),
    )


def test_urg_runner_does_not_inherit_outer_lsf_without_explicit_backend(
    monkeypatch, tmp_path,
):
    from xcov.urg_runner import UrgRunner

    fake = _fake_command(tmp_path / "urg-direct", "raise SystemExit(0)")
    monkeypatch.setenv("XVERIF_LSF_BSUB", "'invalid outer command")
    monkeypatch.delenv("XVERIF_XCOV_URG_BACKEND", raising=False)

    runner = UrgRunner()

    assert runner.backend == "direct"
    assert runner.build_argv([fake]) == [fake]


def test_urg_runner_lsf_requires_its_own_queue(monkeypatch):
    from xcov.errors import XcovError
    from xcov.urg_runner import UrgRunner

    monkeypatch.setenv("XVERIF_XCOV_URG_BACKEND", "lsf")
    monkeypatch.delenv("XVERIF_XCOV_URG_QUEUE", raising=False)

    with pytest.raises(XcovError) as caught:
        UrgRunner()
    assert caught.value.code == "XCOV_URG_CONFIG_INVALID"


def test_urg_runner_lsf_rejects_interactive_bsub_and_canonicalizes_paths(
    tmp_path,
):
    from xcov.errors import XcovError
    from xcov.urg_runner import UrgRunner

    with pytest.raises(XcovError) as caught:
        UrgRunner(
            backend="lsf",
            bsub_cmd="bsub -I",
            bkill_cmd="bkill",
            queue="urg_queue",
        )
    assert caught.value.code == "XCOV_URG_CONFIG_INVALID"

    fake = _fake_command(tmp_path / "urg-paths", "raise SystemExit(0)")
    runner = UrgRunner(
        backend="lsf",
        bsub_cmd="bsub-wrapper",
        bkill_cmd="bkill-wrapper",
        queue="urg_queue",
    )
    argv = runner.build_argv([
        fake,
        "-dir", "relative.vdb",
        "-report", "relative-report",
        "-hier", "relative.hier",
        "-elfile", "relative.el",
    ], job_name="fixed-job")
    for option in ("-dir", "-report", "-hier", "-elfile"):
        assert Path(argv[argv.index(option) + 1]).is_absolute()
    assert argv[:8] == [
        "bsub-wrapper", "-K", "-J", "fixed-job",
        "-q", "urg_queue", fake, "-dir",
    ]


def test_urg_runner_fake_lsf_success_uses_batch_k_and_records_job(
    monkeypatch, tmp_path,
):
    from xcov.urg_runner import UrgRunner

    fake = _fake_command(
        tmp_path / "urg-success",
        "import sys\nprint('inner urg complete')\nraise SystemExit(0)",
    )
    bsub, bkill = _fake_lsf_commands()
    monkeypatch.setenv("FAKE_BSUB_STDOUT_NOISE_BEFORE_READY", "1")
    monkeypatch.setenv("FAKE_BSUB_SCHEDULER_FRAMING", "1")
    runner = UrgRunner(
        backend="lsf",
        bsub_cmd=bsub,
        bkill_cmd=bkill,
        queue="urg_queue",
        resource="select[mem>2048]",
        startup_timeout_sec=1.0,
        run_timeout_sec=2.0,
    )

    result = runner.run([fake])

    assert result.returncode == 0, result.stderr
    assert "-K" in result.argv and "-I" not in result.argv
    assert result.argv[result.argv.index("-q") + 1] == "urg_queue"
    assert result.argv[result.argv.index("-R") + 1] == "select[mem>2048]"
    assert result.argv[result.argv.index("-J") + 1].startswith("xverif_xcov_urg_")
    assert result.scheduler["backend"] == "lsf"
    assert result.scheduler["submitted"] is True
    assert result.scheduler["status"] == "completed"
    assert result.scheduler["job_id"] == "123"
    assert result.scheduler["exit_status"] == 0


def test_urg_runner_fake_lsf_fast_completion_preserves_zero_exit(
    monkeypatch, tmp_path,
):
    from xcov.urg_runner import UrgRunner

    fake = _fake_command(tmp_path / "urg-fast", "raise SystemExit(0)")
    bsub, bkill = _fake_lsf_commands()
    monkeypatch.setenv("FAKE_BSUB_STDOUT_NOISE_BEFORE_READY", "1")
    monkeypatch.delenv("FAKE_BSUB_SCHEDULER_FRAMING", raising=False)
    runner = UrgRunner(
        backend="lsf",
        bsub_cmd=bsub,
        bkill_cmd=bkill,
        queue="urg_fast",
        startup_timeout_sec=1.0,
        run_timeout_sec=1.0,
    )

    result = runner.run([fake])

    assert result.returncode == 0
    assert result.scheduler["submitted"] is True
    assert result.scheduler["status"] == "completed"
    assert result.scheduler["exit_status"] == 0


def test_urg_runner_fake_lsf_rejection_without_job_id_is_not_submitted(
    monkeypatch, tmp_path,
):
    from xcov.urg_runner import UrgRunner

    fake = _fake_command(tmp_path / "urg-rejected", "raise SystemExit(0)")
    bsub, bkill = _fake_lsf_commands()
    monkeypatch.delenv("FAKE_BSUB_STDOUT_NOISE_BEFORE_READY", raising=False)
    monkeypatch.delenv("FAKE_BSUB_SCHEDULER_FRAMING", raising=False)
    monkeypatch.setenv("FAKE_BSUB_EXIT_BEFORE_READY", "1")
    runner = UrgRunner(
        backend="lsf",
        bsub_cmd=bsub,
        bkill_cmd=bkill,
        queue="urg_rejected",
        startup_timeout_sec=1.0,
        run_timeout_sec=1.0,
    )

    result = runner.run([fake])

    assert result.returncode == 77
    assert result.scheduler["submitted"] is False
    assert result.scheduler["job_id"] is None
    assert result.scheduler["status"] == "submission_rejected"
    assert result.scheduler["exit_status"] == 77


def test_urg_summary_cache_fake_lsf_cold_submits_and_warm_skips_job(
    monkeypatch, tmp_path,
):
    from xcov import urg_cache, urg_runner

    counter = tmp_path / "urg-invocations.txt"
    artifacts = {
        name: (
            SESSION_XML if name == "session.xml" else
            "Total tests in report: 1\n"
            "Data from the following tests was used to generate this report\n"
            "test0\n" if name == "tests.txt" else
            "placeholder\n"
        )
        for name in REQUIRED_ARTIFACTS
    }
    fake = _fake_command(
        tmp_path / "urg-cache",
        "import pathlib, sys\n"
        f"counter = pathlib.Path({str(counter)!r})\n"
        "counter.write_text(counter.read_text() + '1\\n' if counter.exists() else '1\\n')\n"
        "args = sys.argv[1:]\n"
        "report = pathlib.Path(args[args.index('-report') + 1])\n"
        f"artifacts = {artifacts!r}\n"
        "report.mkdir(parents=True, exist_ok=True)\n"
        "for name, content in artifacts.items():\n"
        "    (report / name).write_text(content, encoding='utf-8')\n",
    )
    bsub, bkill = _fake_lsf_commands()
    vdb = tmp_path / "cache.vdb"
    vdb.mkdir()
    (vdb / "content").write_text("v1", encoding="utf-8")
    monkeypatch.setattr(urg_runner, "get_urg_path", lambda: fake)
    monkeypatch.setattr(
        urg_cache,
        "_urg_identity",
        lambda: {"path": fake, "size_bytes": Path(fake).stat().st_size, "mtime_ns": 1},
    )
    monkeypatch.setenv("XVERIF_XCOV_URG_BACKEND", "lsf")
    monkeypatch.setenv("XVERIF_XCOV_URG_QUEUE", "summary_queue")
    monkeypatch.setenv("XVERIF_LSF_BSUB", bsub)
    monkeypatch.setenv("XVERIF_LSF_BKILL", bkill)
    monkeypatch.setenv("FAKE_BSUB_STDOUT_NOISE_BEFORE_READY", "1")
    monkeypatch.setenv("FAKE_BSUB_SCHEDULER_FRAMING", "1")

    _, cold = urg_cache.load_cached_urg_summary(
        str(vdb), cache_root=tmp_path / "cache",
    )
    _, warm = urg_cache.load_cached_urg_summary(
        str(vdb), cache_root=tmp_path / "cache",
    )

    assert cold["hit"] is False
    assert cold["urg_execution"]["backend"] == "lsf"
    assert cold["urg_execution"]["submitted"] is True
    assert cold["urg_execution"]["status"] == "completed"
    assert cold["urg_execution"]["queue"] == "summary_queue"
    assert cold["urg_execution"]["job_id"] == "123"
    assert warm["hit"] is True
    assert warm["urg_execution"] == {
        "backend": "lsf",
        "submitted": False,
        "status": "cache_hit",
        "queue": "summary_queue",
        "resource": None,
        "job_name": None,
        "job_id": None,
        "exit_status": None,
    }
    assert counter.read_text(encoding="utf-8").splitlines() == ["1"]


def test_urg_runner_fake_lsf_pending_timeout_cleans_by_job_id(
    monkeypatch, tmp_path,
):
    from xcov.urg_runner import UrgRunner

    fake = _fake_command(tmp_path / "urg-never-starts", "raise SystemExit(0)")
    bsub, bkill = _fake_lsf_commands()
    monkeypatch.setenv("FAKE_BSUB_STDOUT_NOISE_BEFORE_READY", "1")
    monkeypatch.setenv("FAKE_BSUB_SCHEDULER_FRAMING", "1")
    monkeypatch.setenv("FAKE_BSUB_PENDING_DELAY_MS", "1000")
    runner = UrgRunner(
        backend="lsf",
        bsub_cmd=bsub,
        bkill_cmd=bkill,
        queue="urg_pending",
        startup_timeout_sec=0.5,
        run_timeout_sec=1.0,
    )

    result = runner.run([fake])

    assert result.returncode == 124
    assert result.scheduler["status"] == "startup_timeout"
    assert result.scheduler["job_id"] == "123"
    assert result.scheduler["cleanup"]["target"] == "job_id"
    assert result.scheduler["cleanup"]["bkill_ok"] is True
    assert result.scheduler["cleanup"]["complete"] is True


def test_urg_runner_fake_lsf_run_timeout_cleans_by_job_id(
    monkeypatch, tmp_path,
):
    from xcov.urg_runner import UrgRunner

    fake = _fake_command(
        tmp_path / "urg-slow",
        "import time\ntime.sleep(30)",
    )
    bsub, bkill = _fake_lsf_commands()
    monkeypatch.setenv("FAKE_BSUB_STDOUT_NOISE_BEFORE_READY", "1")
    monkeypatch.setenv("FAKE_BSUB_SCHEDULER_FRAMING", "1")
    runner = UrgRunner(
        backend="lsf",
        bsub_cmd=bsub,
        bkill_cmd=bkill,
        queue="urg_slow",
        startup_timeout_sec=1.0,
        run_timeout_sec=0.05,
    )

    result = runner.run([fake])

    assert result.returncode == 124
    assert result.scheduler["status"] == "run_timeout"
    assert result.scheduler["job_id"] == "123"
    assert result.scheduler["cleanup"]["target"] == "job_id"
    assert result.scheduler["cleanup"]["bkill_ok"] is True
    assert result.scheduler["cleanup"]["complete"] is True


def test_urg_runner_fake_lsf_reports_partial_bkill_cleanup(
    monkeypatch, tmp_path,
):
    from xcov.urg_runner import UrgRunner

    fake = _fake_command(
        tmp_path / "urg-bkill-fails",
        "import time\ntime.sleep(30)",
    )
    bsub, _ = _fake_lsf_commands()
    failing_bkill = shlex.join([
        sys.executable, "-c", "raise SystemExit(9)",
    ])
    monkeypatch.setenv("FAKE_BSUB_STDOUT_NOISE_BEFORE_READY", "1")
    monkeypatch.setenv("FAKE_BSUB_SCHEDULER_FRAMING", "1")
    runner = UrgRunner(
        backend="lsf",
        bsub_cmd=bsub,
        bkill_cmd=failing_bkill,
        queue="urg_cleanup",
        startup_timeout_sec=1.0,
        run_timeout_sec=0.05,
    )

    result = runner.run([fake])

    assert result.returncode == 124
    assert result.scheduler["status"] == "run_timeout"
    assert result.scheduler["cleanup"]["bkill_returncode"] == 9
    assert result.scheduler["cleanup"]["bkill_ok"] is False
    assert result.scheduler["cleanup"]["process"] in {"terminated", "killed"}
    assert result.scheduler["cleanup"]["complete"] is False


def test_content_addressed_urg_cache_serializes_concurrent_miss(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from xcov import urg_cache

    vdb = tmp_path / "parallel.vdb"
    vdb.mkdir()
    (vdb / "content.bin").write_bytes(b"parallel")
    cache = tmp_path / "cache"
    monkeypatch.setattr(
        urg_cache,
        "_urg_identity",
        lambda: {"path": "vcs-bin/urg", "size_bytes": 1, "mtime_ns": 1},
    )
    entered = threading.Event()
    release = threading.Event()

    class BlockingRunner:
        def __init__(self):
            self.call_count = 0
            self.guard = threading.Lock()

        def run(self, argv, timeout=None):
            with self.guard:
                self.call_count += 1
            report = Path(argv[argv.index("-report") + 1])
            for name in REQUIRED_ARTIFACTS:
                content = "placeholder\n"
                if name == "session.xml":
                    content = SESSION_XML
                elif name == "tests.txt":
                    content = (
                        "Total tests in report: 1\n"
                        "Data from the following tests was used to generate this report\n"
                        "test0\n"
                    )
                (report / name).write_text(content, encoding="utf-8")
            entered.set()
            assert release.wait(timeout=5)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

    runner = BlockingRunner()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            urg_cache.load_cached_urg_summary,
            str(vdb), cache_root=cache, runner=runner,
        )
        assert entered.wait(timeout=5)
        second = pool.submit(
            urg_cache.load_cached_urg_summary,
            str(vdb), cache_root=cache, runner=runner,
        )
        release.set()
        first_meta = first.result(timeout=5)[1]
        second_meta = second.result(timeout=5)[1]
    assert runner.call_count == 1
    assert sorted([first_meta["hit"], second_meta["hit"]]) == [False, True]
    assert first_meta["key"] == second_meta["key"]


def test_urg_cache_capacity_is_explicit_and_abandoned_staging_is_cleaned(
    monkeypatch, tmp_path
):
    from xcov import urg_cache

    monkeypatch.setattr(
        urg_cache,
        "_urg_identity",
        lambda: {"path": "vcs-bin/urg", "release": "X-test", "size_bytes": 1, "mtime_ns": 1},
    )
    monkeypatch.setenv("XVERIF_XCOV_CACHE_MAX_ENTRIES", "1")
    cache = tmp_path / "cache"

    class Runner:
        def run(self, argv, timeout=None):
            report = Path(argv[argv.index("-report") + 1])
            for name in REQUIRED_ARTIFACTS:
                content = "placeholder\n"
                if name == "session.xml":
                    content = SESSION_XML
                elif name == "tests.txt":
                    content = (
                        "Total tests in report: 1\n"
                        "Data from the following tests was used to generate this report\n"
                        "test0\n"
                    )
                (report / name).write_text(content, encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

    first_vdb = tmp_path / "first.vdb"
    second_vdb = tmp_path / "second.vdb"
    for index, vdb in enumerate((first_vdb, second_vdb), 1):
        vdb.mkdir()
        (vdb / "content").write_text(str(index), encoding="ascii")
    _, first_meta = urg_cache.load_cached_urg_summary(
        str(first_vdb), cache_root=cache, runner=Runner(),
    )
    stale = cache / "staging" / ("a" * 64 + ".stale")
    stale.mkdir()
    old = __import__("time").time() - urg_cache.ABANDONED_STAGING_SECONDS - 1
    __import__("os").utime(stale, (old, old))
    with pytest.raises(XcovError) as exc_info:
        urg_cache.load_cached_urg_summary(
            str(second_vdb), cache_root=cache, runner=Runner(),
        )
    assert exc_info.value.code == "XCOV_CACHE_CAPACITY_EXCEEDED"
    entries = [path for path in (cache / "entries").iterdir() if path.is_dir()]
    assert [path.name for path in entries] == [first_meta["key"]]
    assert not stale.exists()


def test_streaming_parser_keeps_code_assert_and_functional_types(tmp_path):
    index = parse_urg_summary(_report(tmp_path))

    assert index.tests == ("test_a",)
    assert [row["full_name"] for row in index.scopes] == ["top", "top.u0"]
    assert index.xml_instances == ("top", "top.u0")
    assert index.xml_instance_parent == {"top": None, "top.u0": "top"}
    assert index.xml_instance_children == {
        "top": ("top.u0",), "top.u0": (),
    }
    assert index.expand_xml_instances("top", recursive=False) == ("top",)
    assert index.expand_xml_instances("top", recursive=True) == ("top", "top.u0")
    assert index.scope_metrics["top"]["line"]["covered"] == 8
    assert index.scope_metrics["top.u0"]["line"]["covered"] == 1
    assert index.scope_metrics["top"]["functional"]["pct"] == 75.0
    assert index.scope_metrics["top.u0"]["functional"]["pct"] == 75.0

    assert len(index.functional_rows) == 3
    group = next(row for row in index.functional_rows if row["type"] == "npiCovCovergroup")
    assert group["covergroup_type"] == "dut::cg"
    assert group["variant"] == "top.u0::cg"
    assert group["instance"] == "cg_i"
    assert {row.get("coverpoint") for row in index.functional_rows} == {None, "cp"}
    assert {row.get("cross") for row in index.functional_rows} == {None, "cx"}

    assertion, cover_property = index.assertion_rows
    assert assertion["scope"] == "top.u0"
    assert assertion["covered"] == 1
    assert assertion["coverable"] == 1
    assert assertion["attempts"] == 12
    assert assertion["real_successes"] == 9
    assert cover_property["covered"] == 0
    assert cover_property["missing"] == 1


def test_xml_instance_index_excludes_synthetic_ancestors(tmp_path):
    xml = SESSION_XML.replace(
        '<scope type="instance" name="u0">',
        '<scope type="instance" name="generated.u0">',
    ).replace("top.u0", "top.generated.u0")
    index = parse_urg_summary(_report(tmp_path, xml))

    assert [row["full_name"] for row in index.scopes] == [
        "top", "top.generated", "top.generated.u0",
    ]
    assert index.xml_instances == ("top", "top.generated.u0")
    assert index.xml_instance_parent == {
        "top": None, "top.generated.u0": "top",
    }
    assert index.expand_xml_instances("top", recursive=True) == (
        "top", "top.generated.u0",
    )
    with pytest.raises(XcovError) as info:
        index.expand_xml_instances("top.generated", recursive=True)
    assert info.value.code == "SCOPE_NOT_FOUND"


def test_zero_denominator_exclusion_ratio_keeps_null_percentage(tmp_path):
    xml = SESSION_XML.replace(
        '<metric name="Line" value="1/2" excl="0" />',
        '<metric name="Line" value="0/0" excl="2" />',
    ).replace(
        '<metric name="Group" value="3/4" excl="0" />',
        '<metric name="Group" value="0/0" excl="4" />',
    ).replace('<attr name="Score" value="75%" />', "")
    index = parse_urg_summary(_report(tmp_path, xml))

    assert index.scope_metrics["top.u0"]["line"] == {
        "covered": 0, "coverable": 0, "missing": 0,
        "excluded": 2, "pct": None,
    }
    group = next(
        row for row in index.functional_rows
        if row["type"] == "npiCovCovergroup"
    )
    assert group["coverage_pct"] is None
    assert group["coverable"] == 0
    assert index.scope_metrics["top.u0"]["functional"]["pct"] is None


def test_scope_aggregation_uses_parent_subtree_once_and_score_average(tmp_path):
    index = parse_urg_summary(_report(tmp_path))
    scopes = {row["full_name"]: row for row in index.scopes}
    coverage = _coverage_from_urg(
        index.scope_metrics,
        scopes,
        ["line", "assert", "functional"],
    )

    assert coverage["top"]["metrics"][0]["covered"] == 8
    assert coverage["top"]["coverage_pct"] == 68.3333
    assert "covered" not in coverage["top"]
    assert coverage["top.u0"]["coverage_pct"] == 75.0

    line_only = _code_coverage_from_urg(index.scope_metrics, "scope", ["line"])
    top = next(row for row in line_only if row["scope"] == "top")
    assert top["covered"] == 8
    assert top["coverable"] == 10

    metrics = _metrics_from_urg(index.scope_metrics, ["line"])
    assert metrics == [{
        "metric": "line",
        "covered": 8,
        "coverable": 10,
        "missing": 2,
        "coverage_pct": 80.0,
    }]


def test_parser_rejects_unknown_scope_type(tmp_path):
    xml = SESSION_XML.replace(
        '<scope type="assert" name="Statistics" />',
        '<scope type="Future Coverage" name="new" />',
    )
    with pytest.raises(XcovError) as raised:
        parse_urg_summary(_report(tmp_path, xml))
    assert raised.value.code == "URG_XML_UNSUPPORTED_SCOPE_TYPE"


def test_parser_rejects_missing_required_artifact(tmp_path):
    report = _report(tmp_path)
    (report / "groups.txt").unlink()
    with pytest.raises(XcovError) as raised:
        parse_urg_summary(report)
    assert raised.value.code == "URG_SUMMARY_INCOMPLETE"
