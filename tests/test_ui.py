"""Phase 5a-i UI tests — pytest-qt, headless (QT_QPA_PLATFORM=offscreen via
conftest). Playback is monkeypatched so no audio device/soundfont is touched;
the engine/export path runs for real."""
import numpy as np
import mido
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog

import engine
from app.controller import Controller
from app.ui import theme
from app.ui.generate_view import GenerateView
from app.ui.main_window import MainWindow


class _FakePlayer:
    def __init__(self):
        self.calls = []

    def load(self, buf, sr):
        self.calls.append("load")

    def play(self):
        self.calls.append("play")

    def stop(self):
        self.calls.append("stop")


def _patch_playback(monkeypatch):
    from app import playback
    monkeypatch.setattr(playback, "render_events",
                        lambda events, **kw: np.ones((100, 2), dtype=np.float32))
    fp = _FakePlayer()
    monkeypatch.setattr(playback, "Player", lambda: fp)
    return fp


def _view(qtbot, controller=None):
    v = GenerateView(controller or Controller())
    qtbot.addWidget(v)
    return v


# ---------------------------------------------------------------------------
def test_profiles_populate(qtbot):
    v = _view(qtbot)
    profs = v._c.list_profiles()
    assert v.profiles.count() == len(profs)
    assert v.profiles.item(0).data(Qt.UserRole) == profs[0]["name"]


def test_select_profile_sets_spec_and_enables(qtbot):
    v = _view(qtbot)
    v.profiles.setCurrentRow(0)
    name = v._c.list_profiles()[0]["name"]
    assert v._c.spec["profile"] == name
    assert not v.empty_hint.isVisible()
    assert v.play_btn.isEnabled() and v.bpm.isEnabled()


def test_bpm_updates_tempo_preserving_sections(qtbot):
    v = _view(qtbot)
    v.profiles.setCurrentRow(0)
    n_sections = len(v._c.spec["sections"])
    v.bpm.setValue(200)                       # 200 > Qt default max 99
    assert v._c.spec["tempo"] == 200
    assert len(v._c.spec["sections"]) == n_sections   # arrangement preserved


def test_output_map_selection(qtbot):
    v = _view(qtbot)
    v.profiles.setCurrentRow(0)
    maps = [m[0] for m in v._c.list_output_maps()]
    assert v.map_combo.count() == len(maps)
    idx = next(i for i in range(v.map_combo.count())
               if v.map_combo.itemData(i) == "EZ_DRUMMER_3")
    v.map_combo.setCurrentIndex(idx)
    assert v._c.output_map == "EZ_DRUMMER_3"


def test_regenerate_changes_seed(qtbot):
    v = _view(qtbot)
    v.profiles.setCurrentRow(0)
    v._c.set_seed(1)
    v.regen_btn.click()
    assert v._c.seed is not None and v._c.seed != 1
    assert engine.build_song(v._c.spec, seed=v._c.seed)   # non-empty events


def test_play_and_stop(qtbot, monkeypatch):
    fp = _patch_playback(monkeypatch)
    v = _view(qtbot)
    v.profiles.setCurrentRow(0)
    v.play_btn.click()
    assert "load" in fp.calls and "play" in fp.calls
    v.stop_btn.click()
    assert "stop" in fp.calls


def test_export_writes_midi(qtbot, monkeypatch, tmp_path):
    out = str(tmp_path / "out.mid")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (out, "MIDI (*.mid)"))
    v = _view(qtbot)
    v.profiles.setCurrentRow(0)
    v.export_btn.click()
    assert (tmp_path / "out.mid").exists()
    mido.MidiFile(out)                         # re-readable


def test_theme_applies(qapp):
    qss = theme.apply(qapp)
    assert qss.strip()
    assert theme.asset_path("art", "keyart.png").exists()


def test_main_window_builds(qtbot):
    w = MainWindow(Controller())
    qtbot.addWidget(w)
    assert w.windowTitle() == "Kickflip Shuffle"
    assert isinstance(w.centralWidget(), GenerateView)
    assert w.statusBar() is not None


def test_main_module_imports_without_second_qapplication():
    from PySide6.QtWidgets import QApplication
    before = QApplication.instance()
    import main
    assert hasattr(main, "main")
    assert QApplication.instance() is before   # import created no new app


def test_empty_state_controls_disabled(qtbot):
    v = _view(qtbot)
    for w in (v.regen_btn, v.play_btn, v.export_btn, v.bpm, v.map_combo):
        assert not w.isEnabled()


def test_play_error_is_surfaced_not_raised(qtbot, monkeypatch):
    v = _view(qtbot)
    v.profiles.setCurrentRow(0)
    monkeypatch.setattr(v._c, "render_preview",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no sf2")))
    msgs = []
    v.status.connect(msgs.append)
    v.play_btn.click()                         # must not raise
    assert any("unavailable" in m for m in msgs)
