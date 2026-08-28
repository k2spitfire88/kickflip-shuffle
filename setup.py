"""py2app build config for Kickflip Shuffle — unsigned macOS .app (beta 0.9.1).

Build:
    .venv/bin/python setup.py py2app
Output:
    dist/Kickflip Shuffle.app   (~300 MB — bundles FluidR3_GM.sf2)

Unsigned: first launch on another Mac needs right-click -> Open (Gatekeeper).
Requires the 148 MB assets/soundfonts/FluidR3_GM.sf2 to be present at build time
and the Homebrew libfluidsynth dylib (see FLUIDSYNTH_DYLIB below).
"""
from pathlib import Path

from setuptools import setup

ROOT = Path(__file__).resolve().parent

# The native FluidSynth dylib py2app copies into Contents/Frameworks. app/_bootstrap
# monkeypatches ctypes.util.find_library so pyfluidsynth loads THIS bundled copy
# (not a system one) at runtime. py2app/macholib pulls its transitive dylib deps.
FLUIDSYNTH_DYLIB = "/opt/homebrew/lib/libfluidsynth.3.dylib"

DATA_FILES = [
    ("assets/soundfonts", ["assets/soundfonts/FluidR3_GM.sf2"]),
    ("assets/fonts", [str(p) for p in sorted((ROOT / "assets/fonts").glob("*.ttf"))]),
    ("assets/textures", ["assets/textures/grit.png"]),
    ("assets/art", ["assets/art/keyart.png"]),
]

OPTIONS = {
    "iconfile": "assets/icon/KickflipShuffle.icns",
    "plist": {
        "CFBundleName": "Kickflip Shuffle",
        "CFBundleDisplayName": "Kickflip Shuffle",
        "CFBundleIdentifier": "com.kickflipshuffle.app",
        "CFBundleShortVersionString": "0.9.1",
        "CFBundleVersion": "0.9.1",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
    },
    "packages": [
        "PySide6", "librosa", "numba", "llvmlite", "scipy", "numpy",
        "soundfile", "sounddevice", "engine", "app",
    ],
    "includes": ["fluidsynth", "mido"],
    "frameworks": [FLUIDSYNTH_DYLIB],
}

setup(
    name="Kickflip Shuffle",
    app=["main.py"],
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
