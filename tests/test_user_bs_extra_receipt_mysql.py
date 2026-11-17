"""Проверки receipt изолированы: временный import stub не влияет на другие тесты."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECKS = ROOT / "tests" / "_bs_extra_receipt_checks.py"


@pytest.mark.skipif(not os.environ.get("TEST_MYSQL_DSN"), reason="TEST_MYSQL_DSN is required")
@pytest.mark.parametrize(
    "check",
    [
        "test_distinct_concurrent_receipts_do_not_deadlock",
        "test_repeat_after_older_snapshot_returns_committed_receipt",
    ],
)
def test_isolated_mysql_receipt(check):
    subprocess.run([sys.executable, "-m", "pytest", f"{CHECKS}::{check}", "-q"], cwd=ROOT, check=True)
