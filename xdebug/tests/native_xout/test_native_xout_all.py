from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from runner.raw_cli import RawCliResult, RawCliRunner

from .cases import (
    CASES,
    ERROR_CASES,
    EXTERNAL_PROTECTION_CASES,
    FIRST_SECTION_REQUIRED,
    SUMMARY_OMITTED_ACTIONS,
    NativeXoutCase,
)
from .report import verify_report, write_report


RESOURCE_PATHS = {
    "W": ("xdebug.ai_complex_wave", "out/waves.fsdb", "out/simv.daidir"),
    "C": ("xdebug.active_semantics", "out/waves.fsdb", "out/simv.daidir"),
    "X": ("xdebug.trace_x_xprop", "out/waves.fsdb", "out/simv.daidir"),
    "P": ("xdebug.apb_vip", "out/regression/test/apb_vip_test/waves.fsdb", "out/regression/build/simv.daidir"),
    "A": ("xdebug.axi_vip", "out/regression/test/axi_multi_id_test/waves.fsdb", "out/regression/build/simv.daidir"),
    "S": ("xdebug.stream_v1", "out/waves.fsdb", "out/simv.daidir"),
    "E": ("xdebug.xif_event", "out/waves/xif_event_multi_if_test.fsdb", "out/simv.daidir"),
}


def _first_xout_section(text: str) -> str:
    lines = text.splitlines()
    section_indexes = [
        index for index, line in enumerate(lines)
        if index > 0 and line and not line.startswith(" ") and line.endswith(":")
    ]
    if not section_indexes:
        return "\n".join(lines[1:])
    begin = section_indexes[0]
    end = section_indexes[1] if len(section_indexes) > 1 else len(lines)
    return "\n".join(lines[begin:end])


