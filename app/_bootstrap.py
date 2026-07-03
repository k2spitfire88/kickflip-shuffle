"""Frozen-app bootstrap fixups.

Import and call `bootstrap()` as the FIRST thing in `main()` — before anything
imports `fluidsynth` (which resolves its native dylib at import time).

The problem: `pyfluidsynth`'s module-level `find_libfluidsynth()` calls
`ctypes.util.find_library("fluidsynth")` FIRST. On a machine that has Homebrew's
libfluidsynth installed, that returns the SYSTEM dylib, so a bundled copy is never
used. Its `$HOMEBREW_PREFIX/lib` fallback is only reached when `find_library`
returns nothing — unreachable on a dev machine. (macOS SIP also strips
`DYLD_LIBRARY_PATH` from `find_library`, so that route is unreliable.)

The fix: in a frozen bundle, monkeypatch `ctypes.util.find_library` so a request
for the fluidsynth lib names returns the BUNDLED absolute path, delegating every
other name to the original resolver. This forces the bundled copy regardless of a
system install.
"""
import ctypes.util
import sys
from pathlib import Path

_FLUIDSYNTH_NAMES = frozenset({
    "fluidsynth", "fluidsynth-3", "libfluidsynth",
    "libfluidsynth-3", "libfluidsynth-2", "libfluidsynth-1",
})


def resource_root():
    """Directory that contains `assets/`. In a py2app bundle this is
    `<bundle>/Contents/Resources`; on the dev box it is the repo root. Used so
    `__file__`-relative asset lookups keep working once the code is zipped into the
    bundle away from the assets tree."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent / "Resources"
    return Path(__file__).resolve().parents[1]     # app/.. == repo root


def _bundled_frameworks_dir():
    """Where py2app stages bundled dylibs: `<bundle>/Contents/Frameworks`.
    `sys.executable` in a bundle is `<bundle>/Contents/MacOS/<exe>`."""
    return Path(sys.executable).resolve().parent.parent / "Frameworks"


def _find_bundled_fluidsynth(dylib_dir):
    dylib_dir = Path(dylib_dir)
    for name in ("libfluidsynth.dylib", "libfluidsynth.3.dylib"):
        cand = dylib_dir / name
        if cand.exists():
            return str(cand)
    matches = sorted(dylib_dir.glob("libfluidsynth*.dylib"))
    return str(matches[0]) if matches else None


def install_fluidsynth_shim(dylib_dir=None):
    """Force `ctypes.util.find_library` to resolve fluidsynth to the bundled dylib.

    Returns True if the shim was installed (a bundled dylib was found), else False.
    `dylib_dir` defaults to the bundle's Frameworks dir; pass an explicit dir for
    testing. Idempotent enough for a single frozen launch."""
    target = _find_bundled_fluidsynth(dylib_dir or _bundled_frameworks_dir())
    if target is None:
        return False
    _orig = ctypes.util.find_library

    def _patched(name):
        if name in _FLUIDSYNTH_NAMES:
            return target
        return _orig(name)

    _patched._kickflip_orig = _orig      # expose for teardown/introspection
    ctypes.util.find_library = _patched
    return True


def bootstrap():
    """Run frozen-app fixups. No-op when not frozen (dev box / tests)."""
    if not getattr(sys, "frozen", False):
        return
    install_fluidsynth_shim()
