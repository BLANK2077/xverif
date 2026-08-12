#!/usr/bin/env python3
import argparse
import csv
import json
import os
import re
import selectors
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import jsonschema


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REPO_ROOT = os.path.abspath(os.path.join(ROOT, ".."))
TESTS_ROOT = os.path.join(ROOT, "tests")
if TESTS_ROOT not in sys.path:
    sys.path.insert(0, TESTS_ROOT)

from runner import StdioLoopRunner

NONAXI_DIR = os.path.join(ROOT, "testdata", "waveform", "ai_complex_wave")
NONAXI_FSDB = os.path.join(NONAXI_DIR, "out", "waves.fsdb")
AXI_DIR = os.environ.get(
    "XDEBUG_AXI_FIXTURE_DIR",
    os.path.join(ROOT, "testdata", "waveform", "axi_vip_real"),
)
AXI_FSDB = os.path.join(
    AXI_DIR,
    "out",
    "regression",
    "test",
    "axi_multi_id_test",
    "waves.fsdb",
)
AXI_SIM_LOG = os.path.join(
    AXI_DIR,
    "out",
    "regression",
    "test",
    "axi_multi_id_test",
    "sim.log",
)
AXI_HANDSHAKE_ORACLE = os.path.join(
    AXI_DIR,
    "out",
    "regression",
    "test",
    "axi_multi_id_test",
    "axi_handshake.jsonl",
)
DEFAULT_QUERY_TIMEOUT_MS = int(os.environ.get("XDEBUG_QUERY_TIMEOUT_MS", "120000"))
PROGRESS_HEARTBEAT_SEC = int(os.environ.get("XDEBUG_PROGRESS_HEARTBEAT_SEC", "30"))


def log_progress(message):
    print("[xdebug-progress] {}".format(message), flush=True)


def should_print_progress_line(line):
    text = line.strip()
    if not text:
        return False
    if "AXI_EXPECTED_TXN_JSON" in text:
        return False
    important_fragments = [
        "make ",
        "vlogan ",
        "vcs ",
        "simv ",
        "Chronologic VCS",
        "Version V-",
        "Top Level Modules:",
        "CPU time:",
        "Starting test",
        "Starting master",
        "TEST PASSED",
        "Master WRITE transactions",
        "Master READ transactions",
        "UVM_ERROR :",
        "UVM_FATAL :",
        "Error-",
        "Fatal",
        "FAIL:",
    ]
    return any(fragment in text for fragment in important_fragments)


def run_cmd(cmd, cwd=None, env=None, timeout=120, input_text=None, progress_label=None):
    start = time.time()
    if progress_label:
        log_progress("{}: start: {}".format(progress_label, " ".join(cmd)))
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        selector = selectors.DefaultSelector()
        if proc.stdout is not None:
            selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
        if proc.stderr is not None:
            selector.register(proc.stderr, selectors.EVENT_READ, "stderr")
        stdout_chunks = []
        stderr_chunks = []
        last_heartbeat = start
        def emit_heartbeat():
            nonlocal last_heartbeat
            heartbeat_now = time.time()
            if heartbeat_now - last_heartbeat >= PROGRESS_HEARTBEAT_SEC:
                log_progress("{}: still running ({}s)".format(progress_label, int(heartbeat_now - start)))
                last_heartbeat = heartbeat_now

        while selector.get_map():
            now = time.time()
            if timeout is not None and now - start > timeout:
                proc.kill()
                raise subprocess.TimeoutExpired(cmd, timeout)
            events = selector.select(timeout=1.0)
            if not events:
                emit_heartbeat()
                if proc.poll() is not None:
                    for key in list(selector.get_map().values()):
                        line = key.fileobj.readline()
                        while line:
                            if key.data == "stdout":
                                stdout_chunks.append(line)
                            else:
                                stderr_chunks.append(line)
                            if should_print_progress_line(line):
                                print(line, end="", flush=True)
                            line = key.fileobj.readline()
                        selector.unregister(key.fileobj)
                continue
            for key, _ in events:
                line = key.fileobj.readline()
                if line:
                    if key.data == "stdout":
                        stdout_chunks.append(line)
                    else:
                        stderr_chunks.append(line)
                    if should_print_progress_line(line):
                        print(line, end="", flush=True)
                else:
                    selector.unregister(key.fileobj)
            emit_heartbeat()
        rc = proc.wait()
        elapsed_ms = int((time.time() - start) * 1000)
        log_progress("{}: done rc={} elapsed_ms={}".format(progress_label, rc, elapsed_ms))
        return rc, "".join(stdout_chunks), "".join(stderr_chunks), elapsed_ms

    proc = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        timeout=timeout,
        input=input_text,
    )
    elapsed_ms = int((time.time() - start) * 1000)
    return proc.returncode, proc.stdout, proc.stderr, elapsed_ms


def require(cond, msg):
    if not cond:
        raise AssertionError(msg)


def duration_fs(value):
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(fs|ps|ns|us|ms|s)", value)
    require(match is not None, "invalid duration string: {}".format(value))
    scales = {"fs": 1, "ps": 10**3, "ns": 10**6, "us": 10**9,
              "ms": 10**12, "s": 10**15}
    return float(match.group(1)) * scales[match.group(2)]


def require_clock_summary(resp, edge, sample_point=None,
                          expected_clock="ai_complex_top.clk"):
    summary = resp["summary"]
    require(summary["sampling_mode"] == "clock_edge", "missing clock_edge sampling mode")
    require(summary["clock"] == expected_clock, "unexpected summary clock")
    require(summary["edge"] == edge, "unexpected summary edge: {}".format(summary["edge"]))
    effective_sample_point = sample_point
    if effective_sample_point is None and edge in ("posedge", "dual"):
        effective_sample_point = "before"
    if effective_sample_point is None:
        require("sample_point" not in summary,
                "negedge summary should not expose sample_point")
    else:
        require(summary["sample_point"] == effective_sample_point,
                "unexpected summary sample_point")
    require(summary["sample_time_semantics"] == "time is sample_time",
            "missing sample time semantics: {}".format(
                json.dumps(summary, sort_keys=True)))


def require_clock_sampling_contract(resp, edge, sample_point=None,
                                    expected_clock="ai_complex_top.clk"):
    summary = resp["summary"]
    require(summary["sampling_mode"] == "clock_edge", "missing clock_edge sampling mode")
    require(summary["clock"] == expected_clock, "unexpected summary clock")
    require("edge" not in summary and "sample_point" not in summary,
            "sampling selection facts must have one owner in data.sampling")
    require(summary["sample_time_semantics"] == "time is sample_time",
            "missing sample time semantics: {}".format(json.dumps(summary, sort_keys=True)))
    sampling = resp["data"]["sampling"]
    require(sampling["requested"] == {
                "edge": edge,
                "sample_point": sample_point,
            },
            "unexpected requested sampling: {}".format(
                json.dumps(sampling["requested"], sort_keys=True)))
    effective_sample_point = None if edge == "negedge" else (sample_point or "before")
    require(sampling["effective"] == {
                "edge": edge,
                "sample_point": effective_sample_point,
            },
            "unexpected effective sampling: {}".format(
                json.dumps(sampling["effective"], sort_keys=True)))
    ignored = edge == "negedge" and sample_point is not None
    require(sampling["sample_point_applied"] is (edge != "negedge"),
            "sample_point_applied does not match effective edge semantics")
    require(sampling["sample_point_ignored_for_negedge"] is ignored,
            "unexpected negedge sample-point disposition")
    if ignored:
        require(isinstance(sampling.get("sample_point_not_applied_reason"), str) and
                sampling["sample_point_not_applied_reason"],
                "ignored negedge sample_point must publish a reason")
    else:
        require("sample_point_not_applied_reason" not in sampling,
                "non-ignored sampling must not publish an ignored reason")


def require_clock_context(resp, edge, sample_point=None,
                          expected_clock="ai_complex_top.clk"):
    data = resp["data"]
    context = (
        data["samples"][0]["clock_context"]
        if "samples" in data else data["clock_context"]
    )
    require(context["clock"] == expected_clock, "unexpected point-sampling clock")
    require("edge" not in context,
            "clock_context must not duplicate requested_sampling.edge")
    require(context["requested_sampling"] == {
                "edge": edge,
                "sample_point": sample_point,
            },
            "unexpected requested point sampling")
    effective_sample_point = None if edge == "negedge" else (sample_point or "before")
    require(context["effective_sampling"] == {
                "edge": edge,
                "sample_point": effective_sample_point,
            },
            "unexpected effective point sampling")
    ignored = edge == "negedge" and sample_point is not None
    require(context["sample_point_applied"] is (edge != "negedge"),
            "point sample_point_applied does not match effective edge semantics")
    require(context["sample_point_ignored_for_negedge"] is ignored,
            "unexpected point negedge sample-point disposition")
    if ignored:
        require(isinstance(context.get("sample_point_not_applied_reason"), str) and
                context["sample_point_not_applied_reason"],
                "ignored point sample_point must publish a reason")
    else:
        require("sample_point_not_applied_reason" not in context,
                "non-ignored point sampling must not publish an ignored reason")
    require(context["clock_edge_kind"] in (None, "posedge", "negedge"),
            "clock_edge_kind must describe the actual edge at requested_time")
    if context["bracket_complete"]:
        require(context["previous_sample_time"] is not None and
                context["next_sample_time"] is not None,
                "complete bracket must publish both neighboring sample times")
    else:
        require(context["previous_sample_time"] is None or
                context["next_sample_time"] is None,
                "incomplete bracket must identify a missing boundary")


def time_ns(value):
    text = str(value).strip().lower()
    require(text.endswith("ns"), "expected ns time, got {}".format(value))
    return float(text[:-2])


def normalize_sv_hex(value):
    text = str(value).strip().lower().replace("_", "")
    if text.startswith("'h"):
        text = text[2:]
    elif text.startswith("0x"):
        text = text[2:]
    if text == "":
        text = "0"
    text = text.lstrip("0") or "0"
    return "'h" + text


def parse_axi_expected_log(path):
    records = {"WR": [], "RD": []}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            marker = "AXI_EXPECTED_TXN_JSON "
            if marker not in line:
                continue
            payload = line.split(marker, 1)[1].strip()
            rec = json.loads(payload)
            rec["dir"] = rec["dir"].upper()
            records[rec["dir"]].append(rec)
    return records


