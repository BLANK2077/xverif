from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from skill_test_utils import assert_markdown_links


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills/xsimdebug"
SCRIPT = SKILL / "scripts/uvm_component_break.tcl"


def test_xsimdebug_metadata_links_and_scope() -> None:
    assert_markdown_links(SKILL)
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    metadata = (SKILL / "agents/openai.yaml").read_text(encoding="utf-8")
    assert "TODO" not in skill_text
    for term in (
        "VCS/simv", "Xcelium/Xrun", "终端 PTY", "Ctrl-C",
        "vcs-ucli.md", "xrun-tcl.md", "uvm_component_break.tcl",
        "tmux new-session", "tmux send-keys", "tmux capture-pane",
        "help <command>", "固定 sleep", "重新编译代价过高",
        "不允许再次编译", "已有仿真 log 已足以定位问题",
        "回看执行过哪些命令时第一选择是 key", "ucli.key", "xrun.key",
        "历史命令先看 key", "输出和错误再查看已有 log",
        "不是 PTY 的逐字节录像",
    ):
        assert term in skill_text
    description = skill_text.split("---", 2)[1]
    assert "定位 SystemVerilog/UVM 验证问题" in description
    assert "若已有仿真 log 已足以定位问题，则不使用本 skill" in description
    assert "先阅读已有仿真 log" in skill_text
    assert "本 skill 不是默认的日志分析入口" in skill_text
    assert "$xsimdebug" in metadata
    assert "先判断仿真 log 是否足以定位" in metadata


def test_references_cover_common_interactive_debug_workflow() -> None:
    vcs = (SKILL / "references/vcs-ucli.md").read_text(encoding="utf-8")
    xrun = (SKILL / "references/xrun-tcl.md").read_text(encoding="utf-8")
    for term in (
        "help stop", "help get", "stop -line", "stop -delete",
        "get this.value", "get i", "next -end", "run -line",
        "不指定 `-k` 也会", "自动生成 `ucli.key`",
        "只保存依次执行的 UCLI 命令", "tail -n 200",
        "不要为历史回溯专门追加 `-k` 或 `-l`",
    ):
        assert term in vcs
    for term in (
        "help stop", "help value", "stop -create -line", "stop -delete",
        "value hit_count", "value i", "run -return", "临时行断点",
        "不指定 `-k` 也会", "自动生成 `xrun.key`",
        "只保存依次执行的 Tcl 命令", "tail -n 200",
        "不要为历史回溯专门追加 `-k` 或 `-l`",
    ):
        assert term in xrun
    assert "-k /abs/path" not in vcs
    assert "-k /abs/path" not in xrun


def test_xrun_reference_uses_native_uvm_path_without_vcs_helper() -> None:
    text = (SKILL / "references/xrun-tcl.md").read_text(encoding="utf-8")
    for term in (
        "-linedebug", "-uvmlinedebug", "-enable_tpe", "-input /dev/null",
        "uvm_phase -stop_at build -end", "uvm_component -list",
        "$uvm:{uvm_test_top.worker_b}", "run -return", "Simulation interrupted",
    ):
        assert term in text
    assert "uvm_component_break.tcl" not in text


def test_bundled_tcl_loads_and_publishes_expected_api() -> None:
    tclsh = shutil.which("tclsh")
    assert tclsh is not None
    script_path = str(SCRIPT).replace("\\", "/")
    probe = f"""
if {{[catch {{source {{{script_path}}}}} message]}} {{
    puts stderr $message
    exit 1
}}
puts [join [lsort [info procs ::uvmbp::*]] \\n]
"""
    result = subprocess.run(
        [tclsh], input=probe, text=True, capture_output=True, check=True,
    )
    assert set(result.stdout.splitlines()) == {
        "::uvmbp::break_at",
        "::uvmbp::escape_component_name",
        "::uvmbp::get_member",
        "::uvmbp::last_result",
        "::uvmbp::object_id_from_breakpoint",
        "::uvmbp::resolve",
    }


def test_tcl_contract_uses_direct_uvm_tree_resolution() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for term in (
        "uvm_pkg::uvm_top.top_levels", "m_children", "get_member",
        "stop -line", "-object $object_expr", "-cond $condition",
        "UVMBP_BOUND", "UVMBP_VALUE", "run 0",
    ):
        assert term in text
    for removed in ("matching_glob", "scanned_hits", "max_hits", "run\n"):
        assert removed not in text


def test_tcl_resolves_path_sets_breakpoint_and_reads_member() -> None:
    tclsh = shutil.which("tclsh")
    assert tclsh is not None
    script_path = str(SCRIPT).replace("\\", "/")
    probe = f"""
set ::mock_values [dict create \\
    {{uvm_pkg::uvm_top.top_levels[0].m_name}} uvm_test_top \\
    {{uvm_pkg::uvm_top.top_levels[0].m_children[\"worker_b\"].m_name}} \\
        uvm_test_top.worker_b \\
    {{uvm_pkg::uvm_top.top_levels[0].m_children[\"worker_b\"].instance_value}} 200]
proc get {{path args}} {{
    if {{![dict exists $::mock_values $path]}} {{error "unknown object $path"}}
    return [dict get $::mock_values $path]
}}
proc stop {{args}} {{
    if {{[lindex $args 0] eq "-show"}} {{
        return {{7: -object_id {{TargetWorker @2}}}}
    }}
    set ::stop_args $args
    return 7
}}
source {{{script_path}}}
set resolved [::uvmbp::resolve uvm_test_top.worker_b]
set bp [::uvmbp::break_at uvm_test_top.worker_b worker.sv 24 {{hit_count == 3}}]
set member [::uvmbp::get_member uvm_test_top.worker_b instance_value decimal]
puts "RESOLVED=[dict get $resolved object_expr]"
puts "OBJECT_ID=[dict get $bp object_id]"
puts "STOP_ARGS=$::stop_args"
puts "VALUE=[dict get $member value]"
"""
    result = subprocess.run(
        [tclsh], input=probe, text=True, capture_output=True, check=True,
    )
    assert "RESOLVED=uvm_pkg::uvm_top.top_levels[0].m_children[\"worker_b\"]" in result.stdout
    assert "OBJECT_ID=TargetWorker @2" in result.stdout
    assert "-object {uvm_pkg::uvm_top.top_levels[0].m_children[\"worker_b\"]}" in result.stdout
    assert "-cond {hit_count == 3}" in result.stdout
    assert "VALUE=200" in result.stdout
