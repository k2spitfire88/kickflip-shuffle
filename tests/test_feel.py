"""Phase 8f tests — per-section time-feel (normal/half/double) + tap tempo.

Golden byte-identity for the cumulative-bar_start refactor is covered by
test_golden; here we check the SCALED math and that normal is a no-op."""
import engine
from engine.generate import STEPS
from app.controller import Controller
from app.ui.generate_view import GenerateView


def _spec(feel_mid):
    return {"ppq": 480, "profile": "pop_punk", "tempo": 170, "overrides": {},
            "sections": [{"groove": "verse_basic", "bars": 1},
                         {"groove": "verse_basic", "bars": 1, "feel": feel_mid}
                         if feel_mid else {"groove": "verse_basic", "bars": 1},
                         {"groove": "verse_basic", "bars": 1}]}


def _bar_ticks(ppq=480):
    return STEPS * (ppq // 4)


def test_normal_feel_is_byte_identical():
    a = engine.build_song(_spec(None), seed=1)
    b = engine.build_song(
        {**_spec(None), "sections": [dict(s, feel="normal")
                                     for s in _spec(None)["sections"]]}, seed=1)
    assert a == b                                  # feel='normal' == absent


def test_double_feel_shrinks_bar_and_shifts_later_sections():
    bt = _bar_ticks()
    m_normal = engine.compute_section_markers(_spec(None))
    m_double = engine.compute_section_markers(_spec("double"))
    # Section 1 (index 1) starts at the same tick; section 2 shifts EARLIER by
    # half a bar because section 1 (double) is half as wide.
    assert m_normal[1][0] == m_double[1][0] == bt
    assert m_double[2][0] == bt + bt // 2          # normal bt+bt; double bt+bt/2
    assert m_normal[2][0] == 2 * bt


def test_half_feel_widens_bar():
    bt = _bar_ticks()
    m = engine.compute_section_markers(_spec("half"))
    assert m[2][0] == bt + 2 * bt                  # middle section twice as wide


def test_events_within_double_section_are_faster():
    # A double-feel single-section spec: last event tick < a normal one's.
    normal = engine.build_song(
        {"ppq": 480, "profile": "pop_punk", "tempo": 170, "overrides": {},
         "sections": [{"groove": "verse_basic", "bars": 1}]}, seed=3)
    double = engine.build_song(
        {"ppq": 480, "profile": "pop_punk", "tempo": 170, "overrides": {},
         "sections": [{"groove": "verse_basic", "bars": 1, "feel": "double"}]},
        seed=3)
    assert max(t for t, *_ in double) < max(t for t, *_ in normal)


def test_set_section_feel_normal_unsets_key():
    c = Controller(seed=1)
    c.song_from_profile("pop_punk")
    c.set_section_feel(0, "double")
    assert c.spec["sections"][0]["feel"] == "double"
    c.set_section_feel(0, "normal")
    assert "feel" not in c.spec["sections"][0]      # normal -> unset (default path)


def test_playhead_map_accounts_for_feel(qtbot):
    v = GenerateView(Controller(seed=1))
    qtbot.addWidget(v)
    v._c.build_spec_from_ui_state(
        "pop_punk", sections=[{"groove": "verse_basic", "bars": 1, "feel": "double"},
                              {"groove": "verse_basic", "bars": 1}])
    v.load_current_spec()
    spec = v._c.spec
    tempo, ppq = spec["tempo"], spec["ppq"]
    sec_per_tick = 60.0 / (tempo * ppq)
    half_bar_ticks = _bar_ticks() // 2             # section 0 (double) is half wide
    # Just past section 0's (shrunk) end -> should land in section 1.
    t = (half_bar_ticks + 1) * sec_per_tick
    assert v._position_to_grid(t)[0] == 1


def test_tap_tempo_sets_bpm(qtbot, monkeypatch):
    v = GenerateView(Controller(seed=1))
    qtbot.addWidget(v)
    v._c.song_from_profile("pop_punk")
    v.load_current_spec()
    clock = {"t": 0.0}
    monkeypatch.setattr("time.monotonic", lambda: clock["t"])
    for _ in range(4):                             # 0.4 s apart -> 150 BPM
        v._on_tap()
        clock["t"] += 0.4
    assert v._c.spec["tempo"] == 150.0


def test_tap_tempo_identical_timestamps_no_crash(qtbot, monkeypatch):
    v = GenerateView(Controller(seed=1))
    qtbot.addWidget(v)
    v._c.song_from_profile("pop_punk")
    v.load_current_spec()
    monkeypatch.setattr("time.monotonic", lambda: 5.0)   # every tap same instant
    for _ in range(3):
        v._on_tap()                                # must not ZeroDivisionError
    assert v._c.spec["tempo"] == float(engine.PROFILES["pop_punk"]["tempo"])
