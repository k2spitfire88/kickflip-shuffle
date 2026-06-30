import os
import sys

# Ensure the repo root (this dir) is importable so `import engine` works
# regardless of pytest's rootdir/import-mode.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: real-librosa pipeline tests (slower than the unit suite)")
    config.addinivalue_line(
        "markers", "audio: tests that open a real audio output device")