def require_axi_delay_matrix(path, expected_writes, min_random_delay, max_random_delay):
    from collections import Counter

    write_profiles = []
    response_profiles = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "AXI_DELAY_PROFILE_JSON " in line:
                write_profiles.append(json.loads(line.split("AXI_DELAY_PROFILE_JSON ", 1)[1]))
            elif "AXI_RESPONSE_DELAY_JSON " in line:
                response_profiles.append(json.loads(line.split("AXI_RESPONSE_DELAY_JSON ", 1)[1]))
    expected_per_profile = expected_writes // 4
    require(expected_writes % 4 == 0 and
            Counter(row["profile"] for row in write_profiles) ==
            Counter({0: expected_per_profile, 1: expected_per_profile,
                     2: expected_per_profile, 3: expected_per_profile}),
            "write delay profile matrix count mismatch")
    response_counts = Counter(row["profile"] for row in response_profiles)
    require(set(response_counts) == {0, 1, 2, 3} and
            min(response_counts.values()) > 0 and
            max(response_counts.values()) - min(response_counts.values()) <= 1,
            "response delay profile matrix is incomplete or unbalanced: {}".format(
                dict(response_counts)))
    for row in write_profiles:
        profile = row["profile"]
        if profile == 0:
            require((row["data_before_addr"], row["addr_valid_delay"], row["first_wvalid_delay"]) == (0, 0, 4),
                    "AW-before-W fixed delay profile drifted")
        elif profile == 1:
            require((row["data_before_addr"], row["addr_valid_delay"], row["first_wvalid_delay"]) == (1, 4, 0),
                    "W-before-AW fixed delay profile drifted")
        elif profile == 2:
            require((row["data_before_addr"], row["addr_valid_delay"], row["first_wvalid_delay"]) == (0, 0, 0),
                    "same-cycle fixed delay profile drifted")
        else:
            require(0 <= row["addr_valid_delay"] <= 7 and
                    0 <= row["first_wvalid_delay"] <= 7,
                    "fixed-seed random write delay escaped configured range")
    fixed_values = {0: 0, 1: 4, 2: 17}
    for row in response_profiles:
        profile = row["profile"]
        selected = row["bvalid_delay"] if row["channel"] == "B" else row["rvalid_delay"]
        if profile in fixed_values:
            require(selected == fixed_values[profile],
                    "fixed response delay profile drifted")
        else:
            require(min_random_delay <= selected <= max_random_delay,
                    "fixed-seed random response delay escaped configured range")


def parse_axi_handshake_oracle(path):
    """Reconstruct AXI writes from raw pin handshakes, independently of xdebug."""
    pending_writes = []
    completed_w_bursts = []
    current_w_burst = None
    completed = []
    channel_counts = {name: 0 for name in ("AW", "W", "B", "AR", "R")}
    records = {name: [] for name in channel_counts}
    w_beat_index = 0
    r_beat_index_by_id = {}

    def drain_w_bursts():
        while completed_w_bursts:
            target = next((txn for txn in pending_writes if "w_first_time" not in txn), None)
            if target is None:
                return
            burst = completed_w_bursts.pop(0)
            target.update(burst)

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            payload = line.strip()
            if not payload:
                continue
            rec = json.loads(payload)
            channel = rec["channel"]
            channel_counts[channel] += 1
            if channel == "W":
                w_beat_index += 1
                rec["beat_index"] = w_beat_index
                if int(rec["last"]):
                    w_beat_index = 0
            elif channel == "R":
                rid = int(rec["id"])
                r_beat_index_by_id[rid] = r_beat_index_by_id.get(rid, 0) + 1
                rec["beat_index"] = r_beat_index_by_id[rid]
                if int(rec["last"]):
                    del r_beat_index_by_id[rid]
            records[channel].append(rec)
            if channel == "AW":
                pending_writes.append({
                    "id": int(rec["id"]),
                    "addr": int(rec["addr"]),
                    "expected_beat_count": int(rec["len"]) + 1,
                    "aw_time": int(rec["time_ps"]),
                })
                drain_w_bursts()
            elif channel == "W":
                if current_w_burst is None:
                    current_w_burst = {
                        "w_first_time": int(rec["time_ps"]),
                        "beat_count": 0,
                    }
                current_w_burst["beat_count"] += 1
                if int(rec["last"]):
                    current_w_burst["w_last_time"] = int(rec["time_ps"])
                    completed_w_bursts.append(current_w_burst)
                    current_w_burst = None
                    drain_w_bursts()
            elif channel == "B":
                target = next((txn for txn in pending_writes
                               if txn["id"] == int(rec["id"]) and
                               "w_last_time" in txn), None)
                require(target is not None,
                        "raw handshake oracle saw B without completed AW/W for id={}".format(rec["id"]))
                target["b_time"] = int(rec["time_ps"])
                if target["w_first_time"] < target["aw_time"]:
                    target["phase_order"] = "w_before_aw"
                elif target["w_first_time"] > target["aw_time"]:
                    target["phase_order"] = "aw_before_w"
                else:
                    target["phase_order"] = "same_cycle"
                require(target["b_time"] >= target["aw_time"] and
                        target["b_time"] >= target["w_last_time"],
                        "raw handshake oracle found illegal early B response")
                completed.append(target)
                pending_writes.remove(target)

    require(current_w_burst is None and not completed_w_bursts and not pending_writes,
            "raw handshake oracle ended with incomplete writes: current={} buffered={} pending={}".format(
                current_w_burst is not None, len(completed_w_bursts), len(pending_writes)))
    require(w_beat_index == 0 and not r_beat_index_by_id,
            "raw handshake oracle ended with incomplete W/R beat indexing")
    return {"writes": completed, "channel_counts": channel_counts, "records": records}


def require_axi_handshake_queries(r, oracle):
    def same_time(actual, expected_ps, label):
        require(duration_fs(actual) == int(expected_ps) * 1000,
                "{} mismatch: expected {}ps, got {}".format(label, expected_ps, actual))

    def query_record(channel, rec, include_data=False):
        response = r.query(
            "axi.query",
            args={
                "name": "axi0",
                "query": {
                    "channel": channel.lower(),
                    "handshake_time": "{}ps".format(rec["time_ps"]),
                },
                "output": {"include_data": include_data},
            },
        )
        require(response["summary"]["query_mode"] == "handshake" and
                response["summary"]["found"],
                "AXI {} exact handshake query did not match".format(channel))
        match = response["data"]["match"]
        require(match["channel"] == channel.lower(), "AXI query returned wrong channel")
        same_time(match["handshake_time"], rec["time_ps"], "{} match time".format(channel))
        if channel in ("W", "R"):
            require(match["beat_index"] == rec["beat_index"],
                    "AXI {} query returned wrong beat index".format(channel))
        return response["data"]["transaction"]

    records = oracle["records"]
    aw = records["AW"][0]
    aw_txn = query_record("AW", aw)
    same_time(aw_txn["address"]["handshake_time"], aw["time_ps"], "AW handshake")
    same_time(aw_txn["address"]["valid_begin_time"], aw["valid_begin_time_ps"], "AW valid begin")

    ar = records["AR"][0]
    ar_txn = query_record("AR", ar)
    same_time(ar_txn["address"]["handshake_time"], ar["time_ps"], "AR handshake")
    same_time(ar_txn["address"]["valid_begin_time"], ar["valid_begin_time_ps"], "AR valid begin")

    b = records["B"][0]
    b_txn = query_record("B", b)
    same_time(b_txn["response"]["handshake_time"], b["time_ps"], "B handshake")

    for channel in ("W", "R"):
        channel_records = records[channel]
        selected = [channel_records[0]]
        middle = next((item for item in channel_records
                       if item["beat_index"] > 1 and not int(item["last"])), None)
        last = next((item for item in channel_records if int(item["last"])), None)
        if middle is not None:
            selected.append(middle)
        if last is not None and last not in selected:
            selected.append(last)
        for index, rec in enumerate(selected):
            txn = query_record(channel, rec, include_data=True)
            data = txn["data"]
            beat = data["beats"][rec["beat_index"] - 1]
            same_time(beat["handshake_time"], rec["time_ps"],
                      "{} beat handshake".format(channel))
            require(bool(beat["last"]) == bool(int(rec["last"])),
                    "AXI {} beat last mismatch".format(channel))
            if rec["beat_index"] == 1:
                same_time(data["valid_begin_time"], rec["valid_begin_time_ps"],
                          "{} first beat valid begin".format(channel))

    not_found = r.query(
        "axi.query",
        args={"name": "axi0", "query": {"channel": "aw", "handshake_time": "1ps"}},
    )
    require(not_found["summary"]["query_mode"] == "handshake" and
            not not_found["summary"]["found"] and
            "transaction" not in not_found["data"],
            "AXI exact handshake query must not use a nearest-time fallback")

    index_times = []
    handshake_times = []
    for _ in range(5):
        r.query("axi.query", args={"name": "axi0", "direction": "write", "query": {"index": 1}})
        index_times.append(r.rows[-1][4])
        r.query(
            "axi.query",
            args={
                "name": "axi0",
                "query": {"channel": "aw", "handshake_time": "{}ps".format(aw["time_ps"])},
            },
        )
        handshake_times.append(r.rows[-1][4])
    index_median = statistics.median(index_times)
    handshake_median = statistics.median(handshake_times)
    print("AXI_QUERY_PERF_JSON " + json.dumps({
        "index_median_ms": index_median,
        "handshake_median_ms": handshake_median,
        "ratio": handshake_median / max(index_median, 1),
    }, sort_keys=True), flush=True)
    require(handshake_median <= 2 * max(index_median, 1),
            "warm AXI handshake query exceeded 2x index query: index={}ms handshake={}ms".format(
                index_median, handshake_median))


def read_axi_export_table(path):
    delimiter = "," if path.endswith(".csv") else "\t"
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        rows = list(reader)
        require(reader.fieldnames is not None, "missing export header: {}".format(path))
        require("data" not in reader.fieldnames, "export unexpectedly contains data column: {}".format(path))
        return rows


def axi_compare_key(row):
    return (
        normalize_sv_hex(row["id"]),
        normalize_sv_hex(row["addr"]),
        normalize_sv_hex(row["len"]),
        normalize_sv_hex(row["size"]),
        normalize_sv_hex(row["burst"]),
        normalize_sv_hex(row["resp"]),
        int(row["beat_count"]),
        int(row["expected_beat_count"]),
    )


def expected_compare_key(row):
    return (
        normalize_sv_hex(row["id"]),
        normalize_sv_hex(row["addr"]),
        normalize_sv_hex(row["len"]),
        normalize_sv_hex(row["size"]),
        normalize_sv_hex(row["burst"]),
        normalize_sv_hex(row["resp"]),
        int(row["beat_count"]),
        int(row["expected_beat_count"]),
    )


def require_completion_sorted(rows, label):
    def completion_time_ps(row):
        if "completion_time_ps" in row:
            return int(row["completion_time_ps"])
        text = row["completion_time"]
        if text.endswith("ps"):
            return int(text[:-2])
        if text.endswith("ns"):
            return int(text[:-2]) * 1000
        if text.endswith("us"):
            return int(text[:-2]) * 1000 * 1000
        if text.endswith("ms"):
            return int(text[:-2]) * 1000 * 1000 * 1000
        return int(text)

    times = [completion_time_ps(row) for row in rows]
    require(times == sorted(times), "{} export is not sorted by completion time".format(label))


