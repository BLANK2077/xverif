"""pytest fixtures for xsva tests."""

import json
import sys
from pathlib import Path

import pytest

# Ensure xsva package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def golden_dir():
    """Path to the golden_ir test data directory."""
    return Path(__file__).parent / "golden_ir"


def pytest_generate_tests(metafunc):
    """Parameterize golden IR tests from directory structure."""
    if "golden_case" in metafunc.fixturenames:
        golden_dir_path = Path(__file__).parent / "golden_ir"
        cases = []
        for entry in sorted(golden_dir_path.iterdir()):
            if entry.is_dir() and (entry / "input.sva").exists():
                cases.append(entry.name)
        metafunc.parametrize("golden_case", cases)


@pytest.fixture
def run_golden_case(golden_dir, golden_case):
    """Run a golden test case: parse input.sva → compare with golden JSON files."""
    case_dir = golden_dir / golden_case
    input_sva = (case_dir / "input.sva").read_text(encoding="utf-8")

    from xsva.parser.scanner import Scanner
    from xsva.ir.diagnostics import DiagnosticBag
    from xsva.parser.property_parser import PropertyParser
    from xsva.lower.surface_to_sequence import lower_surface_to_sequence
    from xsva.lower.sequence_to_timeline import lower_sequence_to_timeline

    diag = DiagnosticBag()
    scanner = Scanner(input_sva, file=str(case_dir / "input.sva"))
    parser = PropertyParser(scanner, diag)
    results = parser.parse_file()

    assert len(results) >= 1, f"No properties found in {golden_case}"

    surface = results[0]
    seq_ir = lower_surface_to_sequence(surface, diag)
    timeline = lower_sequence_to_timeline(seq_ir, surface_ir=surface, diag=diag)

    return surface, seq_ir, timeline, diag, case_dir
