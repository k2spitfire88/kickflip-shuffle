"""Shared test fixtures.

`_isolate_qsettings` redirects ALL QSettings I/O to a temp directory for the whole
session so no test — even one that constructs a bare `Prefs()`/`QSettings()` (e.g.
a `GenerateView`/`MainWindow` built without an injected Prefs) — can read or write
the real macOS plist / user preferences.
"""
import pytest
from PySide6.QtCore import QSettings, QCoreApplication


@pytest.fixture(autouse=True, scope="session")
def _isolate_qsettings(tmp_path_factory):
    d = str(tmp_path_factory.mktemp("qsettings"))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, d)
    QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope, d)
    QCoreApplication.setOrganizationName("KickflipShuffleTest")
    QCoreApplication.setApplicationName("KickflipShuffleTest")
    yield