def compare_axi_export_to_log(export_data, expected_log, handshake_oracle,
                              expected_count, num_ids, transactions_per_id):
    write_file = export_data["summary"]["output"]["write_path"]
    read_file = export_data["summary"]["output"]["read_path"]
    meta_file = export_data["summary"]["output"]["meta_path"]
    writes = read_axi_export_table(write_file)
    reads = read_axi_export_table(read_file)

    require_completion_sorted(writes, "write")
    require_completion_sorted(reads, "read")

    require(os.path.exists(meta_file), "missing AXI export meta: {}".format(meta_file))
    with open(meta_file, "r", encoding="utf-8") as fh:
        meta = json.load(fh)

    require(len(writes) == expected_count, "unexpected exported write count: {}".format(len(writes)))
    require(len(reads) == expected_count, "unexpected exported read count: {}".format(len(reads)))
    require(len(expected_log["WR"]) == expected_count, "unexpected expected write log count: {}".format(len(expected_log["WR"])))
    require(len(expected_log["RD"]) == expected_count, "unexpected expected read log count: {}".format(len(expected_log["RD"])))

    from collections import Counter

    write_export = Counter(axi_compare_key(row) for row in writes)
    read_export = Counter(axi_compare_key(row) for row in reads)
    write_expected = Counter(expected_compare_key(row) for row in expected_log["WR"])
    read_expected = Counter(expected_compare_key(row) for row in expected_log["RD"])
    require(write_export == write_expected, "write export does not match VIP monitor log")
    require(read_export == read_expected, "read export does not match VIP monitor log")

    expected_ids = ["'h{:x}".format(i) for i in range(num_ids)]
    write_ids = {normalize_sv_hex(v) for v in meta["unique_write_ids"]}
    read_ids = {normalize_sv_hex(v) for v in meta["unique_read_ids"]}
    write_count_by_id = {normalize_sv_hex(k): v for k, v in meta["write_count_by_id"].items()}
    read_count_by_id = {normalize_sv_hex(k): v for k, v in meta["read_count_by_id"].items()}
    require(write_ids == set(expected_ids), "unexpected write id set: {}".format(meta["unique_write_ids"]))
    require(read_ids == set(expected_ids), "unexpected read id set: {}".format(meta["unique_read_ids"]))
    for axi_id in expected_ids:
        require(write_count_by_id.get(axi_id) == transactions_per_id, "write count mismatch for {}".format(axi_id))
        require(read_count_by_id.get(axi_id) == transactions_per_id, "read count mismatch for {}".format(axi_id))
    require(meta["max_total_write_outstanding"] >= min(num_ids, 4), "write outstanding pressure was not observed")
    require(meta["max_total_read_outstanding"] >= min(num_ids, 4), "read outstanding pressure was not observed")
    require(meta["beat_count_mismatch_count"] == 0, "beat count mismatch in export meta")
    require(meta["incomplete_write_count"] == 0, "incomplete writes in export meta")
    require(meta["incomplete_read_count"] == 0, "incomplete reads in export meta")
    require(meta["orphan_w_beat_count"] == 0, "orphan W beats in export meta")
    require(meta["buffered_w_burst_count"] == 0, "buffered W bursts remained after export")
    require(meta["response_dependency_violation_count"] == 0,
            "early AXI response dependency violation in export meta")

    oracle_writes = handshake_oracle["writes"]
    require(len(oracle_writes) == len(writes),
            "raw handshake oracle write count mismatch")
    oracle_orders = Counter(txn["phase_order"] for txn in oracle_writes)
    export_orders = Counter(row["phase_order"] for row in writes)
    require(oracle_orders == export_orders,
            "write phase-order mismatch: oracle={} export={}".format(
                dict(oracle_orders), dict(export_orders)))
    for required_order in ("aw_before_w", "w_before_aw", "same_cycle"):
        require(oracle_orders[required_order] > 0,
                "AXI delay matrix did not produce {}".format(required_order))
    require(any(txn["w_last_time"] < txn["aw_time"] for txn in oracle_writes),
            "AXI delay matrix did not produce a complete W burst before AW")


def make_axi_config(prefix, top="axi_vip_fixture_top", edge="posedge", sample_point=None):
    config = {
        "awaddr": prefix + ".awaddr",
        "awid": prefix + ".awid",
        "awlen": prefix + ".awlen",
        "awsize": prefix + ".awsize",
        "awburst": prefix + ".awburst",
        "awvalid": prefix + ".awvalid",
        "awready": prefix + ".awready",
        "wdata": prefix + ".wdata",
        "wstrb": prefix + ".wstrb",
        "wlast": prefix + ".wlast",
        "wvalid": prefix + ".wvalid",
        "wready": prefix + ".wready",
        "bid": prefix + ".bid",
        "bresp": prefix + ".bresp",
        "bvalid": prefix + ".bvalid",
        "bready": prefix + ".bready",
        "araddr": prefix + ".araddr",
        "arid": prefix + ".arid",
        "arlen": prefix + ".arlen",
        "arsize": prefix + ".arsize",
        "arburst": prefix + ".arburst",
        "arvalid": prefix + ".arvalid",
        "arready": prefix + ".arready",
        "rid": prefix + ".rid",
        "rdata": prefix + ".rdata",
        "rresp": prefix + ".rresp",
        "rlast": prefix + ".rlast",
        "rvalid": prefix + ".rvalid",
        "rready": prefix + ".rready",
        "clock": top + ".clk",
        "reset": {"signal": top + ".rst_n", "polarity": "active_low"},
    }
    if edge is not None:
        config["edge"] = edge
    if sample_point is not None:
        config["sample_point"] = sample_point
    return config


class AiRunner(object):
    def __init__(self, xdebug, fsdb, name):
        self.xdebug = xdebug
        self.fsdb = fsdb
        self.name = name
        self.home = tempfile.mkdtemp(prefix="xdebug_ai_")
        self.env = os.environ.copy()
        self.env["HOME"] = self.home
        self.env["PYTHON"] = sys.executable
        self.sid = None
        self.rows = []
        self.duplicate_contract_violations = []
        self.loop = None

    def ensure_loop(self):
        if self.loop is None:
            self.loop = StdioLoopRunner(
                Path(self.xdebug),
                cwd=Path(REPO_ROOT),
                env=self.env,
                default_json=True,
                wait_for_stderr_idle=False,
            )
            self.loop.start()
        return self.loop

    def cleanup(self):
        try:
            if self.sid:
                self.query("session.close", args={"mode": "force"}, target={"session_id": self.sid}, expect_ok=True, allow_no_sid=True)
            require(not self.duplicate_contract_violations,
                    "summary/data duplicate facts remain: {}".format(self.duplicate_contract_violations))
        finally:
            if self.loop is not None:
                try:
                    self.loop.quit()
                finally:
                    self.loop.terminate()
            shutil.rmtree(self.home, ignore_errors=True)

    def query(self, action, args=None, target=None, limits=None, expect_ok=True, allow_no_sid=False, timeout=60):
        req = {
            "api_version": "xdebug.v1",
            "action": action,
            "args": args or {},
        }
        if target is not None:
            req["target"] = target
        elif self.sid is not None and not allow_no_sid:
            req["target"] = {"session_id": self.sid}
        elif not allow_no_sid:
            raise AssertionError("session must be opened before stateful query")
        request_limits = dict(limits or {})
        if request_limits:
            req["limits"] = request_limits

        start = time.time()
        process_timeout = max(
            timeout,
            int(DEFAULT_QUERY_TIMEOUT_MS / 1000) + 30,
        )
        log_progress(
            "{}: query {} start process_timeout_sec={}".format(
                self.name,
                action,
                process_timeout,
            )
        )
        result = self.ensure_loop().request(req, timeout_sec=process_timeout)
        rc = result.returncode
        out = json.dumps(result.response)
        err = result.stderr_raw
        elapsed_ms = int((time.time() - start) * 1000)
        try:
            data = json.loads(out)
        except Exception:
            raise AssertionError("non-json response for {} rc={} stdout={} stderr={}".format(action, rc, out, err))
        ok = bool(data.get("ok"))
        if action.startswith("axi."):
            schema_path = os.path.join(
                ROOT, "schemas", "v1", "actions", action + ".response.schema.json"
            )
            with open(schema_path, "r", encoding="utf-8") as schema_fh:
                schema = json.load(schema_fh)
            try:
                jsonschema.Draft202012Validator(schema).validate(data)
            except jsonschema.ValidationError as exc:
                raise AssertionError(
                    "{} response schema mismatch at {}: {}\n{}".format(
                        action, list(exc.absolute_path), exc.message,
                        json.dumps(data, indent=2),
                    )
                )
        self.rows.append((self.name, action, rc, ok, elapsed_ms, data.get("meta", {}).get("elapsed_ms")))
        log_progress("{}: query {} done rc={} ok={} elapsed_ms={}".format(self.name, action, rc, ok, elapsed_ms))
        if expect_ok:
            require(rc == 0 and ok, "{} failed rc={} data={} stderr={}".format(action, rc, json.dumps(data, indent=2), err))
            if not action.startswith("session."):
                summary = data.get("summary", {})
                payload = data.get("data", {})
                duplicate_keys = sorted(
                    key for key, value in summary.items()
                    if key in payload and payload[key] == value
                )
                if duplicate_keys:
                    self.duplicate_contract_violations.append({"action": action, "keys": duplicate_keys})
        else:
            require(rc != 0 or not ok, "{} expected failure but passed".format(action))
        return data

    def query_xout(self, action, args=None, target=None, limits=None, timeout=60):
        req = {
            "api_version": "xdebug.v1",
            "action": action,
            "args": args or {},
        }
        if target is not None:
            req["target"] = target
        elif self.sid is not None:
            req["target"] = {"session_id": self.sid}
        else:
            raise AssertionError("session must be opened before stateful XOUT query")
        request_limits = dict(limits or {})
        request_limits.setdefault("timeout_ms", DEFAULT_QUERY_TIMEOUT_MS)
        req["limits"] = request_limits
        process_timeout = max(timeout, int(request_limits["timeout_ms"] / 1000) + 30)
        rc, out, err, _ = run_cmd(
            [self.xdebug, "-"], cwd=REPO_ROOT, env=self.env,
            timeout=process_timeout, input_text=json.dumps(req) + "\n",
        )
        require(rc == 0, "{} XOUT failed rc={} stdout={} stderr={}".format(
            action, rc, out, err))
        return out

    def open(self):
        self.query("session.open", target={"fsdb": self.fsdb}, expect_ok=False, allow_no_sid=True)
        data = self.query("session.open", target={"fsdb": self.fsdb}, args={"name": self.name}, expect_ok=True, allow_no_sid=True)
        self.sid = data["session"]["session_id"]
        self.query("session.open", target={"fsdb": self.fsdb}, args={"name": self.name}, expect_ok=False, allow_no_sid=True)
        return data


