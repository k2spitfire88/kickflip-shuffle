"""Engine grid-pattern override (Phase 5a-ii extension #3). The override is
additive: golden output is unchanged without `patterns` (see test_golden); here we
guard the override path itself."""
import pytest

import engine
from engine.generate import STEPS
KICK4 = [100, 0, 0, 0] * 4   # 4-on-the-floor, kick only


def _one_section_spec(patterns=None, bars=2):
    sec = {"groove": "verse_basic", "bars": bars}
    if patterns is not None:
        sec["patterns"] = patterns
    # humanize=0 -> exact grid timing so per-bar tick windows don't overlap
    # (jitter could otherwise nudge a neighbouring bar's hit across the boundary).
    return {"ppq": 480, "profile": "pop_punk", "tempo": 170,
            "overrides": {"humanize": 0}, "sections": [sec]}


def _bar_notes(events, bar, ppq=480):
    step_ticks = ppq // (STEPS // 4)
    lo = bar * STEPS * step_ticks
    hi = lo + STEPS * step_ticks
    return {n for t, n, _, _ in events if lo <= t < hi}


def test_override_replaces_bar_pattern():
    spec = _one_section_spec({0: {"kick": KICK4}})
    notes = _bar_notes(engine.build_song(spec, seed=3), 0)
    assert notes == {engine.GM["kick"]}            # only the overridden kick
    # bar 1 (not overridden) keeps the groove -> more than just kick
    assert _bar_notes(engine.build_song(spec, seed=3), 1) != {engine.GM["kick"]}


def test_resolved_bar_returns_copy():
    spec = _one_section_spec({0: {"kick": KICK4}})
    rows = engine.resolved_bar(spec, 0, 0, seed=1)
    rows["kick"][1] = 99
    assert spec["sections"][0]["patterns"][0]["kick"][1] == 0   # spec not aliased


def test_str_bar_key_honoured():
    spec = _one_section_spec({"0": {"kick": KICK4}})            # JSON-style str key
    assert engine.resolved_bar(spec, 0, 0, seed=1) == {"kick": KICK4}


def test_empty_and_all_zero_override_are_silent():
    assert _bar_notes(engine.build_song(_one_section_spec({0: {}}), seed=1), 0) == set()
    spec = _one_section_spec({0: {"kick": [0] * STEPS}})
    assert _bar_notes(engine.build_song(spec, seed=1), 0) == set()


@pytest.mark.parametrize("bad", [
    {"not_a_drum": [0] * STEPS},                    # unknown instrument
    {"kick": [0] * (STEPS - 1)},                    # wrong length
    {"kick": [0, 1, 200] + [0] * (STEPS - 3)},      # out of range
    {"kick": [True] + [0] * (STEPS - 1)},           # bool, not int
])
def test_validate_pattern_raises(bad):
    with pytest.raises(ValueError):
        engine._validate_pattern(bad)


def test_validate_pattern_accepts_empty_and_valid():
    engine._validate_pattern({})
    engine._validate_pattern({"cowbell": [0] * STEPS, "kick": KICK4})


def test_export_across_maps_with_exotic_override(tmp_path):
    # cowbell is in GM/ROLES but no groove emits it; an override + EZ_DRUMMER_3
    # must not KeyError (ROLES == GM keys -> every registered map is total).
    spec = _one_section_spec({0: {"cowbell": [90, 0, 0, 0] * 4}})
    ev = engine.build_song(spec, seed=2, output_map=engine.EZ_DRUMMER_3)
    out = engine.write_midi(ev, str(tmp_path / "c.mid"), tempo=170)
    assert out and engine.GM["cowbell"] in {n for _, n, _, _ in ev}
