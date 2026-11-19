"""Реальный wire-контракт панели: gRPC/protobuf и REST TLS с большой конфигурацией."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("scenario", ["grpc", "rest"])
def test_real_dependency_contract(scenario):
    """Реальный wire-контракт панели: gRPC/protobuf и REST TLS с большой конфигурацией."""
    subprocess.run([sys.executable, str(Path(__file__).with_name("_dependency_probe.py")), scenario], check=True)
