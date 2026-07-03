"""Phase 7 (testable slice) — the frozen-app fluidsynth dylib shim.

Validates the mechanism WITHOUT a real py2app build: the shim must force
`ctypes.util.find_library("fluidsynth")` to the BUNDLED dylib even on a machine
that has a system libfluidsynth, and must delegate every other name unchanged.
"""
import ctypes.util

import pytest

from app import _bootstrap


@pytest.fixture
def restore_find_library():
    orig = ctypes.util.find_library
    yield
    ctypes.util.find_library = orig


def _make_bundle(tmp_path, name="libfluidsynth.dylib"):
    d = tmp_path / "Frameworks"
    d.mkdir()
    (d / name).write_bytes(b"\x00")               # stub dylib
    return d


def test_shim_returns_bundled_path(tmp_path, restore_find_library):
    d = _make_bundle(tmp_path)
    assert _bootstrap.install_fluidsynth_shim(d) is True
    got = ctypes.util.find_library("fluidsynth")
    assert got == str(d / "libfluidsynth.dylib")


def test_shim_overrides_even_with_system_lib(tmp_path, restore_find_library):
    # Simulate a dev machine where the original resolver finds a SYSTEM copy.
    ctypes.util.find_library = lambda name: "/opt/homebrew/lib/libfluidsynth.dylib"
    d = _make_bundle(tmp_path, name="libfluidsynth.3.dylib")
    assert _bootstrap.install_fluidsynth_shim(d) is True
    assert ctypes.util.find_library("fluidsynth") == str(d / "libfluidsynth.3.dylib")


def test_shim_delegates_other_names(tmp_path, restore_find_library):
    sentinel = "/somewhere/libfoo.dylib"
    ctypes.util.find_library = lambda name: sentinel
    d = _make_bundle(tmp_path)
    _bootstrap.install_fluidsynth_shim(d)
    assert ctypes.util.find_library("foo") == sentinel      # non-fluidsynth passes through


def test_shim_absent_dylib_returns_false(tmp_path, restore_find_library):
    empty = tmp_path / "Frameworks"
    empty.mkdir()
    assert _bootstrap.install_fluidsynth_shim(empty) is False


def test_bootstrap_noop_when_not_frozen(monkeypatch, restore_find_library):
    orig = ctypes.util.find_library
    monkeypatch.delattr("sys.frozen", raising=False)
    _bootstrap.bootstrap()                        # not frozen -> no patch
    assert ctypes.util.find_library is orig


def test_bootstrap_runs_when_frozen(monkeypatch, tmp_path, restore_find_library):
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr(_bootstrap, "_bundled_frameworks_dir",
                        lambda: _make_bundle(tmp_path))
    _bootstrap.bootstrap()
    assert ctypes.util.find_library("fluidsynth") == str(
        tmp_path / "Frameworks" / "libfluidsynth.dylib")
