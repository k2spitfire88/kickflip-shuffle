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
    qtbot.waitUntil(lambda: "play" in fp.calls, timeout=3000)   # render is async
    assert "load" in fp.calls and "play" in fp.calls
    v.stop_btn.click()
    assert "stop" in fp.calls


def test_export_writes_midi(qtbot, monkeypatch, tmp_path):
    out = str(tmp_path / "out.mid")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (out, "MIDI (*.mid)"))
    v = _view(qtbot)
    v.profiles.setCurrentRow(0)
    v.export_as_btn.click()                    # Save-As path (getSaveFileName)
    assert (tmp_path / "out.mid").exists()
    mido.MidiFile(out)                         # re-readable


def test_theme_applies(qapp):
    qss = theme.apply(qapp)
    assert qss.strip()
    assert theme.asset_path("art", "keyart.png").exists()


def test_close_is_safe(qtbot):
    v = _view(qtbot)
    v.profiles.setCurrentRow(0)
    v.close()                                  # no active render thread -> no crash


def test_register_fonts_and_assets(qapp):
    fams = theme.register_fonts()        # offscreen returns [] but must not crash
    assert isinstance(fams, list)
    for fn in theme.FONT_FILES:
        assert theme.asset_path("fonts", fn).exists()
    assert theme.asset_path("textures", "grit.png").exists()
    assert theme.asset_path("wordmark.png").exists()


def test_main_window_builds(qtbot):
    w = MainWindow(Controller())
    qtbot.addWidget(w)
    assert w.windowTitle() == "Kickflip Shuffle — Untitled"
    assert isinstance(w.view, GenerateView)        # .view -> generate_view
    assert w.stack.count() == 3                     # Generate + Drop + Browser
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


def test_editor_appears_on_select(qtbot):
    v = _view(qtbot)
    assert v.editor_panel.isHidden()           # isVisible() needs a shown window
    v.profiles.setCurrentRow(0)
    assert not v.editor_panel.isHidden() and v.empty_hint.isHidden()


def test_timeline_add_remove_reorder(qtbot):
    v = _view(qtbot)
    v.profiles.setCurrentRow(0)
    n = len(v._c.spec["sections"])
    v.timeline._add()
    assert len(v._c.spec["sections"]) == n + 1
    first_role = v._c.spec["sections"][0].get("role")
    v.timeline.list.setCurrentRow(0)
    v.timeline._right()                        # swap sections 0 and 1
    assert v._c.spec["sections"][1].get("role") == first_role
    v.timeline.list.setCurrentRow(0)
    v.timeline._remove()
    assert len(v._c.spec["sections"]) == n


def test_section_editor_updates_spec(qtbot):
    v = _view(qtbot)
    v.profiles.setCurrentRow(0)
    v.section_editor.load(0)
    v.section_editor.bars.setValue(6)
    v.section_editor.crash.setChecked(True)
    assert v._c.spec["sections"][0]["bars"] == 6
    assert v._c.spec["sections"][0]["crash_in"] is True


def test_grid_edit_sets_and_clears_pattern(qtbot):
    from app.ui.editor_widgets import ROLES
    v = _view(qtbot)
    v.profiles.setCurrentRow(0)
    v.grid.load(0)
    cow = ROLES.index("cowbell")               # no groove emits it -> off, deterministic
    v.grid.toggle(cow, 0)
    pats = v._c.spec["sections"][0]["patterns"][0]
    assert pats["cowbell"][0] == 100
    assert v._c.resolved_bar(0, 0)["cowbell"][0] == 100   # mirror reflects edit
    v.grid._reset()
    assert "patterns" not in v._c.spec["sections"][0]


def test_grid_override_survives_reorder(qtbot):
    from app.ui.editor_widgets import ROLES
    v = _view(qtbot)
    v.profiles.setCurrentRow(0)
    v.grid.load(0)
    v.grid.toggle(ROLES.index("cowbell"), 4)
    v.timeline.list.setCurrentRow(0)
    v.timeline._right()                        # move section 0 -> index 1
    assert v._c.spec["sections"][1]["patterns"][0]["cowbell"][4] == 100


def test_play_error_is_surfaced_not_raised(qtbot, monkeypatch):
    v = _view(qtbot)
    v.profiles.setCurrentRow(0)
    monkeypatch.setattr(v._c, "render_preview",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no sf2")))
    msgs = []
    v.status.connect(msgs.append)
    v.play_btn.click()                         # must not raise (render is async)
    qtbot.waitUntil(lambda: any("unavailable" in m for m in msgs), timeout=3000)
