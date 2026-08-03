from xloc.mapfile import load_map


def test_uvm_report_server_compresses_only_source_paths(xverif_fixture) -> None:
    out = xverif_fixture("xloc.uvm") / "out"
    log = (out / "sim.log").read_text(encoding="utf-8")
    entries = load_map(str(out / "sim.log.xloc.jsonl"))

    assert "UVM_ERROR L_00000001(18)" in log
    assert "UVM_ERROR L_00000001(19)" in log
    assert "UVM_ERROR L_00000002(3)" in log
    assert "UVM_ERROR L_00000002(4)" in log
    assert len(entries) == 2
    assert all(set(entry) == {"loc_id", "file"} for entry in entries.values())
    assert "[FILE_OPEN] cannot open config file" in log
    assert "[PKT_MISMATCH] expected=8'hFF actual=8'hFE" in log
    assert "UVM_WARNING L_" in log
    assert "V C S   S i m u l a t i o n   R e p o r t" in log
