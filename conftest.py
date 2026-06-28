import os
import sys

# Ensure the repo root (this dir) is importable so `import engine` works
# regardless of pytest's rootdir/import-mode.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
