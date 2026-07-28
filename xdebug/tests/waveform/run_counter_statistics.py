#!/usr/bin/env python3
import argparse
import os
import sys

from run_complex_wave import AiRunner, NONAXI_FSDB, REPO_ROOT, require


def run_counter_statistics(xdebug, fsdb):
    r = AiRunner(xdebug, fsdb, "counter_stats")
    try:
        r.open()

        stats = r.query("signal.statistics", args={
            "signal": "ai_complex_top.counter_inc",
            "clock": "ai_complex_top.clk",
            "time_range": {"begin": "55ns", "end": "95ns"},
            "line_limit": 1000,
        })
        for key in ("first", "final", "min", "max"):
            value = stats["data"][key]
            require(isinstance(value, dict) and value["value"].startswith("8'h"), "signal.statistics %s is not a canonical 8-bit hex value object" % key)
            require(value["known"] is True and value["width"] == 8, "signal.statistics %s width/known mismatch" % key)

        direct = r.query("counter.statistics", args={
            "clock": "ai_complex_top.clk",
            "edge": "posedge",
            "time_range": {"begin": "55ns", "end": "95ns"},
            "vld": "ai_complex_top.rst_n",
            "cnt": "ai_complex_top.counter_inc",
        })
        require(direct["summary"]["valid_count"] >= 4, "counter.statistics valid_count too small")
        require("truncated" not in direct.get("meta", {}),
                "counter.statistics must omit default meta.truncated=false")
        require(direct["summary"]["min_value"] == "0", "counter.statistics min mismatch")
        require(direct["summary"]["max_value"] == "4", "counter.statistics max mismatch")
        require(direct["data"]["min_count"] == 1 and direct["data"]["max_count"] == 1, "counter.statistics min/max count mismatch")
        require("ns" in direct["data"]["min_first_time"], "counter.statistics missing min_first_time")

        limited = r.query("counter.statistics", args={
            "clock": "ai_complex_top.clk",
            "edge": "posedge",
            "time_range": {"begin": "55ns", "end": "95ns"},
            "vld": "ai_complex_top.rst_n",
            "cnt": "ai_complex_top.counter_inc",
            "line_limit": 1,
        })
        require(limited["summary"]["valid_count"] == direct["summary"]["valid_count"],
                "counter.statistics line_limit must not reduce analyzed samples")
        require(limited["summary"]["analysis_complete"] is True,
                "counter.statistics line_limit must only truncate response evidence")
        require(limited["summary"]["returned_evidence_count"] == 1 and
                limited["summary"]["response_truncated"] is True,
                "counter.statistics limited evidence contract mismatch")

        budgeted = r.query("counter.statistics", args={
            "clock": "ai_complex_top.clk",
            "edge": "posedge",
            "time_range": {"begin": "55ns", "end": "95ns"},
            "vld": "ai_complex_top.rst_n",
            "cnt": "ai_complex_top.counter_inc",
            "max_samples": 2,
        })
        require(budgeted["summary"]["analysis_complete"] is False,
                "counter.statistics max_samples must report incomplete analysis")

        expr = r.query("counter.statistics", args={
            "clock": "ai_complex_top.clk",
            "edge": "posedge",
            "time_range": {"begin": "55ns", "end": "95ns"},
            "vld": {
                "expr": "rst",
                "signals": {
                    "rst": "ai_complex_top.rst_n",
                },
            },
            "cnt": "ai_complex_top.counter_inc",
        })
        require(expr["summary"]["valid_count"] == direct["summary"]["valid_count"], "expression vld valid_count mismatch")
        require(expr["summary"]["average_value"] == "2", "expression vld average mismatch")

        concat = r.query("counter.statistics", args={
            "clock": "ai_complex_top.clk",
            "edge": "posedge",
            "time_range": {"begin": "55ns", "end": "95ns"},
            "vld": "ai_complex_top.rst_n",
            "cnt": "{ai_complex_top.sig_a,ai_complex_top.counter_inc}",
        })
        require(int(concat["summary"]["max_value"]) > 255, "concat counter max did not include high bits")

        r.query("cursor.set", args={"name": "cnt_begin", "time": "55ns"})
        r.query("cursor.set", args={"name": "cnt_end", "time": "95ns"})
        cursor = r.query("counter.statistics", args={
            "clock": "ai_complex_top.clk",
            "edge": "posedge",
            "time_range": {"begin": "@cnt_begin", "end": "@cnt_end"},
            "vld": "ai_complex_top.rst_n",
            "cnt": "ai_complex_top.counter_inc",
        })
        require(cursor["summary"]["min_value"] == direct["summary"]["min_value"], "cursor window min mismatch")
        require(cursor["summary"]["max_value"] == direct["summary"]["max_value"], "cursor window max mismatch")

        r.query("counter.statistics", args={
            "clock": "ai_complex_top.clk",
            "edge": "posedge",
            "time_range": {"begin": "55ns", "end": "95ns"},
            "vld": {"expr": "missing", "signals": {"other": "ai_complex_top.rst_n"}},
            "cnt": "ai_complex_top.counter_inc",
        }, expect_ok=False)
        r.query("counter.statistics", args={
            "clock": "ai_complex_top.clk",
            "edge": "posedge",
            "time_range": {"begin": "55ns", "end": "95ns"},
            "vld": "ai_complex_top.rst_n",
            "cnt": "{ai_complex_top.counter_inc,'b0}",
        }, expect_ok=False)
        r.query("counter.statistics", args={
            "clock": "ai_complex_top.clk",
            "edge": "posedge",
            "time_range": {"begin": "55ns", "end": "95ns"},
            "vld": "ai_complex_top.rst_n",
            "cnt": "{ai_complex_top.sig_a,ai_complex_top.sig_a,ai_complex_top.sig_a,ai_complex_top.sig_a,ai_complex_top.sig_a,ai_complex_top.sig_a,ai_complex_top.sig_a,ai_complex_top.sig_a,ai_complex_top.sig_a}",
        }, expect_ok=False)

        return r.rows
    finally:
        r.cleanup()


def print_rows(rows):
    print("\ncase,action,rc,ok,elapsed_ms,meta_elapsed_ms")
    for row in rows:
        print("{},{},{},{},{},{}".format(*row))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--xdebug", default=os.path.join(REPO_ROOT, "tools", "xdebug"))
    parser.add_argument("--fsdb", default=NONAXI_FSDB)
    args = parser.parse_args()

    rows = run_counter_statistics(os.path.abspath(args.xdebug), os.path.abspath(args.fsdb))
    print_rows(rows)
    print("\nPASS: xdebug counter.statistics validation completed")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("FAIL: {}".format(e), file=sys.stderr)
        sys.exit(1)
