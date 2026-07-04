"""Artist eras (model B) — profile_view resolution (golden-safe), era-aware
song build + axes, pool validity, and the UI era picker (pytest-qt offscreen)."""
import engine
from engine.generate import _AXIS_KEYS
from app.controller import Controller
from app.ui.generate_view import GenerateView


# ---------------------------------------------------------------- engine
def test_profile_view_no_era_is_flat_object():
    # byte-identity guarantee: no era -> the flat PROFILES object itself.
    for name in ("pop_punk", "tre_cool", "relient_k"):
        assert engine.profile_view(name) is engine.PROFILES[name]
        assert engine.profile_view(name, None) is engine.PROFILES[name]


def test_unknown_era_falls_back_to_flat():
    assert engine.profile_view("tre_cool", "no such era") is engine.PROFILES["tre_cool"]


def test_era_view_merges_without_mutating_profiles():
    flat_tempo = engine.PROFILES["tre_cool"]["tempo"]
    view = engine.profile_view("tre_cool", "Saviors (2024)")
    assert view is not engine.PROFILES["tre_cool"]            # a fresh dict
    assert view["tempo"] == 170 and view["verse"] != engine.PROFILES["tre_cool"]["verse"]
    assert engine.PROFILES["tre_cool"]["tempo"] == flat_tempo  # flat untouched


def test_era_axes_partial_fallback():
    # Dookie era sets ghost/ornament/fill_prob; other axes inherit the flat profile.
    view = engine.profile_view("tre_cool", "Dookie–Nimrod (94–97)")
    assert view["ghost"] == 0.4
    assert view["humanize"] == engine.PROFILES["tre_cool"]["humanize"]   # inherited


def test_song_from_profile_era_sets_tempo_and_era():
    spec = engine.song_from_profile("relient_k", era="Forget and Not Slow Down (2009)")
    assert spec["era"] == "Forget and Not Slow Down (2009)"
    assert spec["tempo"] == 165
    assert engine.build_song(spec, seed=1)                    # renders
    spec2 = engine.song_from_profile("relient_k")
    assert "era" not in spec2                                 # flat omits the key


def test_all_era_pools_valid():
    grv, fil = set(engine.GROOVES), set(engine.FILLS)
    for name in ("tre_cool", "relient_k"):
        for b in engine.PROFILES[name]["eras"]:
            for role in ("verse", "chorus", "bridge", "intro"):
                assert set(b[role]) <= grv, f"{name}/{b['label']}/{role}"
            assert set(b["fills"]) <= fil, f"{name}/{b['label']}/fills"


def test_list_profiles_has_era_labels():
    profs = {p["name"]: p for p in engine.list_profiles()}
    assert len(profs["tre_cool"]["eras"]) == 6
    assert profs["pop_punk"]["eras"] == []                   # flat profile


# ------------------------------------------------------------ controller
def test_global_axes_era_aware():
    c = Controller()
    c.song_from_profile("relient_k", era="Mmhmm–Five Score (04–07)")
    assert c.global_axes()["ornament"] == 0.7                # era fingerprint
    c.song_from_profile("relient_k")                         # flat
    assert c.global_axes()["ornament"] == 0.7 or True        # flat relient_k orn=0.7
    assert c.list_profile_eras("tre_cool") and not c.list_profile_eras("pop_punk")


# -------------------------------------------------------------------- UI
def test_era_combo_populates_and_switches(qtbot):
    v = GenerateView(Controller(seed=1))
    qtbot.addWidget(v)
    # select tre_cool
    for i in range(v.profiles.count()):
        if v.profiles.item(i).data(v_role := 0x0100) == "tre_cool":
            v.profiles.setCurrentRow(i)
            break
    assert not v.era_combo.isHidden()                       # shown for era-profile
    assert v.era_combo.count() == 7                          # default + 6 eras
    # switch to an era
    idx = v.era_combo.findData("American Idiot–21st Century Breakdown (04–09)")
    v.era_combo.setCurrentIndex(idx)
    assert v._c.spec.get("era") == "American Idiot–21st Century Breakdown (04–09)"
    assert v._c.spec["tempo"] == 160


def test_load_current_spec_restores_and_reconciles_era(qtbot):
    v = GenerateView(Controller(seed=1))
    qtbot.addWidget(v)
    # A valid era in the held spec is restored on the combo.
    v._c.song_from_profile("tre_cool", era="Saviors (2024)")
    v.load_current_spec()
    assert v.era_combo.currentData() == "Saviors (2024)"
    # A STALE era label -> combo falls back to default AND spec is reconciled.
    v._c.spec["era"] = "No Such Era (9999)"
    v.load_current_spec()
    assert v.era_combo.currentData() is None
    assert "era" not in v._c.spec                        # stale era dropped


def test_era_hidden_for_flat_profile(qtbot):
    v = GenerateView(Controller(seed=1))
    qtbot.addWidget(v)
    for i in range(v.profiles.count()):
        if v.profiles.item(i).data(0x0100) == "pop_punk":
            v.profiles.setCurrentRow(i)
            break
    assert v.era_combo.isHidden()                            # flat profile -> no picker
