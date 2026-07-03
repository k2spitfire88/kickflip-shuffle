"""Phase 6b undo/redo tests — controller spec-snapshot stack (headless) + the
Edit-menu wiring (pytest-qt offscreen)."""
import engine
from app.controller import Controller
from app.ui.main_window import MainWindow


# ------------------------------------------------------------- controller
def _c():
    c = Controller(seed=1)
    c.song_from_profile("pop_punk")
    return c


def test_edit_undo_redo_roundtrip():
    c = _c()
    assert not c.can_undo() and not c.can_redo()   # fresh load reset history
    c.update_section(0, bars=13)
    assert c.can_undo()
    assert c.spec["sections"][0]["bars"] == 13
    assert c.undo()
    assert c.spec["sections"][0]["bars"] != 13
    assert c.can_redo()
    assert c.redo()
    assert c.spec["sections"][0]["bars"] == 13


def test_new_edit_clears_redo():
    c = _c()
    c.update_section(0, bars=13)
    c.undo()
    assert c.can_redo()
    c.update_section(0, bars=7)                     # new branch
    assert not c.can_redo()


def test_set_tempo_tracked_and_noop_guard():
    c = _c()
    before = len(c._undo)
    c.set_tempo(c.spec["tempo"])                    # unchanged -> no snapshot
    assert len(c._undo) == before
    c.set_tempo(200)
    assert len(c._undo) == before + 1
    assert c.spec["tempo"] == 200.0
    c.undo()
    assert c.spec["tempo"] != 200.0


def test_load_boundaries_reset_history():
    c = _c()
    c.update_section(0, bars=9)
    assert c.can_undo()
    c.song_from_profile("barker")                   # new document
    assert not c.can_undo() and not c.can_redo()


def test_clear_bar_pattern_noop_does_not_snapshot():
    c = _c()
    before = len(c._undo)
    c.clear_bar_pattern(0, 0)                        # nothing to clear
    assert len(c._undo) == before


def test_empty_update_section_does_not_snapshot():
    c = _c()
    before = len(c._undo)
    c.update_section(0)                             # no fields
    assert len(c._undo) == before


def test_undo_snapshot_is_deep_copied():
    c = _c()
    c.update_section(0, bars=5)
    c.undo()
    c.spec["sections"][0]["bars"] = 999            # mutate live
    c.redo()                                        # redo target must be intact
    assert c.spec["sections"][0]["bars"] == 5


def test_history_cap_enforced():
    c = _c()
    for i in range(Controller._HISTORY_CAP + 20):
        c.update_section(0, bars=(i % 12) + 1)
    assert len(c._undo) == Controller._HISTORY_CAP


# --------------------------------------------------------------------- UI
def test_edit_menu_undo_reverts_and_enable_state(qtbot):
    w = MainWindow(Controller(seed=2))
    qtbot.addWidget(w)
    w._c.song_from_profile("pop_punk")
    w.generate_view.load_current_spec()
    assert not w._undo_act.isEnabled()             # nothing to undo yet
    w._c.update_section(0, bars=11)
    w.generate_view.arrangementChanged.emit()      # (edits normally emit this)
    assert w._undo_act.isEnabled()
    w._undo()
    assert w._c.spec["sections"][0]["bars"] != 11
    assert not w._undo_act.isEnabled()
    assert w._redo_act.isEnabled()


def test_browser_apply_emits_and_is_undoable(qtbot):
    w = MainWindow(Controller(seed=4))
    qtbot.addWidget(w)
    w._c.song_from_profile("pop_punk")
    w.generate_view.load_current_spec()
    w.generate_view.timeline.list.setCurrentRow(0)
    before = w._c.spec["sections"][0].get("groove")
    with qtbot.waitSignal(w.generate_view.arrangementChanged, timeout=1000):
        ok = w.generate_view.apply_groove_to_current_section("half_time_shuffle")
    assert ok
    assert w._undo_act.isEnabled()                 # enable-state refreshed live
    assert w._c.spec["sections"][0]["groove"] == "half_time_shuffle"
    w._undo()
    assert w._c.spec["sections"][0].get("groove") == before


def test_bpm_change_is_undoable(qtbot):
    w = MainWindow(Controller(seed=3))
    qtbot.addWidget(w)
    w._c.song_from_profile("pop_punk")
    w.generate_view.load_current_spec()
    w.generate_view.bpm.setValue(201)              # fires _on_bpm_changed -> set_tempo
    assert w._c.spec["tempo"] == 201.0
    assert w._undo_act.isEnabled()
    w._undo()
    assert w._c.spec["tempo"] != 201.0
