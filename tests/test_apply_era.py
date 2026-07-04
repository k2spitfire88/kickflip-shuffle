"""Apply-era-to-current-song + Lock tempo — re-flavor an existing spec in place
(keep sections + tempo) instead of rebuilding (pytest-qt offscreen for the UI)."""
import engine
from app.controller import Controller
from app.ui.generate_view import GenerateView


def _role_song(tempo=128):
    c = Controller(seed=1)
    # A role-based spec at a chosen tempo (as an uploaded/analysed song would be).
    c.build_spec_from_ui_state(
        "relient_k", tempo=tempo,
        sections=[{"role": "verse", "bars": 4}, {"role": "chorus", "bars": 4},
                  {"role": "bridge", "bars": 4}])
    c.generate()
    return c


# ---------------------------------------------------------------- controller
def test_apply_era_keeps_sections_and_tempo():
    c = _role_song(tempo=128)
    before = [dict(s) for s in c.spec["sections"]]
    c.apply_era("Mmhmm–Five Score (04–07) — Douglas")       # keep_tempo default True
    assert c.spec["era"] == "Mmhmm–Five Score (04–07) — Douglas"
    assert c.spec["tempo"] == 128                            # BPM preserved
    assert "tempo_range" not in c.spec                       # pinned (no re-roll)
    assert [s.get("role") for s in c.spec["sections"]] == \
           [s.get("role") for s in before]                   # structure preserved


def test_apply_era_reflavors_role_grooves():
    c = _role_song()
    c.apply_era("Anatomy–Two Lefts (01–03) — Douglas")
    era_pools = set()
    b = next(x for x in engine.PROFILES["relient_k"]["eras"]
             if x["label"] == "Anatomy–Two Lefts (01–03) — Douglas")
    for r in ("verse", "chorus", "bridge"):
        era_pools |= set(b[r])
    picks = engine.resolved_section_grooves(c.spec, seed=c.seed)
    assert all(p["groove"] in era_pools for p in picks)      # from the era pools


def test_apply_era_keep_tempo_false_adopts_range():
    c = _role_song(tempo=128)
    c.apply_era("Mmhmm–Five Score (04–07) — Douglas", keep_tempo=False)
    assert c.spec["tempo_range"] == [110, 170]               # relient_k era range
    assert c.spec["tempo"] == 140                            # era midpoint


def test_apply_era_none_clears():
    c = _role_song()
    c.apply_era("Mmhmm–Five Score (04–07) — Douglas")
    c.apply_era(None)
    assert "era" not in c.spec


def test_apply_era_is_undoable():
    c = _role_song(tempo=128)
    c.apply_era("Mmhmm–Five Score (04–07) — Douglas", keep_tempo=False)
    c.undo()
    assert "era" not in c.spec and c.spec["tempo"] == 128    # restored


def test_set_tempo_locked_drops_and_restores_range():
    c = _role_song()
    c.apply_era("Mmhmm–Five Score (04–07) — Douglas", keep_tempo=False)
    assert "tempo_range" in c.spec
    c.set_tempo_locked(True)
    assert "tempo_range" not in c.spec                       # pinned
    c.set_tempo_locked(False)
    assert c.spec["tempo_range"] == [110, 170]               # restored from era


def test_set_tempo_locked_flat_profile_no_range():
    c = _role_song()
    c.apply_era(None)                                        # flat
    c.set_tempo_locked(False)                                # flat int tempo
    assert "tempo_range" not in c.spec                       # nothing to restore


# -------------------------------------------------------------------- UI
def test_era_change_reflavors_not_rebuild(qtbot):
    v = GenerateView(Controller(seed=1))
    qtbot.addWidget(v)
    # Build a 3-section song via a profile, then switch era.
    for i in range(v.profiles.count()):
        if v.profiles.item(i).data(0x0100) == "relient_k":
            v.profiles.setCurrentRow(i)
            break
    v._c.set_sections([{"role": "verse", "bars": 4}, {"role": "chorus", "bars": 4},
                       {"role": "bridge", "bars": 4}])
    v.load_current_spec()
    n_before = len(v._c.spec["sections"])
    v.bpm.setValue(128)
    v.lock_tempo.setChecked(True)
    idx = v.era_combo.findData("Mmhmm–Five Score (04–07) — Douglas")
    v.era_combo.setCurrentIndex(idx)
    assert v._c.spec.get("era") == "Mmhmm–Five Score (04–07) — Douglas"
    assert len(v._c.spec["sections"]) == n_before            # NOT rebuilt
    assert v._c.spec["tempo"] == 128                         # BPM kept
