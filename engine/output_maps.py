"""Articulation output maps — symbolic drum role -> concrete MIDI note number.

`build_song` emits symbolic `inst` roles (kick, snare, hat, ...); the selected
output map resolves each to a MIDI note at build time. `GENERAL_MIDI` is the
default and is byte-identical to the engine's historical `GM` map (works in any
DAW/sampler). Other maps are alternate translations of the SAME 17 roles.

Every map MUST define all 17 roles in `ROLES` — `build_song` does `note =
output_map[inst]`, so a missing key is a runtime KeyError, not a silent miss.

New maps are data, not code: add a dict here + register it in `OUTPUT_MAPS`.
"""

# The 17 symbolic roles the engine can emit (mirrors generate.GM keys).
ROLES = (
    "kick", "snare", "rim",
    "hat", "hat_open", "hat_pedal",
    "crash", "crash2", "china", "splash", "cowbell",
    "ride", "ride_bell",
    "tom_hi", "tom_mid", "tom_low", "tom_floor",
)

# General MIDI percussion (channel 10). DEFAULT — must stay byte-identical to
# generate.GM. A regression test asserts GENERAL_MIDI == GM.
GENERAL_MIDI = {
    "kick": 36, "snare": 38, "rim": 37,
    "hat": 42, "hat_open": 46, "hat_pedal": 44,
    "crash": 49, "crash2": 57, "china": 52, "splash": 55, "cowbell": 56,
    "ride": 51, "ride_bell": 53,
    "tom_hi": 50, "tom_mid": 47, "tom_low": 45, "tom_floor": 43,
}

# EZ Drummer 3 (Toontrack GM-superset).
# !!! UNVERIFIED note values !!! Toontrack's articulation keymap is a GM
# superset; most core voices match GM, but tom/rim articulations can differ per
# kit. These numbers are a best-effort starting point and MUST be validated in
# EZ Drummer 3 with the note-ladder export (engine.note_ladder) before being
# trusted. Divergences from GM below are flagged inline.
EZ_DRUMMER_3 = {
    "kick": 36, "snare": 38, "rim": 37,
    "hat": 42, "hat_open": 46, "hat_pedal": 44,
    "crash": 49, "crash2": 57, "china": 52, "splash": 55, "cowbell": 56,
    "ride": 51, "ride_bell": 53,
    "tom_hi": 48,    # UNVERIFIED: EZD3 high tom commonly 48 (GM is 50)
    "tom_mid": 47,
    "tom_low": 45,
    "tom_floor": 43,
}

# name -> map. Order is the UI listing order.
OUTPUT_MAPS = {
    "GENERAL_MIDI": GENERAL_MIDI,
    "EZ_DRUMMER_3": EZ_DRUMMER_3,
}

# Maps whose note numbers are not yet validated against the target sampler.
UNVERIFIED_MAPS = frozenset({"EZ_DRUMMER_3"})


def list_output_maps():
    """[(name, n_roles, verified_bool), ...] in UI order."""
    return [
        (name, len(m), name not in UNVERIFIED_MAPS)
        for name, m in OUTPUT_MAPS.items()
    ]


def get_output_map(name):
    if name not in OUTPUT_MAPS:
        raise ValueError(
            f"Unknown output map '{name}'. Options: {list(OUTPUT_MAPS)}"
        )
    return OUTPUT_MAPS[name]


# Fail loudly at import if any map is incomplete (would crash build_song).
for _name, _m in OUTPUT_MAPS.items():
    _missing = set(ROLES) - set(_m)
    if _missing:
        raise AssertionError(
            f"Output map '{_name}' missing roles: {sorted(_missing)}"
        )
