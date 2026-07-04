"""Phase 8e section-lock tests — structural-only lock: a locked section keeps its
groove across regenerate; unlock restores role-based rolling; undoable."""
import engine
from app.controller import Controller


def _c():
    c = Controller(seed=1)
    # A multi-section role-based arrangement so regenerate can re-roll grooves.
    c.build_spec_from_ui_state(
        "pop_punk",
        sections=[{"role": "verse", "bars": 2},
                  {"role": "chorus", "bars": 2},
                  {"role": "verse", "bars": 2}])
    c.generate()
    return c


def test_lock_freezes_groove_across_regenerate():
    c = _c()
    frozen = engine.resolved_section_grooves(c.spec, seed=c.seed)[0]["groove"]
    c.set_section_locked(0, True)
    sec = c.spec["sections"][0]
    assert sec.get("locked") and sec.get("groove") == frozen and "role" not in sec
    # Reroll several times — the locked section's groove must not change.
    for _ in range(8):
        c.regenerate()
        assert c.spec["sections"][0]["groove"] == frozen


def test_unlock_restores_role_and_rolls_again():
    c = _c()
    c.set_section_locked(0, True)
    assert "role" not in c.spec["sections"][0]
    c.set_section_locked(0, False)
    sec = c.spec["sections"][0]
    assert sec.get("role") == "verse"          # pre-lock role restored
    assert "groove" not in sec and not sec.get("locked")
    assert "_lock_added" not in sec and "_prelock_role" not in sec


def test_lock_noop_when_already_in_state():
    c = _c()
    c.set_section_locked(0, False)             # already unlocked -> no-op
    assert not c.can_undo()
    c.set_section_locked(0, True)
    assert c.can_undo()


def test_lock_is_undoable():
    c = _c()
    before = dict(c.spec["sections"][0])
    c.set_section_locked(0, True)
    c.undo()
    assert c.spec["sections"][0] == before     # lock fully reverted


def test_resolved_section_grooves_index_aligned_with_bars0():
    # A degenerate bars=0 section must not shift later sections' indices.
    spec = {"ppq": 480, "profile": "pop_punk", "tempo": 170, "overrides": {},
            "sections": [{"role": "verse", "bars": 0},
                         {"role": "chorus", "bars": 2}]}
    picks = engine.resolved_section_grooves(spec, seed=1)
    assert len(picks) == 2
    assert picks[0] is None                    # bars=0 -> no resolved bar
    assert picks[1] is not None                # chorus still at index 1


def test_lock_bars0_section_is_safe():
    c = Controller(seed=1)
    c.build_spec_from_ui_state(
        "pop_punk", sections=[{"role": "verse", "bars": 0},
                              {"role": "chorus", "bars": 2}])
    c.generate()
    c.set_section_locked(0, True)              # must not IndexError
    assert c.spec["sections"][0].get("locked")
    c.set_section_locked(0, False)             # clean unlock
    assert not c.spec["sections"][0].get("locked")


def test_section_editor_disabled_when_locked(qtbot):
    from app.ui.editor_widgets import SectionEditor
    c = _c()
    ed = SectionEditor(c)
    qtbot.addWidget(ed)
    ed.load(0)
    assert ed.isEnabled()
    c.set_section_locked(0, True)
    ed.load(0)
    assert not ed.isEnabled()                  # frozen -> read-only
    c.set_section_locked(0, False)
    ed.load(0)
    assert ed.isEnabled()                      # re-enabled after unlock


def test_locked_section_with_preexisting_groove():
    c = Controller(seed=2)
    c.build_spec_from_ui_state(
        "pop_punk", sections=[{"groove": "skank", "bars": 2},
                              {"role": "chorus", "bars": 2}])
    c.generate()
    c.set_section_locked(0, True)              # already explicit groove
    assert c.spec["sections"][0]["groove"] == "skank"
    c.set_section_locked(0, False)
    assert c.spec["sections"][0]["groove"] == "skank"   # kept (we didn't add it)
    assert not c.spec["sections"][0].get("locked")
