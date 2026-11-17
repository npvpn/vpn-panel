"""Mypy diagnostics filtering keeps errors while dropping unstable notes."""

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent


def test_filter_mypy_notes_keeps_error_without_error_code():
    diagnostics = "\n".join(
        (
            "example.py:1: note: By default the bodies of untyped functions are not checked",
            "example.py:2: error: No parent module -- cannot perform relative import",
            "Found 1 error in 1 file (errors prevented further checking)",
            "",
        )
    )

    result = subprocess.run(
        [sys.executable, "scripts/filter_mypy_notes.py"],
        cwd=_ROOT,
        input=diagnostics,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "note:" not in result.stdout
    assert "error: No parent module -- cannot perform relative import" in result.stdout
    assert "Found 1 error in 1 file" in result.stdout
