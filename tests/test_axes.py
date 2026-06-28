"""Per-section axes: global-only path unchanged; overrides scoped correctly."""
import copy

import engine


def test_empty_axes_byte_identical():
    a = engine.song_from_profile("pop_punk")
    b = copy.deepcopy(a)
    for s in b["sections"]:
        s["axes"] = {}
    assert engine.build_song(a, seed=42) == engine.build_song(b, seed=42)


def test_section_override_changes_output():
    a = engine.song_from_profile("pop_punk")
    b = copy.deepcopy(a)
    b["sections"][2]["axes"] = {"double_bass": 1.0}
    assert engine.build_song(a, seed=42) != engine.build_song(b, seed=42)


def test_override_scoped_to_its_section_and_after():
    a = engine.song_from_profile("pop_punk")
    b = copy.deepcopy(a)
    b["sections"][2]["axes"] = {"double_bass": 1.0}
    # bars before the overridden section are unaffected...
    assert engine.resolved_bar(a, 0, 0, seed=42) == engine.resolved_bar(b, 0, 0, seed=42)
    assert engine.resolved_bar(a, 1, 0, seed=42) == engine.resolved_bar(b, 1, 0, seed=42)
    # ...the overridden section's bar differs.
    assert engine.resolved_bar(a, 2, 0, seed=42) != engine.resolved_bar(b, 2, 0, seed=42)


def test_spec_level_humanize_still_honored():
    # humanize keeps its 3-tier (overrides -> spec -> profile) resolution.
    a = engine.song_from_profile("pop_punk")
    tight = copy.deepcopy(a); tight["humanize"] = 0.0
    loose = copy.deepcopy(a); loose["humanize"] = 1.0
    assert engine.build_song(tight, seed=42) != engine.build_song(loose, seed=42)