class MatrixRuntime:
    def __init__(self, runner: RawCliRunner, repo_root: Path, tmp_path: Path,
                 xverif_fixture: Any) -> None:
        self.runner = runner
        self.repo_root = repo_root
        self.tmp_path = tmp_path
        self.xverif_fixture = xverif_fixture
        self.resources: dict[str, tuple[Path, Path]] = {}
        self.sessions: dict[str, str] = {}
        self.setup_done: set[tuple[str, str]] = set()
        self._prepare_local_inputs()

    def _prepare_local_inputs(self) -> None:
        self.rc_config = self.tmp_path / "wave_view.json"
        self.rc_config.write_text(json.dumps({
            "file_time_scale": "1ns",
            "groups": [{"name": "clock", "signals": ["ai_complex_top.clk"]}],
        }), encoding="utf-8")
        self.event_config = self.tmp_path / "event_rdy_leaf.json"
        self.event_config.write_text(json.dumps({
            "clock": "xif_event_top.clk",
            "reset": {
                "signal": "xif_event_top.rst_n",
                "polarity": "active_low",
            },
            "edge": "posedge",
            "signals": {
                "vld": "xif_event_top.if_rdy.vld",
                "rdy": "xif_event_top.if_rdy.rdy",
            },
        }), encoding="utf-8")

    def resource(self, code: str) -> tuple[Path, Path]:
        if code not in self.resources:
            fixture, fsdb_rel, daidir_rel = RESOURCE_PATHS[code]
            root = self.xverif_fixture(fixture)
            fsdb, daidir = root / fsdb_rel, root / daidir_rel
            assert fsdb.is_file() and fsdb.stat().st_size > 0
            assert daidir.is_dir()
            self.resources[code] = (fsdb, daidir)
        return self.resources[code]

    def session(self, code: str) -> str:
        if code not in self.sessions:
            fsdb, daidir = self.resource(code)
            session_id = "native_xout_" + code.lower()
            target: dict[str, str] = {"fsdb": str(fsdb)}
            if code in {"C", "X"}:
                target["daidir"] = str(daidir)
            self.success({
                "api_version": "xdebug.v1", "action": "session.open",
                "target": target, "args": {"name": session_id},
            }, role="setup")
            self.sessions[code] = session_id
        return self.sessions[code]

    def success(self, request: dict[str, Any], *, role: str) -> RawCliResult:
        result = self.runner.run(request, role=role, timeout_sec=240)
        assert not result.timed_out
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        assert result.stdout.startswith(
            ("@xdebug.%s.v1\n" % request["action"]).encode("utf-8")
        ), result.stdout[:200]
        return result

    def replacements(self) -> dict[str, Any]:
        apb_prefix = "apb_vip_fixture_top.apb_if"
        apb = {
            "paddr": apb_prefix + ".paddr", "pwdata": apb_prefix + ".pwdata",
            "prdata": apb_prefix + ".prdata[0]", "pwrite": apb_prefix + ".pwrite",
            "penable": apb_prefix + ".penable", "psel": apb_prefix + ".psel[0]",
            "pready": apb_prefix + ".pready[0]", "pslverr": apb_prefix + ".pslverr[0]",
            "clock": "apb_vip_fixture_top.clk",
            "reset": {"signal": "apb_vip_fixture_top.rst_n", "polarity": "active_low"},
            "edge": "posedge",
        }
        prefix = "axi_vip_fixture_top.axi_vip_if.master_if[0]"
        axi = {key: prefix + "." + key for key in (
            "awaddr", "awid", "awlen", "awsize", "awburst", "awvalid", "awready",
            "wdata", "wstrb", "wlast", "wvalid", "wready", "bid", "bresp",
            "bvalid", "bready", "araddr", "arid", "arlen", "arsize", "arburst",
            "arvalid", "arready", "rid", "rdata", "rresp", "rlast", "rvalid", "rready",
        )}
        axi.update({"clock": "axi_vip_fixture_top.clk",
                    "reset": {"signal": "axi_vip_fixture_top.rst_n", "polarity": "active_low"},
                    "edge": "posedge"})
        stream_config_path = (
            self.repo_root /
            "xdebug/testdata/waveform/stream_v1/config/streams.json"
        )
        primary_stream = json.loads(
            stream_config_path.read_text(encoding="utf-8")
        )["streams"][0]
        primary_stream["name"] = "native_primary_stream"
        return {
            "$APB_CONFIG": apb,
            "$AXI_CONFIG": axi,
            "$TMP": str(self.tmp_path),
            "$EVENT_CONFIG": str(self.event_config),
            "$STREAM_CONFIG": str(self.repo_root / "xdebug/testdata/waveform/stream_v1/config/streams.json"),
            "$STREAM_PRIMARY": [primary_stream],
            "$RC_CONFIG": str(self.rc_config),
        }

    def expand(self, value: Any) -> Any:
        replacements = self.replacements()
        if isinstance(value, dict):
            return {key: self.expand(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.expand(item) for item in value]
        if isinstance(value, str):
            if value in replacements:
                return replacements[value]
            return value.replace("$TMP", replacements["$TMP"])
        return value

    def ensure(self, case: NativeXoutCase) -> None:
        code, prerequisite = case.resource, case.prerequisite
        if code is None or prerequisite in {None, "open_action", "disposable_session"}:
            return
        instance = prerequisite
        if prerequisite in {"list", "cursor"}:
            instance += ":" + str(
                case.args.get(
                    "name",
                    "mark_for_list" if prerequisite == "cursor" else "basic",
                )
            )
        key = (code, instance)
        if key in self.setup_done:
            return
        target = {"session_id": self.session(code)}
        if prerequisite == "apb":
            args = {"name": "apb0", "config": self.replacements()["$APB_CONFIG"]}
            action = "apb.config.load"
        elif prerequisite == "axi":
            args = {"name": "axi0", "config": self.replacements()["$AXI_CONFIG"]}
            action = "axi.config.load"
        elif prerequisite == "stream":
            args = {"config_path": self.replacements()["$STREAM_CONFIG"], "mode": "replace"}
            action = "stream.config.load"
        elif prerequisite == "event":
            args = {"name": "rdy", "config_path": self.replacements()["$EVENT_CONFIG"]}
            action = "event.config.load"
        elif prerequisite == "list":
            args = {"name": str(case.args["name"]),
                    "signals": ["ai_complex_top.sig_a", "ai_complex_top.sig_b"]}
            action = "list.create"
        elif prerequisite == "cursor":
            args = {"name": str(case.args.get("name", "mark_for_list")),
                    "time": "75ns"}
            action = "waveform.cursor.set"
        elif prerequisite == "rc":
            self.session(code)
            self.setup_done.add(key)
            return
        else:
            raise AssertionError("unknown prerequisite: " + prerequisite)
        self.success({"api_version": "xdebug.v1", "action": action,
                      "target": target, "args": args}, role="setup")
        self.setup_done.add(key)

    def primary_request(self, case: NativeXoutCase) -> dict[str, Any]:
        args = self.expand(case.args)
        if case.action == "session.open":
            fsdb, _ = self.resource(case.resource or "W")
            self.sessions["PRIMARY_OPEN"] = str(args["name"])
            return {"api_version": "xdebug.v1", "action": case.action,
                    "target": {"fsdb": str(fsdb)}, "args": args}
        if case.prerequisite == "disposable_session":
            fsdb, _ = self.resource(case.resource or "W")
            sid = "native_xout_disposable_" + case.action.rsplit(".", 1)[-1]
            self.success({"api_version": "xdebug.v1", "action": "session.open",
                          "target": {"fsdb": str(fsdb)}, "args": {"name": sid}}, role="setup")
            return {"api_version": "xdebug.v1", "action": case.action,
                    "target": {"session_id": sid}, "args": args}
        request = {"api_version": "xdebug.v1", "action": case.action, "args": args}
        if case.resource is not None:
            request["target"] = {"session_id": self.session(case.resource)}
        return request

    def close(self) -> None:
        for code, session_id in list(self.sessions.items()):
            self.runner.run({"api_version": "xdebug.v1", "action": "session.close",
                             "target": {"session_id": session_id}, "args": {}},
                            role="teardown", timeout_sec=120)


def _request_schema_exposes_value_format(repo_root: Path, action: str) -> bool:
    schema = json.loads((
        repo_root / "xdebug/schemas/v1/actions" /
        f"{action}.request.schema.json"
    ).read_text(encoding="utf-8"))

    def contains(node: Any) -> bool:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict) and "value_format" in properties:
                return True
            return any(contains(value) for value in node.values())
        if isinstance(node, list):
            return any(contains(value) for value in node)
        return False

    return contains(schema)


