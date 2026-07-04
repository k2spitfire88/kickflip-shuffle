"""Phase 8c playhead tests — seconds->(section,bar,step) mapping and the StepGrid
overlay gating (pytest-qt offscreen)."""
from app.controller import Controller
from app.ui.generate_view import GenerateView


def _view(qtbot):
    v = GenerateView(Controller(seed=1))
    qtbot.addWidget(v)
    v._c.song_from_profile("pop_punk")
    v.load_current_spec()
    return v


def test_position_zero_is_none(qtbot):
    v = _view(qtbot)
    assert v._position_to_grid(0.0) is None


def test_position_maps_to_section_bar_step(qtbot):
    v = _view(qtbot)
    spec = v._c.spec
    tempo, ppq = spec["tempo"], spec.get("ppq", 480)
    ticks_per_bar = 4 * ppq
    sec_per_tick = 60.0 / (tempo * ppq)
    # Start of the very first bar -> first section, bar 0, step 0.
    assert v._position_to_grid(0.001) == (0, 0, 0)
    # A third of the way through the first bar -> step 5 (of 16).
    t2 = (ticks_per_bar / 3) * sec_per_tick
    assert v._position_to_grid(t2)[2] == 5
    # Start of the global 2nd bar -> step 0, and it lands inside the section walk.
    si, bar, step = v._position_to_grid(ticks_per_bar * sec_per_tick + 0.001)
    assert step == 0 and si >= 0 and bar >= 0


def test_position_past_end_is_none(qtbot):
    v = _view(qtbot)
    total_bars = sum(int(s.get("bars", 4)) for s in v._c.spec["sections"])
    tempo, ppq = v._c.spec["tempo"], v._c.spec.get("ppq", 480)
    sec_per_tick = 60.0 / (tempo * ppq)
    past = (total_bars * 4 * ppq + 10) * sec_per_tick
    assert v._position_to_grid(past) is None


def test_grid_playhead_gated_to_visible_section_bar(qtbot):
    v = _view(qtbot)
    g = v.grid
    g._i = 0
    g.bar.setValue(0)
    g.set_playhead(0, 0, 7)                 # matches visible -> shows
    assert g._playhead == 7
    g.set_playhead(1, 0, 7)                 # different section -> hidden
    assert g._playhead is None
    g.set_playhead(0, 3, 7)                 # different bar -> hidden
    assert g._playhead is None
    g.set_playhead(0, 0, 2)
    g.clear_playhead()
    assert g._playhead is None


def test_tick_playhead_stops_timer_at_end(qtbot, monkeypatch):
    v = _view(qtbot)
    v._play_timer.start()
    monkeypatch.setattr(type(v._c), "playback_position", property(lambda self: 0.0))
    v._tick_playhead()                      # position 0 -> None -> stop
    assert not v._play_timer.isActive()
    assert v.grid._playhead is None


def test_render_failed_stops_playhead(qtbot):
    v = _view(qtbot)
    v._play_timer.start()
    v.grid.set_playhead(v.grid._i, v.grid.bar.value(), 4)
    v._on_render_failed("boom")
    assert not v._play_timer.isActive()
    assert v.grid._playhead is None


def test_section_switch_clears_stale_playhead(qtbot):
    v = _view(qtbot)
    if len(v._c.spec["sections"]) < 2:
        return                              # need >=2 sections to switch
    v.grid.set_playhead(v.grid._i, v.grid.bar.value(), 6)
    assert v.grid._playhead == 6
    v.grid.load(1)                          # switch section -> stale playhead cleared
    assert v.grid._playhead is None
