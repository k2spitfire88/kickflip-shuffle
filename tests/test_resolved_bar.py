"""resolved_bar MIRROR contract: it returns exactly the pre-jitter rows that
build_song renders at the same (section, bar)."""
import random

import pytest

import engine
from engine.generate import _iter_bars

SPECS = [
    (engine.song_from_profile("pop_punk"), 42),
    (engine.song_from_profile("ramones"), 7),
    ({"ppq": 480, "profile": "pop_punk", "tempo": 172, "overrides": {},
      "sections": [{"groove": "chorus_ride_bell", "bars": 2, "crash_in": True},
                   {"groove": "verse_basic", "bars": 2, "fill": "china_choke"},
                   {"groove": "verse_basic", "bars": 2, "fill": "tom_descend"}]}, 99),
    # A mid-song pattern override: asserts the MIRROR still holds for bars AFTER
    # the override despite the rng-stream shift (resolved_bar(b+k)==build bar b+k).
    ({"ppq": 480, "profile": "pop_punk", "tempo": 170, "overrides": {},
      "sections": [{"groove": "verse_basic", "bars": 3,
                    "patterns": {1: {"kick": [100, 0, 0, 0] * 4,
                                     "snare": [0, 0, 0, 0, 80] + [0] * 11}}},
                   {"groove": "chorus_ride_bell", "bars": 2, "crash_in": True}]}, 11),
]


def _rows_used(spec, seed):
    rng = random.Random(seed)
    return [rows for _si, _bi, _g, _f, rows, _ev
            in _iter_bars(spec, rng, engine.GENERAL_MIDI)]


@pytest.mark.parametrize("spec,seed", SPECS)
def test_resolved_bar_mirrors_build(spec, seed):
    used = _rows_used(spec, seed)
    bar = 0
    for si, s in enumerate(spec["sections"]):
        for bj in range(s.get("bars", 4)):
            assert engine.resolved_bar(spec, si, bj, seed=seed) == used[bar]
            bar += 1


def test_resolved_bar_self_deterministic():
    a = engine.song_from_profile("pop_punk")
    assert engine.resolved_bar(a, 1, 0, seed=5) == engine.resolved_bar(a, 1, 0, seed=5)


def test_resolved_bar_out_of_range():
    a = engine.song_from_profile("pop_punk")
    with pytest.raises(IndexError):
        engine.resolved_bar(a, 99, 0, seed=1)
    with pytest.raises(IndexError):
        engine.resolved_bar(a, 0, 999, seed=1)
