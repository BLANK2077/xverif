import os
from pathlib import Path

from testinfra.xverif_test.fixtures import (
    FixtureOutput,
    FixtureRegistry,
    FixtureSpec,
    FixtureStore,
    _compatibility_identity,
)


ROOT = Path(__file__).resolve().parents[2]


def make_store(root: Path) -> tuple[FixtureStore, FixtureSpec]:
    source = root / "fixture"
    source.mkdir()
    (source / "input.sv").write_text("module top; endmodule\n", encoding="utf-8")
    spec = FixtureSpec(
        id="demo.fixture",
        source_dir="fixture",
        inputs=("*.sv",),
        extra_inputs=(),
        builder={
            "argv": [
                "python3",
                "-c",
                (
                    "import pathlib; "
                    "p=pathlib.Path(r'{resources}/out.txt'); "
                    "p.parent.mkdir(parents=True, exist_ok=True); "
                    "p.write_text('ok')"
                ),
            ]
        },
        outputs=(FixtureOutput("text", "out.txt", "file", 1),),
        tool_env=(),
        build_capabilities=(),
    )
    return FixtureStore(root, FixtureRegistry("xverif-fixture-registry.v1", (spec,))), spec


def test_fingerprint_uses_content_not_mtime(tmp_path: Path) -> None:
    store, spec = make_store(tmp_path)
    first, _ = store.fingerprint(spec)
    input_path = tmp_path / "fixture/input.sv"
    os.utime(input_path, None)
    second, _ = store.fingerprint(spec)
    assert second == first
    input_path.write_text("module changed; endmodule\n", encoding="utf-8")
    third, _ = store.fingerprint(spec)
    assert third != first


def test_prepare_publishes_and_reuses_fixture(tmp_path: Path) -> None:
    store, spec = make_store(tmp_path)
    first = store.prepare(spec.id)
    assert (first / "out.txt").read_text(encoding="utf-8") == "ok"
    second = store.prepare(spec.id)
    assert second == first
    assert store.resolve(spec.id) == first


def test_rebuild_atomically_switches_to_new_immutable_generation(tmp_path: Path) -> None:
    store, spec = make_store(tmp_path)
    first = store.prepare(spec.id)
    second = store.prepare(spec.id, rebuild=True)
    assert second != first
    assert (first / "out.txt").read_text(encoding="utf-8") == "ok"
    assert store.resolve(spec.id) == second


def test_tool_identity_uses_compatible_major_minor() -> None:
    assert _compatibility_identity("tools/verdi/V-2023.12-SP2") == "V-2023.12"
    assert _compatibility_identity("") == "unset"


def test_fingerprint_uses_effective_default_environment(tmp_path: Path, monkeypatch) -> None:
    store, spec = make_store(tmp_path)
    spec = FixtureSpec(**{**spec.__dict__, "builder": {
        **spec.builder, "default_env": {"VIP_ROOT": "{home}/vip"},
    }})
    first, _ = store.fingerprint(spec)
    monkeypatch.setenv("VIP_ROOT", "other-vip")
    second, _ = store.fingerprint(spec)
    assert second != first


def test_large_summary_fixture_fingerprints_generator_recipe_probe_and_tools() -> None:
    registry = FixtureRegistry.load(
        ROOT / "testinfra/fixtures.v1.yaml",
        ROOT / "testinfra/schemas/fixtures.v1.schema.json",
    )
    spec = registry.by_id("xcov.large_summary")
    store = FixtureStore(ROOT, registry)

    assert spec.inputs == (
        "Makefile", "generate_large_fixture.py", "probe_large_fixture.py",
    )
    assert spec.tool_env == ("VCS_HOME", "VERDI_HOME")
    assert spec.builder["argv"] == ["make", "fixture", "RUN_DIR={resources}"]
    assert spec.builder["timeout_sec"] == 3600
    assert spec.probes[0]["argv"] == [
        "python3", "{source}/probe_large_fixture.py",
        "--resources", "{resources}",
    ]
    source_names = {
        path.name for path in store._source_files(spec)  # private contract audit
    }
    assert source_names == {
        "Makefile", "generate_large_fixture.py", "probe_large_fixture.py",
    }
    fingerprint, tool_identity = store.fingerprint(spec)
    assert len(fingerprint) == 64
    assert set(tool_identity) == {"VCS_HOME", "VERDI_HOME"}


def test_design_hierarchy_fixture_preserves_validated_npi_experiment_recipe() -> None:
    registry = FixtureRegistry.load(
        ROOT / "testinfra/fixtures.v1.yaml",
        ROOT / "testinfra/schemas/fixtures.v1.schema.json",
    )
    spec = registry.by_id("xdebug.design_hierarchy")
    assert spec.source_dir == "xdebug/testdata/design/hierarchy_types"
    assert spec.inputs == ("hierarchy_types_fixture.sv",)
    assert spec.builder["argv"] == [
        "vcs",
        "-full64",
        "-sverilog",
        "-timescale=1ns/1ps",
        "-debug_access+all",
        "-kdb",
        "-lca",
        "{source}/hierarchy_types_fixture.sv",
        "-top",
        "hierarchy_types_top",
        "-o",
        "{resources}/simv",
    ]
    assert spec.outputs == (
        FixtureOutput("daidir", "simv.daidir", "dir", 1),
    )
    assert spec.tool_env == ("VERDI_HOME",)