def run_nonaxi(xdebug, fsdb):
    r = AiRunner(xdebug, fsdb, "nonaxi")
    try:
        r.open()
        r.query("session.list", expect_ok=True, allow_no_sid=True)
        r.query("session.doctor", target={"session_id": r.sid})
        r.query("session.gc", expect_ok=True, allow_no_sid=True)

        scope = r.query("scope.list", args={"path": "ai_complex_top", "level": 0}, limits={"max_rows": 8})
        require(scope["summary"]["scan_complete"] is True and
                scope["summary"]["analysis_complete"] is True and
                scope["summary"]["response_truncated"] is True,
                "scope.list must distinguish complete scan from response projection")
        require(scope["summary"]["returned_count"] == 8 and
                scope["summary"]["total_count"] > 8 and
                scope["summary"]["truncation_scopes"] == ["response_rows"],
                "scope.list completeness counts/scopes are inconsistent")
        require("signals_preview" not in scope["data"], "scope.list generated redundant data.signals_preview")
        require("examples" not in scope["data"], "scope.list generated placeholder data.examples")
        direct_scope = r.query("scope.list", args={"path": "ai_complex_top", "level": 0}, limits={"max_rows": 100})
        require(any(item["name"] == "sig_a" and item["width"] == 8
                    for item in direct_scope["data"]["signals"]),
                "level-0 scope.list omitted relative sig_a or its width")
        require(direct_scope["summary"]["scan_complete"] is True and
                direct_scope["summary"]["analysis_complete"] is True and
                direct_scope["summary"]["response_truncated"] is False and
                direct_scope["summary"]["total_count"] == direct_scope["summary"]["returned_count"] and
                direct_scope["summary"]["truncation_scopes"] == [],
                "complete level-0 scope.list completeness contract is inconsistent")

        v = r.query("value.at", args={"signal": "ai_complex_top.sig_a", "clock": "ai_complex_top.clk", "time": "75ns", "value_format": "hex"})
        v_cell = v["data"]["samples"][0]["values"][0]
        require(v_cell["value"]["value"] == "8'h22" and v_cell["value"]["known"] is True, "unexpected sig_a value")
        require_clock_context(v, "negedge")
        raw_v = r.query("value.at", args={
            "signal": "ai_complex_top.sig_a",
            "time": "75ns",
            "value_format": "hex",
        })
        require(raw_v["summary"]["sampling_mode"] == "raw_time" and
                "clock_context" not in raw_v["data"]["samples"][0],
                "raw value.at must not publish a clock context")
        xz = r.query("value.at", args={"signal": "ai_complex_top.xz_bus", "clock": "ai_complex_top.clk", "time": "95ns", "value_format": "bin"})
        xz_value = xz["data"]["samples"][0]["values"][0]["value"]
        require(xz_value["known"] is False, "xz_bus should be unknown")
        require("bits" in xz_value and "has_x" in xz_value, "xz_bus lacks logic diagnostics")
        hint = r.query("value.at", args={"signal": "ai_complex_top.sig_a", "clock": "ai_complex_top.clk", "time": "75ns", "value_format": "hex", "slice_hint": {"chunk_width": 4, "count": 2}})
        require(hint["data"]["samples"][0]["values"][0]["xbit_hints"]["status"] == "ready", "xbit hints not generated")
        unsupported = r.query("value.at", args={"signal": "ai_complex_top.sig_a", "clock": "ai_complex_top.clk", "time": "75ns", "format": "hex"}, expect_ok=False)
        require(unsupported["error"]["code"] == "INVALID_REQUEST" and
                unsupported["error"]["invalid_arg"] == "args.format",
                "legacy args.format must be rejected by the public schema")
        r.query("value.at", args={"signal": "ai_complex_top.no_such", "clock": "ai_complex_top.clk", "time": "10ns"}, expect_ok=False)

        loaded = r.query("list.load", args={
            "config": {
                "lists": [{
                    "name": "key_context",
                    "signals": [
                        "ai_complex_top.sig_a",
                        "ai_complex_top.xz_bus",
                    ],
                }],
            },
            "mode": "replace",
        })
        require(loaded["summary"]["loaded"] == 1 and
                loaded["data"]["lists"] == ["key_context"],
                "list.load inline config did not load one list")
        raw_values = r.query("value.at", args={
            "list": "key_context",
            "times": ["75ns", "95ns"],
            "value_format": "hex",
        })
        require(raw_values["summary"]["time_count"] == 2 and
                [sample["time"] for sample in raw_values["data"]["samples"]] ==
                ["75ns", "95ns"],
                "value.at list selector did not preserve requested time order")
        require(all(sample["sampling_mode"] == "raw_time" and
                    "clock_context" not in sample
                    for sample in raw_values["data"]["samples"]),
                "raw value.at list selector published clock context")
        clock_values = r.query("value.at", args={
            "list": "key_context",
            "clock": "ai_complex_top.clk",
            "times": ["75ns", "95ns"],
            "value_format": "hex",
        })
        require(all(sample["sampling_mode"] == "clock_sampled" and
                    "clock_context" in sample
                    for sample in clock_values["data"]["samples"]),
                "clock-sampled value.at list selector omitted per-time context")
        require(v["data"]["samples"][0]["clock_context"] ==
                clock_values["data"]["samples"][0]["clock_context"],
                "value.at selectors must share one clock bracket contract")
        r.query("list.load", args={
            "config": {
                "lists": [{
                    "name": "invalid_context",
                    "signals": ["ai_complex_top.no_such"],
                }],
            },
        }, expect_ok=False)
        r.query("list.show", args={"name": "invalid_context"}, expect_ok=False)

        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False,
                encoding="utf-8") as list_config:
            json.dump({
                "lists": [{
                    "name": "file_context",
                    "signals": ["ai_complex_top.sig_b"],
                }],
            }, list_config)
            list_config_path = list_config.name
        try:
            file_loaded = r.query("list.load", args={
                "config_path": list_config_path,
                "mode": "append",
            })
            require(file_loaded["data"]["lists"] == ["file_context"],
                    "list.load config_path did not load expected list")
        finally:
            os.unlink(list_config_path)

        created = r.query("list.create", args={"name": "basic"})
        require("summary" not in created["data"], "list.create generated nested data.summary")
        added_a = r.query("list.add", args={"name": "basic", "signal": "ai_complex_top.sig_a"})
        require("summary" not in added_a["data"], "list.add generated nested data.summary")
        r.query("list.add", args={"name": "basic", "signal": "ai_complex_top.sig_b"})
        r.query("list.add", args={"name": "basic", "signal": "ai_complex_top.no_such"}, expect_ok=False)
        show = r.query("list.show", args={"name": "basic"})
        require(show["summary"]["signal_count"] == 2, "list.show count mismatch")
        require("count" not in show["data"], "list.show generated redundant data.count")
        values = r.query("value.at", args={"list": "basic", "clock": "ai_complex_top.clk", "times": ["75ns"], "value_format": "hex"})
        require("summary" not in values["data"], "value.at generated nested data.summary")
        require(
            values["data"]["samples"][0]["clock_context"][
                "effective_sampling"]["edge"] == "negedge",
            "value.at list selector clock context edge mismatch")
        validated = r.query("list.validate", args={"name": "basic"})
        require("all_found" in validated["summary"], "list.validate did not expose all_found at source")
        require("summary" not in validated["data"], "list.validate generated nested data.summary")
        diff = r.query("list.first_change", args={"name": "basic", "time_range": {"begin": "0ns", "end": "120ns"}})
        require("ns" in diff["summary"]["diff_time"] or "ps" in diff["summary"]["diff_time"], "list.first_change did not return time")
        require(diff["summary"]["changed_signal_count"] >= 1,
                "list.first_change must report signals that actually changed at diff_time")
        require(all(item["before"]["value"] != item["after"]["value"]
                    for item in diff["data"]["changed_signals"]),
                "list.first_change must not report unchanged signals")
        require("time" not in diff["data"], "list.first_change generated redundant data.time")
        list_export_dir = tempfile.mkdtemp(prefix="xdebug_list_export_")
        list_export = r.query("list.export", args={
            "name": "basic",
            "time_range": {"begin": "0ns", "end": "400ns"},
            "output": {"path": list_export_dir, "file_format": "u64bin"},
        })
        require("summary" not in list_export["data"], "list.export generated nested data.summary")
        manifest_file = list_export["summary"]["output"]["manifest_path"]
        require(os.path.exists(manifest_file), "missing list.export manifest")
        with open(manifest_file, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        require(manifest["format"] == "u64bin.v1", "unexpected list.export format")
        require(manifest["signal_count"] == 2, "unexpected exported signal count")
        require(manifest["row_count"] >= 2, "list.export did not write rows")
        for item in manifest["signals"]:
            require(os.path.exists(os.path.join(list_export_dir, item["file"])), "missing list.export signal file")
        image_file = os.path.join(list_export_dir, "wave.jpg")
        rc, out, err, _ = run_cmd([
            os.path.join(REPO_ROOT, "tools", "xwaveform"),
            "render",
            "--manifest", manifest_file,
            "--output", image_file,
            "--width", "4096",
            "--cursor-count", "32",
            "--json",
        ], cwd=REPO_ROOT, env=r.env, timeout=60)
        require(rc == 0, "xwaveform render failed\n{}\n{}".format(out, err))
        rendered = json.loads(out)
        require(rendered["width"] == 4096, "xwaveform did not render 4096px width")
        require(os.path.exists(rendered["image_file"]), "missing xwaveform JPG")
        require(os.path.exists(rendered["stats_file"]), "missing xwaveform stats")
        r.query("list.delete", args={"name": "basic", "index": 2})
        r.query("list.show", args={"name": "basic"})

        event_cfg = os.path.join(NONAXI_DIR, "config", "event0.json")
        r.query("event.config.load", args={"name": "evt0", "config_path": event_cfg})
        r.query("event.config.list", args={"name": "evt0"})
        found = r.query("event.find", args={"name": "evt0", "expr": "vld && !rdy && payload_lo != 0", "time_range": {"begin": "0ns", "end": "200ns"}})
        require(len(found["data"]["events"]) == 1, "event.find did not return one event")
        all_limited = r.query("event.find", args={
            "name": "evt0", "expr": "vld", "mode": "all",
            "time_range": {"begin": "0ns", "end": "200ns"}, "line_limit": 1,
        })
        require(all_limited["summary"]["total_count"] >
                all_limited["summary"]["returned_count"] == 1,
                "event.find all must report full match count with limited response")
        require(all_limited["summary"]["analysis_complete"] is True and
                all_limited["summary"]["response_truncated"] is True,
                "event.find response truncation must not imply incomplete analysis")
        last_event = r.query("event.find", args={
            "name": "evt0", "expr": "vld", "mode": "last",
            "time_range": {"begin": "0ns", "end": "200ns"},
        })
        require(last_event["data"]["events"][0]["time"] == all_limited["summary"]["last"],
                "event.find last must return the true last match")
        require_clock_sampling_contract(found, "posedge")
        require("examples" not in found["data"], "event.find generated redundant data.examples")
        ge_threshold = r.query("event.find", args={"name": "evt0", "expr": "vld && !rdy && payload_lo >= 10", "time_range": {"begin": "0ns", "end": "200ns"}})
        require(len(ge_threshold["data"]["events"]) == 1, "event.find >= threshold failed")
        gt_literal = r.query("event.find", args={"name": "evt0", "expr": "vld && !rdy && payload_lo > 4'h9", "time_range": {"begin": "0ns", "end": "200ns"}})
        require(len(gt_literal["data"]["events"]) == 1, "event.find > SV literal failed")
        lt_threshold = r.query("event.find", args={"name": "evt0", "expr": "vld && !rdy && payload_lo < 10", "time_range": {"begin": "0ns", "end": "200ns"}})
        require(len(lt_threshold["data"]["events"]) == 0, "event.find < threshold matched unexpectedly")
        inline = r.query("event.find", args={
            "expr": "vld && !rdy",
            "clock": "ai_complex_top.clk",
            "edge": "posedge",
            "reset": {"signal": "ai_complex_top.rst_n", "polarity": "active_low"},
            "signals": {
                "vld": "ai_complex_top.event_vld",
                "rdy": "ai_complex_top.event_rdy"
            },
            "time_range": {"begin": "0ns", "end": "200ns"},
            "mode": "last"
        })
        require(inline["summary"]["inline"] is True and len(inline["data"]["events"]) == 1, "inline event.find failed")
        require_clock_sampling_contract(inline, "posedge")
        require("examples" not in inline["data"], "inline event.find generated redundant data.examples")
        race_before = r.query("event.find", args={
            "expr": "!vld && !race",
            "clock": "ai_complex_top.clk",
            "edge": "posedge",
            "sample_point": "before",
            "reset": {"signal": "ai_complex_top.rst_n", "polarity": "active_low"},
            "signals": {
                "vld": "ai_complex_top.event_vld",
                "race": "ai_complex_top.event_race"
            },
            "time_range": {"begin": "100ns", "end": "110ns"},
            "mode": "first"
        })
        require(len(race_before["data"]["events"]) == 1, "event.find posedge before did not observe old values")
        require_clock_sampling_contract(race_before, "posedge", "before")
        race_after = r.query("event.find", args={
            "expr": "vld && race",
            "clock": "ai_complex_top.clk",
            "edge": "posedge",
            "sample_point": "after",
            "reset": {"signal": "ai_complex_top.rst_n", "polarity": "active_low"},
            "signals": {
                "vld": "ai_complex_top.event_vld",
                "race": "ai_complex_top.event_race"
            },
            "time_range": {"begin": "100ns", "end": "110ns"},
            "mode": "first"
        })
        require(len(race_after["data"]["events"]) == 1, "event.find posedge after did not observe new values")
        require_clock_sampling_contract(race_after, "posedge", "after")
        r.query("stream.config.load", args={"config": {"streams": [
            {
                "name": "race_before_stream",
                "signals": {
                    "clk": "ai_complex_top.clk",
                    "vld": "ai_complex_top.event_vld",
                    "rdy": "ai_complex_top.event_race",
                    "payload": "ai_complex_top.event_payload",
                },
                "clock": "clk",
                "edge": "posedge",
                "sample_point": "before",
                "reset": {"signal": "ai_complex_top.rst_n", "polarity": "active_low"},
                "vld": "vld",
                "rdy": "rdy",
                "data": "payload",
            },
            {
                "name": "race_after_stream",
                "signals": {
                    "clk": "ai_complex_top.clk",
                    "vld": "ai_complex_top.event_vld",
                    "rdy": "ai_complex_top.event_race",
                    "payload": "ai_complex_top.event_payload",
                },
                "clock": "clk",
                "edge": "posedge",
                "sample_point": "after",
                "reset": {"signal": "ai_complex_top.rst_n", "polarity": "active_low"},
                "vld": "vld",
                "rdy": "rdy",
                "data": "payload",
            },
        ]}})
        stream_before = r.query("stream.query", args={
            "stream": "race_before_stream",
            "query": "summary",
            "time_range": {"begin": "100ns", "end": "110ns"},
        })
        stream_after = r.query("stream.query", args={
            "stream": "race_after_stream",
            "query": "summary",
            "time_range": {"begin": "100ns", "end": "110ns"},
        })
        require_clock_summary(stream_before, "posedge", "before", expected_clock="clk")
        require_clock_summary(stream_after, "posedge", "after", expected_clock="clk")
        require(stream_before["summary"]["transfer_count"] == 0,
                "stream posedge before should not observe same-edge event_vld/event_race transfer")
        require(stream_after["summary"]["transfer_count"] == 1,
                "stream posedge after should observe same-edge event_vld/event_race transfer")
        exported = r.query("event.export", args={"name": "evt0", "expr": "vld && !rdy", "time_range": {"begin": "0ns", "end": "200ns"}, "line_limit": 1})
        require(len(exported["data"]["events"]) == 1, "event.export limit failed")
        require_clock_sampling_contract(exported, "posedge")
        require("examples" not in exported["data"], "event.export generated redundant data.examples")
        event_vld = exported["data"]["events"][0]["signals"]["vld"]
        require("'h" in event_vld["value"] and event_vld["known"] is True, "event signal value is not normalized")
        agg = r.query("event.export", args={"name": "evt0", "expr": "vld && !rdy", "time_range": {"begin": "0ns", "end": "200ns"}, "aggregate": {"group_by": ["payload_lo"], "events": False}})
        require("events" not in agg["data"] and agg["data"]["aggregate"]["count"] >= 1, "event aggregate count failed")
        require(agg["data"]["aggregate"]["group_count"] >= 1, "event aggregate group failed")
        no_xz = r.query("event.export", args={"name": "evt0", "expr": "xz != 0", "time_range": {"begin": "0ns", "end": "200ns"}, "line_limit": 5})
        require(len(no_xz["data"]["events"]) == 0, "x/z event comparison matched unexpectedly")
        no_xz_order = r.query("event.export", args={"name": "evt0", "expr": "xz >= 1", "time_range": {"begin": "0ns", "end": "200ns"}, "line_limit": 5})
        require(len(no_xz_order["data"]["events"]) == 0, "x/z event ordering comparison matched unexpectedly")
        r.query("event.find", args={"name": "evt0", "expr": "bad_alias", "time_range": {"begin": "0ns", "end": "200ns"}}, expect_ok=False)
        bad_clock_field = r.query("event.find", args={
            "expr": "vld",
            "clk": "ai_complex_top.clk",
            "signals": {"vld": "ai_complex_top.event_vld"},
            "time_range": {"begin": "0ns", "end": "200ns"},
        }, expect_ok=False)
        require(bad_clock_field["error"]["code"] == "INVALID_REQUEST", "legacy clk should be INVALID_REQUEST")
        require(bad_clock_field["error"]["invalid_arg"] == "args.clk", "legacy clk should identify args.clk")
        require("clock" in bad_clock_field["error"]["expected"], "legacy clk expected guidance should mention clock")

        checks = r.query("verify.conditions", args={
            "clock": "ai_complex_top.clk",
            "time": "95ns",
            "signals": {
                "a": "ai_complex_top.sig_a",
                "b": "ai_complex_top.sig_b",
                "xz": "ai_complex_top.xz_bus",
            },
            "conditions": [
                {"expr": "a == 'h22"},
                {"expr": "b == 'h22"},
                {"expr": "xz == 0"},
            ],
        })
        require(checks["summary"]["passed"] == 1 and checks["summary"]["failed"] == 1 and checks["summary"]["unknown"] == 1, "verify.conditions mismatch")
        require("results" not in checks["data"], "verify.conditions generated redundant data.results")
        require("checks" in checks["data"], "verify.conditions did not expose data.checks")
        require_clock_context(checks, "negedge")

        expr = r.query("expr.eval_at", args={
            "clock": "ai_complex_top.clk",
            "time": "145ns",
            "expr": "valid && !ready",
            "signals": {"valid": "ai_complex_top.hs_valid", "ready": "ai_complex_top.hs_ready"},
        })
        require(expr["data"]["expr_value"] is True, "expr.eval_at expected true")
        require_clock_context(expr, "negedge")
        require(not any(field in expr["summary"] for field in (
                    "requested_any_edge_hit",
                    "requested_target_edge_hit",
                    "bracket_complete",
                )),
                "expr.eval_at summary must not duplicate clock_context facts")
        expr_u = r.query("expr.eval_at", args={
            "clock": "ai_complex_top.clk",
            "time": "95ns",
            "expr": "xz != 0",
            "signals": {"xz": "ai_complex_top.xz_bus"},
        })
        require(expr_u["summary"]["known"] is False, "expr.eval_at xz should be unknown")
        require_clock_context(expr_u, "negedge")

        win = r.query("window.verify", args={
            "clock": "ai_complex_top.clk",
            "edge": "posedge",
            "sample_point": "after",
            "time_range": {"begin": "140ns", "end": "175ns"},
            "signals": {"valid": "ai_complex_top.hs_valid", "ready": "ai_complex_top.hs_ready"},
            "conditions": [{"expr": "valid && !ready", "mode": "always"}],
        })
        require(win["summary"]["all_passed"] is True, "window.verify expected pass")
        limited_window = r.query("window.verify", args={
            "clock": "ai_complex_top.clk",
            "signals": {"a": "ai_complex_top.sig_a"},
            "conditions": [{"expr": "a == 8'hff", "mode": "eventually"}],
            "time_range": {"begin": "0ns", "end": "120ns"},
            "line_limit": 1,
        })
        require(limited_window["summary"]["sample_count"] > 1 and
                limited_window["summary"]["scan_complete"] is True,
                "window.verify line_limit must not cap sampled analysis")
        require(limited_window["summary"]["returned_count"] == 1 and
                limited_window["summary"]["response_truncated"] is True,
                "window.verify response evidence limit mismatch")
        require_clock_sampling_contract(win, "posedge", "after")
        offset_win = r.query("window.verify", args={
            "clock": "ai_complex_top.clk",
            "edge": "posedge",
            "sample_point": "before",
            "time_range": {"begin": "140ns", "end": "175ns"},
            "signals": {"valid": "ai_complex_top.hs_valid", "ready": "ai_complex_top.hs_ready"},
            "conditions": [{"expr": "valid && !ready", "mode": "eventually"}],
        })
        require(offset_win["summary"]["all_passed"] is True,
                "window.verify positive offset expected eventually pass: {}".format(json.dumps(offset_win, sort_keys=True)))
        require_clock_sampling_contract(offset_win, "posedge", "before")
        dual_win = r.query("window.verify", args={
            "clock": "ai_complex_top.clk",
            "edge": "dual",
            "time_range": {"begin": "140ns", "end": "160ns"},
            "signals": {"rst": "ai_complex_top.rst_n"},
            "conditions": [{"expr": "rst", "mode": "always"}],
        })
        require(dual_win["summary"]["sample_count"] >= 4, "dual edge window should sample both edges")
        require_clock_sampling_contract(dual_win, "dual")
        bad_window_field = r.query("window.verify", args={
            "clock": "ai_complex_top.clk",
            "posedge": True,
            "time_range": {"begin": "140ns", "end": "175ns"},
            "signals": {"valid": "ai_complex_top.hs_valid"},
            "conditions": [{"expr": "valid"}],
        }, expect_ok=False)
        require(bad_window_field["error"]["code"] == "INVALID_REQUEST", "legacy posedge should be INVALID_REQUEST")
        require(bad_window_field["error"]["invalid_arg"] == "args.posedge", "legacy posedge should identify args.posedge")

        changes = r.query("signal.changes", args={"signal": "ai_complex_top.sig_a", "time_range": {"begin": "0ns", "end": "120ns"}, "line_limit": 2})
        require(changes["summary"]["analysis_complete"] is True and
                changes["summary"]["response_truncated"] is True and
                changes["summary"]["returned_count"] == 2 and
                changes["summary"]["total_count"] > 2 and
                changes["summary"]["truncation_scopes"] == ["response_changes"],
                "signal.changes must distinguish full analysis from response projection")
        complete_changes = r.query("signal.changes", args={"signal": "ai_complex_top.sig_a", "time_range": {"begin": "0ns", "end": "120ns"}, "line_limit": 100})
        require(complete_changes["summary"]["actual_transition_count"] > 0, "signal.changes found no transitions")
        require(complete_changes["summary"]["scan_complete"] is True and
                complete_changes["summary"]["analysis_complete"] is True and
                complete_changes["summary"]["response_truncated"] is False and
                complete_changes["summary"]["total_count"] == complete_changes["summary"]["returned_count"] and
                complete_changes["summary"]["truncation_scopes"] == [],
                "complete signal.changes completeness contract is inconsistent")
        stab = r.query("signal.stability", args={"signal": "ai_complex_top.stable_sig", "time_range": {"begin": "0ns", "end": "400ns"}})
        require(stab["summary"]["stable"] is True, "stable_sig should be stable")
        require(stab["summary"]["actual_transition_count"] == 0,
                "stable initial value must not be counted as a transition")
        x_exact = r.query("signal.xz_verify", args={
            "signal": "ai_complex_top.xz_bus",
            "expected_state": "x",
            "time_range": {"begin": "86ns", "end": "94ns"},
        })
        require(x_exact["summary"]["verdict"] == "pass", "all-X exact window should pass")
        require(x_exact["summary"]["match_mode"] == "exact", "match_mode should default to exact")
        require(x_exact["summary"]["scan_complete"] is True, "passing X/Z proof must scan the window")
        require(x_exact["data"]["first_mismatch"] is None, "passing X/Z proof must not report mismatch")

        z_exact = r.query("signal.xz_verify", args={
            "signal": "ai_complex_top.xz_bus",
            "expected_state": "z",
            "match_mode": "exact",
            "time_range": {"begin": "96ns", "end": "105ns"},
        })
        require(z_exact["summary"]["verdict"] == "pass", "all-Z exact window should pass")

        for expected_state in ("x", "z"):
            mixed = r.query("signal.xz_verify", args={
                "signal": "ai_complex_top.mixed_xz_bus",
                "expected_state": expected_state,
                "match_mode": "contains",
                "time_range": {"begin": "86ns", "end": "105ns"},
            })
            require(mixed["summary"]["verdict"] == "pass",
                    "mixed vector should contain {} throughout window".format(expected_state))

        mixed_exact = r.query("signal.xz_verify", args={
            "signal": "ai_complex_top.mixed_xz_bus",
            "expected_state": "x",
            "match_mode": "exact",
            "time_range": {"begin": "86ns", "end": "105ns"},
        })
        require(mixed_exact["summary"]["verdict"] == "fail", "mixed vector must fail exact X")
        require(mixed_exact["summary"]["analysis_complete"] is True,
                "first mismatch is a conclusive result")
        require(mixed_exact["summary"]["scan_complete"] is False,
                "first mismatch should stop the raw scan")
        require(mixed_exact["summary"]["stop_reason"] == "first_mismatch",
                "failed X/Z proof should expose stop reason")
        require(mixed_exact["data"]["first_mismatch"]["sample_time"] == "86ns",
                "first mismatch must use the closed-window begin sample")

        end_boundary = r.query("signal.xz_verify", args={
            "signal": "ai_complex_top.xz_bus",
            "expected_state": "x",
            "time_range": {"begin": "86ns", "end": "95ns"},
        })
        require(end_boundary["summary"]["verdict"] == "fail",
                "closed-window end transition must be checked")
        require(end_boundary["data"]["first_mismatch"]["sample_time"] == "95ns",
                "end-boundary mismatch time is wrong")

        single_point = r.query("signal.xz_verify", args={
            "signal": "ai_complex_top.xz_bus",
            "expected_state": "z",
            "time_range": {"begin": "95ns", "end": "95ns"},
        })
        require(single_point["summary"]["verdict"] == "pass",
                "begin=end should check one finalized raw value")

        bad_xz_range = r.query("signal.xz_verify", args={
            "signal": "ai_complex_top.xz_bus",
            "expected_state": "x",
            "time_range": {"begin": "100ns", "end": "90ns"},
        }, expect_ok=False)
        require(bad_xz_range["error"]["code"] == "TIME_RANGE_INVALID",
                "reverse X/Z window should be TIME_RANGE_INVALID")

        missing_xz_signal = r.query("signal.xz_verify", args={
            "signal": "ai_complex_top.no_such",
            "expected_state": "x",
            "time_range": {"begin": "86ns", "end": "94ns"},
        }, expect_ok=False)
        require(missing_xz_signal["error"]["code"] == "SIGNAL_NOT_FOUND",
                "missing X/Z signal should be SIGNAL_NOT_FOUND")
        stats = r.query("signal.statistics", args={"signal": "ai_complex_top.hs_valid", "clock": "ai_complex_top.clk", "time_range": {"begin": "120ns", "end": "210ns"}, "line_limit": 1000})
        require_clock_sampling_contract(stats, "negedge")
        require(stats["summary"]["sample_count"] > 0 and stats["summary"]["known_count"] > 0, "signal.statistics did not sample")
        require("high_cycles" in stats["data"] and "low_cycles" in stats["data"], "signal.statistics missing cycle counts")
        raw_stats = r.query("signal.statistics", args={
            "signal": "ai_complex_top.hs_valid",
            "time_range": {"begin": "120ns", "end": "210ns"},
            "line_limit": 1000,
        })
        require(raw_stats["summary"]["sampling_mode"] == "raw_value_changes" and
                "sampling" not in raw_stats["data"],
                "raw signal.statistics must not publish a clock sampling contract")
        offset_stats = r.query("signal.statistics", args={
            "signal": "ai_complex_top.hs_valid",
            "clock": "ai_complex_top.clk",
            "edge": "posedge",
            "sample_point": "before",
            "time_range": {"begin": "140ns", "end": "175ns"},
            "line_limit": 1000,
        })
        require_clock_sampling_contract(offset_stats, "posedge", "before")
        require(offset_stats["summary"]["sample_count"] > 0, "signal.statistics negative offset did not sample")
        anomaly = r.query("signal.anomaly.inspect", args={
            "signals": ["ai_complex_top.glitch_sig", "ai_complex_top.stuck_sig", "ai_complex_top.xz_bus"],
            "time_range": {"begin": "0ns", "end": "200ns"},
            "checks": [{"type": "glitch", "min_pulse_width": "1ns"}, {"type": "stuck", "min_duration": "100ns"}, {"type": "unknown_xz"}],
            "line_limit": 10,
        })
        require(anomaly["summary"]["total_count"] >= 3 and
                anomaly["summary"]["returned_count"] == len(anomaly["data"]["findings"]),
                "signal.anomaly.inspect missing findings")
        require(any(f.get("type") == "glitch" for f in anomaly["data"].get("findings", [])), "glitch not detected")
        require(any(f.get("type") == "unknown_xz" and f.get("value", {}).get("value") == "8'hzz"
                    for f in anomaly["data"].get("findings", [])), "Z finding not preserved in signal.anomaly.inspect JSON")
        sampled_pulse = r.query("signal.sampled_pulse.inspect", args={
            "clock": "ai_complex_top.clk",
            "valid": "ai_complex_top.glitch_sig",
            "payloads": ["ai_complex_top.sig_a"],
            "edge": "posedge",
            "time_range": {"begin": "0ns", "end": "140ns"},
            "line_limit": 1,
        })
        require(sampled_pulse["summary"]["analysis_complete"] is True,
                "sampled_pulse analysis must cover the complete requested window")
        require(sampled_pulse["summary"]["returned_count"] == 1,
                "sampled_pulse line_limit must only limit returned findings")
        require(sampled_pulse["summary"]["total_count"] >= sampled_pulse["summary"]["returned_count"],
                "sampled_pulse total_count must count all analyzed findings")
        require(sampled_pulse["summary"]["payload_changed_without_sampled_valid_reporting"] == "summary",
                "sampled_pulse payload risk reporting must default to summary")
        require(not any(item.get("type") == "payload_changed_without_sampled_valid"
                        for item in sampled_pulse["data"]["findings"]),
                "sampled_pulse summary mode must not expand payload-risk findings")
        finding = sampled_pulse["data"]["findings"][0]
        raw_begin = time_ns(finding["raw_begin"])
        raw_end = time_ns(finding["raw_end"])
        require(time_ns(finding["previous_sample_edge"]) <= raw_begin,
                "sampled_pulse previous edge must bracket the raw pulse")
        require(time_ns(finding["next_sample_edge"]) >= raw_end,
                "sampled_pulse next edge must bracket the raw pulse")
        bad_checks = r.query("signal.anomaly.inspect", args={
            "signals": ["ai_complex_top.glitch_sig", "ai_complex_top.xz_bus"],
            "time_range": {"begin": "0ns", "end": "200ns"},
            "checks": ["unknown_xz", "glitch"],
        }, expect_ok=False)
        require(bad_checks["error"]["code"] == "INVALID_REQUEST", "string checks should return INVALID_REQUEST")
        require(bad_checks["error"]["invalid_arg"] == "args.checks[0]", "bad checks should expose invalid_arg")
        require(isinstance(bad_checks["error"].get("expected"), str) and bad_checks["error"]["expected"],
                "bad checks should explain the rejected item")
        require(bad_checks["error"]["received_type"] == "string", "bad checks should expose received_type")
        require("correct_example" in bad_checks["error"], "bad checks should expose correct_example")
        bad_type = r.query("signal.anomaly.inspect", args={
            "signals": ["ai_complex_top.glitch_sig", "ai_complex_top.xz_bus"],
            "time_range": {"begin": "0ns", "end": "200ns"},
            "checks": [{"type": "unknown"}],
        }, expect_ok=False)
        require(bad_type["error"]["code"] == "INVALID_REQUEST", "unknown check type should return INVALID_REQUEST")
        require(bad_type["error"]["invalid_arg"] == "args.checks[0]",
                "unknown check type should expose the rejected check item")
        health = r.query("value.at", args={"signal": "ai_complex_top.clk", "clock": "ai_complex_top.clk",
                                            "edge": "negedge", "sample_point": "after", "time": "10ns"})
        require(health["ok"] is True, "session should remain healthy after invalid signal.anomaly.inspect checks")
        require_clock_context(health, "negedge", "after")
        clock_context = health["data"]["samples"][0]["clock_context"]
        require(clock_context["requested_sampling"]["sample_point"] == "after",
                "negedge request must retain requested sample_point")
        require(clock_context["effective_sampling"]["sample_point"] is None and
                clock_context["sample_point_applied"] is False and
                clock_context["sample_point_ignored_for_negedge"] is True,
                "negedge sample_point must use the existing negedge semantics")
        hs = r.query("protocol.handshake.inspect", args={
            "clock": "ai_complex_top.clk",
            "valid": "ai_complex_top.hs_valid",
            "ready": "ai_complex_top.hs_ready",
            "data": ["ai_complex_top.hs_data"],
            "time_range": {"begin": "120ns", "end": "210ns"},
            "rules": {"max_wait_cycles": 2, "check_data_stable_when_stalled": True},
        })
        require(hs["summary"]["max_stall_cycles"] >= 3 and hs["summary"]["data_stability_violations"] >= 1, "protocol.handshake.inspect mismatch")
        require_clock_sampling_contract(hs, "negedge")
        require(hs["summary"]["ready_without_valid_reporting"] == "summary",
                "handshake default ready-without-valid reporting must be summary")
        require(hs["summary"]["require_valid_hold_until_handshake"] is True,
                "handshake must enable valid-hold checking by default")
        require(not any(item.get("type") == "ready_without_valid" for item in hs["data"]["findings"]),
                "summary reporting must not emit one finding per ready-without-valid cycle")
        hs_valid_drop = r.query("protocol.handshake.inspect", args={
            "clock": "ai_complex_top.clk",
            "valid": "ai_complex_top.event_vld",
            "ready": "ai_complex_top.event_rdy",
            "time_range": {"begin": "0ns", "end": "200ns"},
        })
        require(hs_valid_drop["summary"]["valid_hold_violations"] >= 1,
                "handshake must detect valid deassertion before handshake")
        require(any(item.get("type") == "valid_dropped_before_handshake"
                    for item in hs_valid_drop["data"]["findings"]),
                "handshake valid-hold violation evidence missing")
        hs_intervals = r.query("protocol.handshake.inspect", args={
            "clock": "ai_complex_top.clk",
            "valid": "ai_complex_top.hs_valid",
            "ready": "ai_complex_top.hs_ready",
            "time_range": {"begin": "120ns", "end": "210ns"},
            "rules": {"ready_without_valid": "intervals"},
        })
        require(hs_intervals["summary"]["ready_without_valid_reporting"] == "intervals",
                "interval ready-without-valid reporting mismatch")
        require(hs_intervals["summary"]["ready_without_valid_cycles"] == hs["summary"]["ready_without_valid_cycles"],
                "ready-without-valid reporting mode must not change the count")
        intervals = hs_intervals["data"].get("ready_without_valid_intervals", [])
        require(all("begin" in item and "end" in item and "cycle_count" in item for item in intervals),
                "ready-without-valid intervals must expose begin/end/cycle_count")
        require(all("cycles" not in item for item in intervals),
                "ready-without-valid intervals must not duplicate cycle_count")
        hs_all = r.query("protocol.handshake.inspect", args={
            "clock": "ai_complex_top.clk",
            "valid": "ai_complex_top.hs_valid",
            "ready": "ai_complex_top.hs_ready",
            "time_range": {"begin": "120ns", "end": "210ns"},
            "rules": {"ready_without_valid": "all"},
        })
        ready_rows = [item for item in hs_all["data"]["findings"]
                      if item.get("type") == "ready_without_valid"]
        require(len(ready_rows) == hs_all["summary"]["ready_without_valid_cycles"],
                "all reporting must retain one ready-without-valid finding per cycle")
        sampling = hs["data"]["sampling"]
        require(sampling["effective"]["sample_point"] is None and not sampling["sample_point_applied"],
                "negedge sampling contract must report no effective sample_point")
        return r.rows
    finally:
        r.cleanup()


def run_axi(xdebug, fsdb, sim_log=AXI_SIM_LOG, handshake_oracle_path=AXI_HANDSHAKE_ORACLE,
            expected_count=3200, num_ids=16, transactions_per_id=200,
            min_random_delay=50, max_random_delay=100):
    r = AiRunner(xdebug, fsdb, "axi")
    cache_probe = os.path.join(r.home, "axi-analysis-cache.jsonl")
    r.env["XDEBUG_TEST_ANALYSIS_PROBE_PATH"] = cache_probe
    try:
        r.open()
        prefix = "axi_vip_fixture_top.axi_vip_if.master_if[0]"
        r.query("axi.config.load", args={"name": "axi0", "config": make_axi_config(prefix)})
        r.query("axi.config.list", args={"name": "axi0"})
        wr = r.query("axi.query", args={"name": "axi0", "direction": "write"})
        rd = r.query("axi.query", args={"name": "axi0", "direction": "read"})
        for response, direction in ((wr, "write"), (rd, "read")):
            summary = response["summary"]
            require(summary["query_mode"] == "count" and
                    summary["direction"] == direction and
                    summary["scan_complete"] is True and
                    summary["analysis_complete"] is True and
                    summary["response_truncated"] is False and
                    summary["total_count"] == expected_count and
                    summary["returned_count"] == 0 and
                    summary["truncation_scopes"] == [],
                    "AXI {} count-only query contract mismatch".format(direction))
            require(response["data"]["filter"]["direction"] == direction and
                    "transaction" not in response["data"] and
                    "transactions" not in response["data"],
                    "AXI {} count-only query returned transaction rows".format(direction))
        axi_xout = r.query_xout("axi.query", args={
            "name": "axi0",
            "direction": "write",
            "query": {"index": 1},
            "output": {"include_data": True},
        })
        require(axi_xout.startswith("@xdebug.axi.query.v1\n"), "AXI XOUT header mismatch")
        for section in (
            "transaction:", "transaction_address:", "transaction_data:",
            "transaction_beats:", "transaction_response:",
        ):
            require("\n{}\n".format(section) in axi_xout,
                    "AXI XOUT missing {}".format(section))
        for field in (
            "direction", "phase_order", "latency", "response_dependency_violation",
            "valid_begin_time", "handshake_time", "addr", "id", "len", "size",
            "burst", "beat_count", "expected_beat_count", "data", "wstrb", "last",
            "resp",
        ):
            require(field in axi_xout, "AXI XOUT lost {}".format(field))
        for forbidden in (
            "{", "}", '"', "known=true", "XOUT_BEGIN", "XOUT_END",
            "pointer\tkind\tvalue",
        ):
            require(forbidden not in axi_xout,
                    "AXI XOUT leaked {!r}".format(forbidden))
        require(axi_xout.endswith("\n") and not axi_xout.endswith("\n\n"),
                "AXI XOUT must end with exactly one newline")
        expected_log = parse_axi_expected_log(sim_log)
        expected_records = expected_log["WR"] + expected_log["RD"]

        def numeric_value(value):
            return int(normalize_sv_hex(value)[2:], 16)

        all_statistics = r.query("axi.statistics", args={"name": "axi0"})
        require(all_statistics["summary"]["scanned_transaction_count"] == 2 * expected_count and
                all_statistics["summary"]["matched_transaction_count"] == 2 * expected_count and
                all_statistics["summary"]["matched_read_count"] == expected_count and
                all_statistics["summary"]["matched_write_count"] == expected_count and
                all_statistics["summary"]["unresolved_transaction_count"] == 0 and
                all_statistics["summary"]["full_scan_count"] == 1,
                "AXI unfiltered statistics mismatch")

        selected_ids = list(range(min(num_ids, 2)))
        selected_addresses = sorted({numeric_value(row["addr"]) for row in expected_records})[:2]
        exact_expected = sum(
            1 for row in expected_log["WR"]
            if numeric_value(row["id"]) in selected_ids and
            numeric_value(row["addr"]) in selected_addresses
        )
        exact_statistics = r.query("axi.statistics", args={
            "name": "axi0",
            "filter": {
                "direction": "write",
                "ids": [str(value) for value in selected_ids],
                "address": {
                    "mode": "exact",
                    "values": ["32'h{:x}".format(value) for value in selected_addresses],
                },
            },
        })
        require(exact_statistics["summary"]["matched_transaction_count"] == exact_expected and
                exact_statistics["summary"]["matched_read_count"] == 0 and
                exact_statistics["summary"]["matched_write_count"] == exact_expected and
                exact_statistics["summary"]["full_scan_count"] == 1,
                "AXI direction/ID/exact-address AND statistics mismatch")

        all_addresses = sorted({numeric_value(row["addr"]) for row in expected_records})
        range_begin = all_addresses[len(all_addresses) // 4]
        range_end = all_addresses[(3 * len(all_addresses)) // 4]
        range_expected = sum(
            range_begin <= numeric_value(row["addr"]) <= range_end
            for row in expected_records
        )
        range_statistics = r.query("axi.statistics", args={
            "name": "axi0",
            "filter": {"address": {"mode": "range",
                                    "begin": "32'h{:x}".format(range_begin),
                                    "end": "32'h{:x}".format(range_end)}},
        })
        require(range_statistics["summary"]["matched_transaction_count"] == range_expected and
                range_statistics["summary"]["full_scan_count"] == 1,
                "AXI range-address statistics mismatch")

        mask_value = all_addresses[0]
        mask = 0xff
        mask_expected = sum(
            (numeric_value(row["addr"]) & mask) == (mask_value & mask)
            for row in expected_log["RD"]
        )
        mask_statistics = r.query("axi.statistics", args={
            "name": "axi0",
            "filter": {"direction": "read",
                       "address": {"mode": "mask",
                                   "value": "32'h{:x}".format(mask_value),
                                   "mask": "32'h{:x}".format(mask)}},
        })
        require(mask_statistics["summary"]["matched_transaction_count"] == mask_expected and
                mask_statistics["summary"]["matched_read_count"] == mask_expected and
                mask_statistics["summary"]["matched_write_count"] == 0 and
                mask_statistics["summary"]["full_scan_count"] == 1,
                "AXI mask-address statistics mismatch")
        default_txn = r.query(
            "axi.query",
            args={"name": "axi0", "direction": "write", "query": {"index": 1}},
        )
        require(default_txn["summary"]["data_scope"] ==
                    "first_beat_each_with_first_transaction_full" and
                "beats" in default_txn["data"]["transaction"]["data"],
                "AXI default first transaction must include all beats")
        compact_txn = r.query(
            "axi.query",
            args={
                "name": "axi0",
                "direction": "write",
                "query": {"index": 1},
                "output": {"include_data": False},
            },
        )
        require(compact_txn["summary"]["data_scope"] == "none" and
                "beats" not in compact_txn["data"]["transaction"].get("data", {}),
                "AXI include_data=false transaction must omit beat data")
        detailed_txn = r.query(
            "axi.query",
            args={
                "name": "axi0",
                "direction": "write",
                "query": {"index": 1},
                "output": {"include_data": True},
            },
        )
        require(detailed_txn["summary"]["data_scope"] ==
                    "all_returned_transactions_full" and
                "beats" in detailed_txn["data"]["transaction"]["data"],
                "AXI include_data transaction must include beat data")

        axi_modes = [
            ("axi_default_negedge", make_axi_config(prefix, edge=None), "negedge", None),
            ("axi_dual", make_axi_config(prefix, edge="dual"), "dual", "before"),
            ("axi_pos_before", make_axi_config(prefix, edge="posedge", sample_point="before"), "posedge", "before"),
        ]
        for name, config, expected_edge, expected_sample_point in axi_modes:
            loaded = r.query("axi.config.load", args={"name": name, "config": config})
            require(loaded["data"]["config"]["edge"] == expected_edge, "AXI config edge mismatch for {}".format(name))
            if expected_sample_point is None:
                require("sample_point" not in loaded["data"]["config"],
                        "AXI negedge config should not expose sample_point for {}".format(name))
            else:
                require(loaded["data"]["config"]["sample_point"] == expected_sample_point,
                        "AXI config sample_point mismatch for {}".format(name))

        r.query("axi.transaction.cursor", args={"name": "axi0", "op": "begin", "direction": "all"})
        r.query("axi.transaction.cursor", args={"name": "axi0", "op": "next", "direction": "all"})
        tr = {"begin": "0ns", "end": "200ms"}
        pair_cold = r.query(
            "axi.request_response_pair",
            args={"name": "axi0", "time_range": tr, "line_limit": 10000},
        )
        require(pair_cold["summary"]["analysis_complete"] is True and
                pair_cold["summary"]["response_truncated"] is False and
                pair_cold["summary"]["total_count"] ==
                    pair_cold["summary"]["returned_count"] < 10000,
                "AXI percentile oracle requires the complete transaction set")
        oracle_latencies = sorted(
            duration_fs(txn["latency"])
            for txn in pair_cold["data"]["transactions"]
        )
        require(oracle_latencies, "AXI percentile oracle transaction set is empty")

        latency = r.query("axi.analysis", args={"name": "axi0", "analysis": "latency", "direction": "all"})
        percentile_values = {}
        for percentile, percent in (("p50", 50), ("p95", 95), ("p99", 99)):
            require(percentile in latency["summary"],
                    "AXI latency analysis missing {}".format(percentile))
            percentile_values[percentile] = duration_fs(latency["summary"][percentile])
            rank = (percent * len(oracle_latencies) + 99) // 100
            expected = oracle_latencies[rank - 1]
            require(percentile_values[percentile] == expected,
                    "AXI {} nearest-rank mismatch: expected {}, got {}".format(
                        percentile, expected, percentile_values[percentile]))
        require(latency["summary"]["samples"] == len(oracle_latencies),
                "AXI latency sample count does not match transaction oracle")
        require(latency["summary"]["full_scan_count"] == 1,
                "canonical AXI analysis must perform exactly one full FSDB scan")
        require({"direction", "latency", "address", "response"} <= set(latency["data"]["slowest"]),
                "AXI latency analysis missing slowest transaction anchor")
        slowest = latency["data"]["slowest"]
        slowest_latency = duration_fs(slowest["response"]["handshake_time"]) - duration_fs(slowest["address"]["handshake_time"])
        require(slowest_latency == duration_fs(latency["summary"]["max"]),
                "AXI slowest transaction latency must equal summary.max")
        require(slowest_latency == oracle_latencies[-1],
                "AXI slowest transaction must match the transaction oracle maximum")
        r.query("axi.analysis", args={"name": "axi0", "analysis": "osd", "direction": "all"})
        pending = r.query(
            "axi.analysis",
            args={"name": "axi0", "analysis": "pending", "direction": "all"},
        )
        require(pending["summary"]["total_count"] == 0 and
                pending["summary"]["returned_count"] == 0 and
                pending["data"]["pending_transactions"] == [],
                "completed AXI VIP run must not leave pending transactions")

        require(pair_cold["summary"]["total_count"] > 0, "AXI request_response_pair empty")
        require(all("beats" not in txn.get("data", {})
                    for txn in pair_cold["data"]["transactions"]),
                "AXI compact request_response_pair must omit beat payload")
        pair_cache = r.query("axi.request_response_pair", args={"name": "axi0", "time_range": tr, "line_limit": 20})
        require(pair_cache["summary"]["total_count"] > 0, "AXI cached request_response_pair empty")
        lat = r.query("axi.latency_outlier", args={"name": "axi0", "time_range": tr, "line_limit": 5})
        require(lat["summary"]["returned_count"] ==
                len(lat["data"]["outliers"]) > 0,
                "AXI latency_outlier empty")
        require(all("beats" not in txn.get("data", {})
                    for txn in lat["data"]["outliers"]),
                "AXI compact latency_outlier must omit beat payload")
        osd = r.query("axi.outstanding_timeline", args={"name": "axi0", "time_range": tr, "line_limit": 20})
        require(osd["summary"]["sample_count"] > 0, "AXI outstanding_timeline empty")
        stall = r.query("axi.channel_stall", args={"name": "axi0", "channel": "r", "time_range": tr, "rules": {"max_wait_cycles": 2}, "line_limit": 1000000})
        require(stall["summary"]["sample_count"] > 0, "AXI channel_stall did not sample")

        require_axi_delay_matrix(sim_log, expected_count,
                                 min_random_delay, max_random_delay)
        handshake_oracle = parse_axi_handshake_oracle(handshake_oracle_path)
        require_axi_handshake_queries(r, handshake_oracle)
        export_dir = tempfile.mkdtemp(prefix="xdebug_axi_export_")
        export_prefix = os.path.join(export_dir, "axi0_full")
        exported = r.query(
            "axi.export",
            args={
                "name": "axi0",
                "time_range": tr,
                "output": {"path": export_prefix, "file_format": "tsv"},
            },
            timeout=240,
        )
        compare_axi_export_to_log(exported, expected_log, handshake_oracle,
                                  expected_count, num_ids, transactions_per_id)
        require(exported["summary"]["full_scan_count"] == 1,
                "analysis/pair/timeline/outlier/export workflow triggered an extra AXI scan")

        windowed = r.query(
            "axi.export",
            args={
                "name": "axi0",
                "time_range": {"begin": "1us", "end": "200ms"},
                "output": {"path": os.path.join(export_dir, "axi0_windowed"), "file_format": "tsv"},
            },
            timeout=240,
        )
        require(windowed["summary"]["write_count"] <= exported["summary"]["write_count"], "windowed write count exceeds full export")
        require(windowed["summary"]["read_count"] <= exported["summary"]["read_count"], "windowed read count exceeds full export")
        with open(cache_probe, "r", encoding="utf-8") as probe_fh:
            cache_rows = [json.loads(line) for line in probe_fh if line.strip()]
        axi_rows = [row for row in cache_rows if row.get("protocol") == "axi"]
        require(axi_rows and axi_rows[-1]["scanner_invocations"] == 1,
                "AXI repository workflow must perform exactly one FSDB scan")
        require(sum(row.get("event") == "build" for row in axi_rows) == 1,
                "AXI repository must publish exactly one canonical build")
        require(sum(row.get("event") == "index_build" for row in axi_rows) >= 3,
                "AXI address, ID, and handshake lazy indexes were not all built")

        if expected_count <= 32:
            lru_probe_dir = tempfile.mkdtemp(prefix="xdebug_axi_lru_probe_")
            lru_probe = os.path.join(lru_probe_dir, "analysis-probe.jsonl")
            lru = AiRunner(xdebug, fsdb, "axi_soft_lru")
            lru.env["XDEBUG_ANALYSIS_CACHE_MAX_BYTES"] = "1"
            lru.env["XDEBUG_ANALYSIS_CACHE_HARD_MAX_BYTES"] = "2147483648"
            lru.env["XDEBUG_TEST_ANALYSIS_PROBE_PATH"] = lru_probe
            try:
                lru.open()
                lru.query(
                    "axi.config.load",
                    args={"name": "axi_before",
                          "config": make_axi_config(
                              prefix, sample_point="before")},
                )
                lru.query(
                    "axi.config.load",
                    args={"name": "axi_after",
                          "config": make_axi_config(
                              prefix, sample_point="after")},
                )
                started = lru.query(
                    "axi.transaction.cursor",
                    args={"name": "axi_before", "op": "begin",
                          "direction": "all"},
                )
                advanced = lru.query(
                    "axi.transaction.cursor",
                    args={"name": "axi_before", "op": "next",
                          "direction": "all"},
                )
                require(started["summary"]["index"] == 1 and
                        advanced["summary"]["index"] == 2,
                        "AXI LRU cursor setup did not reach position 2")
                lru.query(
                    "axi.query",
                    args={"name": "axi_after", "direction": "write"},
                )
                resumed = lru.query(
                    "axi.transaction.cursor",
                    args={"name": "axi_before", "op": "next",
                          "direction": "all"},
                )
                require(resumed["summary"]["found"] is True and
                        resumed["summary"]["index"] == 3,
                        "AXI generation cursor did not resume after soft LRU rebuild")
                with open(lru_probe, "r", encoding="utf-8") as probe_fh:
                    lru_rows = [json.loads(line) for line in probe_fh if line.strip()]
                lru_axi_rows = [row for row in lru_rows
                                if row.get("protocol") == "axi"]
                require(lru_axi_rows[-1]["scanner_invocations"] == 3 and
                        lru_axi_rows[-1]["evictions"] >= 2 and
                        sum(row.get("event") == "scan"
                            for row in lru_axi_rows) == 3,
                        "AXI soft LRU must rescan only after eviction")
            finally:
                lru.cleanup()
                shutil.rmtree(lru_probe_dir, ignore_errors=True)

        limited = AiRunner(xdebug, fsdb, "axi_hard_limit")
        limited.env["XDEBUG_ANALYSIS_CACHE_MAX_BYTES"] = "1"
        limited.env["XDEBUG_ANALYSIS_CACHE_HARD_MAX_BYTES"] = "1"
        try:
            limited.open()
            limited.query(
                "axi.config.load",
                args={"name": "axi0", "config": make_axi_config(prefix)},
            )
            rejected = limited.query(
                "axi.query",
                args={"name": "axi0", "direction": "write"},
                expect_ok=False,
            )
            cache_error = rejected.get("error", {})
            require(cache_error.get("code") == "ANALYSIS_MEMORY_LIMIT_EXCEEDED" and
                    cache_error.get("recoverable") is True and
                    cache_error.get("hard_max_bytes") == 1 and
                    cache_error.get("protocol") == "axi" and
                    len(cache_error.get("next_actions", [])) == 2,
                    "AXI hard-limit error contract mismatch: {}".format(cache_error))
        finally:
            limited.cleanup()
        return r.rows
    finally:
        r.cleanup()


def print_rows(rows):
    print("\n=== xdebug waveform performance ===")
    print("{:<8} {:<32} {:>4} {:>5} {:>10} {:>10}".format("wave", "action", "rc", "ok", "wall_ms", "tool_ms"))
    for wave, action, rc, ok, wall_ms, tool_ms in rows:
        print("{:<8} {:<32} {:>4} {:>5} {:>10} {:>10}".format(wave, action, rc, str(ok), wall_ms, str(tool_ms)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--xdebug", default=os.path.join(REPO_ROOT, "tools", "xdebug"))
    parser.add_argument("--fsdb", default=NONAXI_FSDB)
    parser.add_argument("--axi-fsdb", default=AXI_FSDB)
    parser.add_argument("--axi-sim-log", default=AXI_SIM_LOG)
    parser.add_argument("--axi-handshake-oracle", default=AXI_HANDSHAKE_ORACLE)
    parser.add_argument("--axi-expected-count", type=int, default=3200)
    parser.add_argument("--axi-num-ids", type=int, default=16)
    parser.add_argument("--axi-transactions-per-id", type=int, default=200)
    parser.add_argument("--axi-min-random-delay", type=int, default=50)
    parser.add_argument("--axi-max-random-delay", type=int, default=100)
    parser.add_argument("--mode", choices=["all", "nonaxi", "axi"], default="all")
    args = parser.parse_args()

    rows = []
    if args.mode in ("all", "nonaxi"):
        rows.extend(run_nonaxi(os.path.abspath(args.xdebug), os.path.abspath(args.fsdb)))
    if args.mode in ("all", "axi"):
        rows.extend(run_axi(
            os.path.abspath(args.xdebug), os.path.abspath(args.axi_fsdb),
            os.path.abspath(args.axi_sim_log),
            os.path.abspath(args.axi_handshake_oracle),
            args.axi_expected_count, args.axi_num_ids,
            args.axi_transactions_per_id,
            args.axi_min_random_delay, args.axi_max_random_delay))
    print_rows(rows)
    print("\nPASS: xdebug complex waveform validation completed")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("FAIL: {}".format(e), file=sys.stderr)
        sys.exit(1)
