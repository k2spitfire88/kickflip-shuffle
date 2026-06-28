"""Output-map layer: completeness, GM identity, and remap behaviour."""
import engine
from engine.generate import GM


def test_general_midi_equals_gm():
    # The default map must be byte-identical to the historical GM map.
    assert engine.GENERAL_MIDI == GM


def test_all_maps_complete_17_keys():
    for name, m in engine.OUTPUT_MAPS.items():
        assert set(m) == set(engine.ROLES), f"{name} key mismatch"
        assert len(m) == 17, f"{name} must have all 17 roles"


def test_ezd3_same_keys_different_mapping():
    assert set(engine.EZ_DRUMMER_3) == set(engine.GENERAL_MIDI)
    # differs from GM only by mapping (some note values), not by keys
    assert engine.EZ_DRUMMER_3 != engine.GENERAL_MIDI


def test_list_output_maps_flags_verified():
    rows = dict((name, verified) for name, _n, verified in engine.list_output_maps())
    assert rows["GENERAL_MIDI"] is True
    assert rows["EZ_DRUMMER_3"] is False  # values unverified until EZD3-validated


def test_note_ladder_one_hit_per_role():
    ev = engine.note_ladder_events()
    assert len(ev) == len(engine.ROLES) == 17
    assert [n for _, n, _, _ in ev] == [engine.GENERAL_MIDI[r] for r in engine.ROLES]


def test_output_map_remaps_notes_same_timing():
    spec = {"ppq": 480, "profile": "pop_punk", "tempo": 172, "overrides": {},
            "sections": [{"groove": "longview_tom", "bars": 2}]}  # uses tom_hi
    gm = engine.build_song(spec, seed=42)
    ez = engine.build_song(spec, seed=42, output_map=engine.EZ_DRUMMER_3)
    assert len(gm) == len(ez)
    assert [t for t, *_ in gm] == [t for t, *_ in ez]  # timing unchanged
    assert gm != ez  # tom_hi remapped (50 -> 48)
