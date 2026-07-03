"""Prefs — a thin, injectable wrapper over QSettings for app preferences.

Holds recent files, the default export folder, last-used project dir, and the
theme. Construct with an explicit ``QSettings`` in tests (temp IniFormat file) so
the suite never touches the real macOS plist; production code uses the default
``QSettings()`` which reads the org/app names set in ``main.py``.
"""
from pathlib import Path

from PySide6.QtCore import QSettings

_RECENT_KEY = "recent_files"
_EXPORT_DIR_KEY = "export_dir"
_PROJECT_DIR_KEY = "last_project_dir"
_THEME_KEY = "theme"
_RECENT_CAP = 10
_DEFAULT_EXPORT_DIR = Path.home() / "Music" / "Kickflip Shuffle"


class Prefs:
    def __init__(self, qsettings=None):
        self._s = qsettings if qsettings is not None else QSettings()

    # ------------------------------------------------------------ recent
    def recent_files(self):
        """Most-recent-first list of existing project paths (missing ones are
        pruned on read)."""
        raw = self._s.value(_RECENT_KEY, []) or []
        if isinstance(raw, str):                       # QSettings may collapse a 1-list
            raw = [raw]
        out = [p for p in raw if Path(p).exists()]
        if out != list(raw):
            self._s.setValue(_RECENT_KEY, out)
        return out

    def add_recent(self, path):
        path = str(path)
        items = [p for p in self.recent_files() if p != path]
        items.insert(0, path)
        self._s.setValue(_RECENT_KEY, items[:_RECENT_CAP])

    # ------------------------------------------------------------ folders
    def export_dir(self):
        """Default export folder, created if absent."""
        raw = self._s.value(_EXPORT_DIR_KEY, None)
        d = Path(raw) if raw else _DEFAULT_EXPORT_DIR
        d.mkdir(parents=True, exist_ok=True)
        return d

    def set_export_dir(self, path):
        self._s.setValue(_EXPORT_DIR_KEY, str(path))

    def last_project_dir(self):
        raw = self._s.value(_PROJECT_DIR_KEY, None)
        return Path(raw) if raw else Path.home()

    def set_last_project_dir(self, path):
        self._s.setValue(_PROJECT_DIR_KEY, str(path))

    # ------------------------------------------------------------- theme
    def theme(self):
        t = self._s.value(_THEME_KEY, "dark")
        return t if t in ("dark", "light") else "dark"

    def set_theme(self, mode):
        if mode in ("dark", "light"):
            self._s.setValue(_THEME_KEY, mode)
