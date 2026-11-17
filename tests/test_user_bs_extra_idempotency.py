"""Проверки receipt изолированы: временный import stub не влияет на другие тесты."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECKS = ROOT / "tests" / "_bs_extra_receipt_checks.py"


@pytest.mark.parametrize(
    "check",
    [
        "test_same_operation_id_increments_bs_extra_once",
        "test_different_operation_ids_increment_bs_extra_independently",
        "test_payload_accepts_uuid_operation_id",
    ],
)
def test_isolated_bs_extra_receipt(check):
    subprocess.run([sys.executable, "-m", "pytest", f"{CHECKS}::{check}", "-q"], cwd=ROOT, check=True)