def _format_variant_request(request: dict[str, Any], value_format: str) -> dict[str, Any]:
    variant = json.loads(json.dumps(request))
    variant.setdefault("args", {})["value_format"] = value_format
    output = variant["args"].get("output")
    if isinstance(output, dict) and isinstance(output.get("path"), str):
        output["path"] += "-" + value_format
    return variant


@pytest.mark.regression
@pytest.mark.slow
def test_all_runtime_actions_emit_native_xout(
    xdebug_bin: Path,
    repo_root: Path,
    isolated_home: Path,
    tmp_path: Path,
    xverif_fixture: Any,
) -> None:
    runner = RawCliRunner(
        xdebug_bin, cwd=repo_root,
        base_env={"HOME": str(isolated_home), "XVERIF_HOME": str(repo_root)},
        phase=os.environ.get("XDEBUG_XOUT_PHASE", ""),
    )
    report_path = tmp_path / "native-xout-final-report.md"
    staged_report = report_path.with_suffix(report_path.suffix + ".tmp")
    staged_report.unlink(missing_ok=True)
    runtime = MatrixRuntime(runner, repo_root, tmp_path, xverif_fixture)
    semantic_failures: list[str] = []
    matrix_complete = False
    try:
        assert len(CASES) == 73
        assert len({item.action for item in CASES}) == 73
        assert set(FIRST_SECTION_REQUIRED) == {item.action for item in CASES}
        for case in CASES:
            runtime.ensure(case)
            request = runtime.primary_request(case)
            result = runner.run(request, role="primary", timeout_sec=240)
            assert not result.timed_out
            if result.returncode != 0:
                semantic_failures.append(
                    f"{case.action}: runtime returncode={result.returncode}"
                )
                continue
            assert result.stdout.startswith(
                ("@xdebug.%s.v1\n" % case.action).encode("utf-8")
            ), result.stdout[:200]
            text = result.stdout_text()
            first_section = _first_xout_section(text)
            for required in FIRST_SECTION_REQUIRED[case.action]:
                if required not in first_section:
                    semantic_failures.append(
                        f"{case.action}: first section missing {required!r}"
                    )
            if case.action in SUMMARY_OMITTED_ACTIONS and first_section.startswith("summary:"):
                semantic_failures.append(
                    f"{case.action}: redundant summary section was not omitted"
                )
            for redundant in (
                "output_written", "all_passed", "termination_detail",
                "checked_value_count", "full_scan_count",
            ):
                if redundant in first_section:
                    semantic_failures.append(
                        f"{case.action}: first section retained redundant field "
                        f"{redundant!r}"
                    )
            for required in case.required_text:
                if required not in text:
                    semantic_failures.append(
                        f"{case.action}: missing required text {required!r}"
                    )
            for forbidden in case.forbidden_text:
                if forbidden in text:
                    semantic_failures.append(
                        f"{case.action}: retained forbidden text {forbidden!r}"
                    )
            if case.action == "actions":
                for catalog_action in {item.action for item in CASES}:
                    if text.count("\n  " + catalog_action + "\n") != 1:
                        semantic_failures.append(
                            f"actions: catalog entry {catalog_action!r} is not unique"
                        )
            if runner.phase == "final":
                for redundant in (
                    " known=", " has_x=", " has_z=", " width=",
                    " width_unknown",
                ):
                    if redundant in text:
                        semantic_failures.append(
                            f"{case.action}: retained redundant value token "
                            f"{redundant!r}"
                        )
                if re.search(r"\bbits=[01_]+\b", text):
                    semantic_failures.append(
                        f"{case.action}: retained redundant known-value bits"
                    )

        for protection_id in ("012", "013"):
            protection = EXTERNAL_PROTECTION_CASES[protection_id]
            request = {
                "api_version": "xdebug.v1",
                "action": protection["action"],
                "target": {
                    "session_id": runtime.session(protection["resource"])
                },
                "args": protection["args"],
            }
            result = runner.run(
                request,
                role="protection:" + protection_id,
                timeout_sec=240,
            )
            if result.timed_out or result.returncode != 0:
                semantic_failures.append(
                    f"{protection['action']}: protection {protection_id} failed"
                )
                continue
            text = result.stdout_text()
            for required in protection["required_text"]:
                if required not in text:
                    semantic_failures.append(
                        f"{protection['action']}: protection {protection_id} "
                        f"missing required text {required!r}"
                    )
            for forbidden in protection["forbidden_text"]:
                if forbidden in text:
                    semantic_failures.append(
                        f"{protection['action']}: protection {protection_id} "
                        f"retained forbidden text {forbidden!r}"
                    )

        for name, resource, template in ERROR_CASES:
            request = runtime.expand(template)
            if resource is not None:
                request["target"] = {
                    "session_id": runtime.session(resource)
                }
            result = runner.run(request, role="error:" + name, timeout_sec=120)
            assert not result.timed_out
            assert result.returncode != 0
            assert result.stdout
            assert result.stdout.startswith(b"@xdebug.error.v1\n")

        if runner.phase == "final":
            for case in CASES:
                if not _request_schema_exposes_value_format(
                    repo_root, case.action
                ):
                    continue
                runtime.ensure(case)
                base_request = runtime.primary_request(case)
                for value_format in ("bin", "dec"):
                    request = _format_variant_request(
                        base_request, value_format
                    )
                    result = runner.run(
                        request,
                        role="value-format:" + value_format,
                        timeout_sec=240,
                    )
                    if result.timed_out or result.returncode != 0:
                        semantic_failures.append(
                            f"{case.action}: value_format={value_format} failed"
                        )
                        continue
                    text = result.stdout_text()
                    for redundant in (
                        " known=false", " known=true", " width=",
                        " has_x=", " has_z=", " width_unknown",
                    ):
                        if redundant in text:
                            semantic_failures.append(
                                f"{case.action}: redundant value token "
                                f"{redundant!r} for value_format={value_format}"
                            )

            x_session = runtime.session("X")
            for value_format, expected, forbidden in (
                ("hex", "8'hx bits=x01x_x10x", ""),
                ("bin", "8'bx01xx10x", "bits="),
                (
                    "dec",
                    "8'bx01xx10x requested=dec reason=X/Z",
                    "bits=",
                ),
            ):
                request = {
                    "api_version": "xdebug.v1",
                    "action": "value.at",
                    "target": {"session_id": x_session},
                    "args": {
                        "signal": "trace_x_xprop_tb.observed",
                        "time": "18ns",
                        "value_format": value_format,
                    },
                }
                result = runner.run(
                    request, role="xz:" + value_format, timeout_sec=240
                )
                if result.returncode != 0:
                    semantic_failures.append(
                        f"value.at X/Z value_format={value_format} failed"
                    )
                    continue
                text = result.stdout_text()
                if expected not in text:
                    semantic_failures.append(
                        f"value.at X/Z value_format={value_format} missing "
                        f"{expected!r}"
                    )
                if forbidden and forbidden in text:
                    semantic_failures.append(
                        f"value.at X/Z value_format={value_format} retained "
                        f"{forbidden!r}"
                    )
        matrix_complete = True
    finally:
        runtime.close()
        if matrix_complete:
            write_report(
                staged_report, runner.history,
                semantic_failures=semantic_failures,
            )
            expected = {runner.phase: 73}
            verify_report(staged_report, expected_primary_by_phase=expected)
            os.replace(staged_report, report_path)
    if runner.phase == "final":
        assert not semantic_failures, "\n".join(semantic_failures)
