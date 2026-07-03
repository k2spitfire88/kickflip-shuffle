"""Phase 6a persistence + export tests — controller .ppd round-trip, Prefs over a
temp QSettings (never touches the real macOS plist), and the UI save/load/export
polish (pytest-qt offscreen; playback + `open -R` monkeypatched)."""
import json

import numpy as np
import pytest
from PySide6.QtCore import QSettings

import engine
from app.controller import Controller, PROJECT_VERSION
from app.ui.settings import Prefs
from app.ui.generate_view import GenerateView
from app.ui.main_window import MainWindow


def _temp_prefs(tmp_path):
    s = QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat)
    return Prefs(s)


# --------------------------------------------------------------- controller
def test_to_project_shape_and_requires_spec():
    c = Controller(seed=5)
    with pytest.raises(ValueError):
        c.to_project()
    c.song_from_profile("pop_punk")
    d = c.to_project(extra={"selected_section": 2, "theme": "light"})
    assert d["version"] == PROJECT_VERSION
    assert d["spec"]["profile"] == "pop_punk"
    assert d["seed"] == 5 and d["output_map"] == "GENERAL_MIDI"
    assert d["selected_section"] == 2 and d["theme"] == "light"


def test_save_load_roundtrip_restores_state(tmp_path):
    c = Controller(seed=11)
    c.set_output_map("EZ_DRUMMER_3")
    c.song_from_profile("barker")
    p = tmp_path / "song.ppd"
    c.save_project(p, extra={"selected_section": 1})

    c2 = Controller()
    data = c2.load_project(p)
    assert c2.spec["profile"] == "barker"
    assert c2.seed == 11
    assert c2.output_map == "EZ_DRUMMER_3"
    assert data["selected_section"] == 1
    assert data["warnings"] == []


def test_loaded_spec_is_deep_copied(tmp_path):
    c = Controller(seed=1)
    c.song_from_profile("pop_punk")
    p = tmp_path / "s.ppd"
    c.save_project(p)
    c2 = Controller()
    c2.load_project(p)
    c2.spec["sections"].append({"role": "verse", "bars": 99})
    # Re-reading the file must not see the post-load mutation.
    again = json.loads(p.read_text())
    assert all(s.get("bars") != 99 for s in again["spec"]["sections"])


def test_bad_version_raises_without_mutating(tmp_path):
    p = tmp_path / "bad.ppd"
    p.write_text(json.dumps({"version": 999, "spec": {"profile": "x"}}))
    c = Controller()
    c.song_from_profile("pop_punk")
    held = c.spec
    with pytest.raises(ValueError):
        c.load_project(p)
    assert c.spec is held                    # unchanged


def test_unknown_output_map_falls_back(tmp_path):
    c = Controller()
    c.song_from_profile("pop_punk")
    p = tmp_path / "m.ppd"
    d = c.to_project()
    d["output_map"] = "NONEXISTENT_MAP"
    p.write_text(json.dumps(d))
    c2 = Controller()
    out = c2.load_project(p)
    assert c2.output_map == "GENERAL_MIDI"
    assert out["warnings"] and "NONEXISTENT_MAP" in out["warnings"][0]


# -------------------------------------------------------------------- Prefs
def test_recent_add_dedup_cap_and_prune(tmp_path):
    prefs = _temp_prefs(tmp_path)
    files = []
    for i in range(12):
        f = tmp_path / f"p{i}.ppd"
        f.write_text("{}")
        files.append(str(f))
        prefs.add_recent(f)
    rec = prefs.recent_files()
    assert len(rec) == 10                    # capped
    assert rec[0] == files[-1]               # most-recent first
    prefs.add_recent(files[-1])              # dedup
    assert prefs.recent_files().count(files[-1]) == 1
    files[-1] and __import__("os").remove(files[-1])   # prune missing
    assert files[-1] not in prefs.recent_files()


def test_export_dir_default_created_and_theme_roundtrip(tmp_path):
    prefs = _temp_prefs(tmp_path)
    custom = tmp_path / "out"
    prefs.set_export_dir(custom)
    d = prefs.export_dir()
    assert d == custom and d.exists()
    assert prefs.theme() == "dark"           # default
    prefs.set_theme("light")
    assert prefs.theme() == "light"


# ---------------------------------------------------------------------- UI
def _patch_playback(monkeypatch):
    from app import playback
    monkeypatch.setattr(playback, "render_events",
                        lambda events, **kw: np.ones((100, 2), dtype=np.float32))


def test_export_writes_to_folder_and_dedups(qtbot, tmp_path, monkeypatch):
    _patch_playback(monkeypatch)
    prefs = _temp_prefs(tmp_path)
    prefs.set_export_dir(tmp_path / "midi")
    v = GenerateView(Controller(), prefs=prefs)
    qtbot.addWidget(v)
    v._c.song_from_profile("pop_punk")
    v.load_current_spec()
    v.export_btn.click()
    v.export_btn.click()
    mids = sorted((tmp_path / "midi").glob("*.mid"))
    assert [m.name for m in mids] == ["drums-2.mid", "drums.mid"]


def test_reveal_guarded(qtbot, tmp_path, monkeypatch):
    import subprocess
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd: calls.append(cmd))
    monkeypatch.setattr("sys.platform", "darwin")
    prefs = _temp_prefs(tmp_path)
    prefs.set_export_dir(tmp_path / "midi")
    v = GenerateView(Controller(), prefs=prefs)
    qtbot.addWidget(v)
    v._on_reveal()                           # no export yet -> reveal folder
    assert calls and calls[0][0] == "open"


def test_mainwindow_save_then_load_restores(qtbot, tmp_path):
    prefs = _temp_prefs(tmp_path)
    w = MainWindow(Controller(seed=3), prefs=prefs)
    qtbot.addWidget(w)
    w._c.song_from_profile("pop_punk")
    w.generate_view.load_current_spec()
    w.generate_view.timeline.list.setCurrentRow(2)
    p = tmp_path / "proj.ppd"
    w._write_project(str(p))
    assert p.exists()
    assert str(p) in prefs.recent_files()
    assert "proj" in w.windowTitle()

    w2 = MainWindow(Controller(), prefs=prefs)
    qtbot.addWidget(w2)
    w2._open(str(p))
    assert w2._c.spec["profile"] == "pop_punk"
    assert w2._c.seed == 3
    assert w2.generate_view.timeline.list.currentRow() == 2


def test_mainwindow_open_malformed_shows_error_no_crash(qtbot, tmp_path):
    prefs = _temp_prefs(tmp_path)
    bad = tmp_path / "bad.ppd"
    bad.write_text("{ not json")
    w = MainWindow(Controller(), prefs=prefs)
    qtbot.addWidget(w)
    w._open(str(bad))                        # must not raise
    assert "failed" in w.statusBar().currentMessage().lower()


def test_new_clears_project(qtbot, tmp_path):
    prefs = _temp_prefs(tmp_path)
    w = MainWindow(Controller(), prefs=prefs)
    qtbot.addWidget(w)
    w._c.song_from_profile("pop_punk")
    w.generate_view.load_current_spec()
    w._new()
    assert w._c.spec is None
    assert "Untitled" in w.windowTitle()
