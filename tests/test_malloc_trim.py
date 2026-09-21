"""Возврат освобождённой памяти ядру (NPVPN-2120)."""

import ctypes

import pytest

from app.utils import malloc_trim as module


@pytest.fixture(autouse=True)
def _reset_resolution():
    """Резолв libc кэшируется в модуле — сбрасываем его вокруг каждого теста."""
    module._resolved = False
    module._malloc_trim = None
    yield
    module._resolved = False
    module._malloc_trim = None


def test_trims_on_glibc():
    """На glibc (наш образ python:3.12-slim) вызов проходит и не падает."""
    assert module.trim_malloc() in (True, False)
    assert module._malloc_trim is not None


def test_returns_true_when_kernel_got_memory(monkeypatch):
    monkeypatch.setattr(module, "_resolved", True)
    monkeypatch.setattr(module, "_malloc_trim", lambda pad: 1)

    assert module.trim_malloc() is True


def test_returns_false_when_nothing_to_release(monkeypatch):
    monkeypatch.setattr(module, "_resolved", True)
    monkeypatch.setattr(module, "_malloc_trim", lambda pad: 0)

    assert module.trim_malloc() is False


def test_missing_libc_is_not_an_error(monkeypatch):
    """На musl malloc_trim отсутствует — это не повод ронять вызывающую джобу."""

    def _no_libc(_name):
        raise OSError("libc.so.6: cannot open shared object file")

    monkeypatch.setattr(ctypes, "CDLL", _no_libc)

    assert module.trim_malloc() is False


def test_missing_symbol_is_not_an_error(monkeypatch):
    class _LibcWithoutTrim:
        def __getattr__(self, name):
            raise AttributeError(name)

    monkeypatch.setattr(ctypes, "CDLL", lambda _name: _LibcWithoutTrim())

    assert module.trim_malloc() is False


def test_resolution_happens_once(monkeypatch):
    """Отрицательный результат тоже кэшируется: иначе каждая волна дёргала бы CDLL."""
    calls = []

    def _counting_cdll(name):
        calls.append(name)
        raise OSError("no libc")

    monkeypatch.setattr(ctypes, "CDLL", _counting_cdll)

    assert module.trim_malloc() is False
    assert module.trim_malloc() is False
    assert len(calls) == 1


def test_call_failure_is_swallowed(monkeypatch):
    def _boom(_pad):
        raise OSError("boom")

    monkeypatch.setattr(module, "_resolved", True)
    monkeypatch.setattr(module, "_malloc_trim", _boom)

    assert module.trim_malloc() is False
