#!/usr/bin/env python3
"""
Pop-punk drum MIDI generator for EZ Drummer 3 / Superior Drummer 3 / Logic.

v3 — widened to span the genre across eras and subgenres. Pop punk runs from
'77/Ramones buzzsaw through '90s skate punk, 2000s mall/mainstream, emo
crossover, easycore (pop punk + metalcore breakdowns & double bass), the 2010s
"tr00"/melodic wave, and the 2020s Travis-Barker-produced, trap-inflected
revival. The engine models the *axes* the genre varies along; a band is a point
in that space. Presets are named coordinates grouped by era; you can also dial
any axis directly to reach a band or song no preset covers.

Drive it by PROFILE (broad / band-flavored) or by explicit SONG SPEC (full
control). See README usage:
    python generate.py --list-profiles
    python generate.py --profile easycore --out drums.mid
    python generate.py --profile tre_cool --tempo 180 --out drums.mid
    python generate.py --song song.json --out drums.mid

Axes (set per profile, overridable per song via "overrides"):
    tempo        center-of-gravity BPM
    ghost        ghost-note presence (0-1+)
    ornament     hi-hat filigree / ride-bell flips (0-1)
    double_bass  16th double-kick density (0-1)   [NFG, easycore, FOB, Sum 41]
    syncopation  kick displacement / push (0-1)   [FOB disco-punk, emo]
    breakdown    chance a bridge becomes a half-time chug (0-1) [easycore]
    fill_prob    chance a transition bar gets a fill (0-1)
    humanize     timing/velocity looseness (lower = tighter/cleaner)
"""

import argparse
import json
import random

try:
    import mido
except ImportError:
    raise SystemExit("This script needs mido. Install with: pip install mido")

# ---------------------------------------------------------------------------
GM = {
    "kick": 36, "snare": 38, "rim": 37,
    "hat": 42, "hat_open": 46, "hat_pedal": 44,
    "crash": 49, "crash2": 57, "china": 52, "splash": 55, "cowbell": 56,
    "ride": 51, "ride_bell": 53,
    "tom_hi": 50, "tom_mid": 47, "tom_low": 45, "tom_floor": 43,
}
STEPS = 16
DOUBLE_BASS_GRID = [2, 3, 6, 7, 10, 11, 14, 15]  # the "e/a" 16ths


def _hat8(vel=82, accent=95):
    out = [0] * STEPS
    for i in range(0, STEPS, 2):
        out[i] = accent if i % 4 == 0 else vel
    return out


def _hat16(vel=70, accent=92):
    out = [vel] * STEPS
    for i in range(0, STEPS, 4):
        out[i] = accent
    return out


def _hat16_bounce(vel=64, accent=92, push=80):
    """16th hats with a bounce: downbeat accent, lighter 'e', medium 'a'."""
    out = []
    for i in range(STEPS):
        if i % 4 == 0:
            out.append(accent)
        elif i % 4 == 2:
            out.append(push)
        else:
            out.append(vel)
    return out


def _quarters(vel=100):
    return {i: vel for i in range(0, STEPS, 4)}


# ---------------------------------------------------------------------------
# GROOVE LIBRARY
# ---------------------------------------------------------------------------
GROOVES = {
    # Core
    "verse_basic": {"hat": _hat8(), "snare": {4: 110, 12: 110},
                    "kick": {0: 105, 8: 100, 10: 95}},
    "skank": {"hat": _hat8(80, 92), "snare": {2: 108, 6: 108, 10: 108, 14: 108},
              "kick": {0: 104, 4: 104, 8: 104, 12: 104}},
    "surf": {"hat": _hat8(), "snare": {4: 108, 6: 92, 12: 108},
             "kick": {0: 105, 8: 102}},
    "verse_doubles": {"hat": _hat8(), "snare": {4: 110, 12: 110},
                      "kick": {0: 105, 6: 92, 7: 92, 8: 102, 14: 92, 15: 92}},
    "verse_16th": {"hat": _hat16(), "snare": {4: 112, 7: 40, 12: 112, 15: 42},
                   "kick": {0: 106, 8: 100, 11: 96}},
    "two_step": {"hat": _hat8(82, 94), "snare": {4: 110, 12: 110},
                 "kick": {0: 106, 8: 106}},

    # '77 / power-pop
    "ramones_buzzsaw": {"hat": _hat8(86, 96), "snare": {4: 112, 12: 112},
                        "kick": {0: 104, 4: 100, 8: 104, 12: 100}},
    "four_floor": {"hat": _hat8(), "snare": {4: 112, 12: 112},
                   "kick": {0: 106, 4: 100, 8: 106, 12: 100}},

    # Hardcore / skate
    "dbeat": {"hat": _hat8(78, 90), "snare": {4: 110, 12: 110},
              "kick": {0: 106, 3: 92, 8: 104, 11: 92}},
    "blast_beat": {"hat": {i: 70 for i in range(0, STEPS, 2)},
                   "snare": {i: 96 for i in range(2, STEPS, 4)},
                   "kick": {i: 100 for i in range(0, STEPS, 4)}},

    # Ska-punk
    "ska_punk": {"hat_open": {2: 96, 6: 96, 10: 96, 14: 96},
                 "hat": {0: 70, 4: 70, 8: 70, 12: 70},
                 "rim": {4: 100, 12: 100}, "kick": {0: 104, 8: 102}},

    # Double-bass driven (NFG / easycore / Sum 41 / FOB)
    "double_bass_verse": {"hat": _hat8(82, 94), "snare": {4: 112, 12: 112},
                          "kick": {0: 106, 6: 92, 7: 92, 8: 104, 14: 92, 15: 92,
                                   2: 88, 3: 88, 10: 88, 11: 88}},

    # Disco-punk (Fall Out Boy "Dance Dance")
    "disco_punk": {"hat": {0: 60, 2: 96, 4: 60, 6: 96, 8: 60, 10: 96, 12: 60, 14: 96},
                   "hat_open": {2: 98, 6: 98, 10: 98, 14: 98},
                   "snare": {4: 112, 12: 112},
                   "kick": {0: 106, 4: 100, 8: 106, 12: 100}},

    # Tom-driven (Paramore "Decode" / "Brick by Boring Brick")
    "tribal_toms": {"tom_floor": {0: 108, 8: 108}, "tom_low": {4: 100, 12: 100},
                    "snare": {12: 110}, "hat_open": {6: 84, 14: 84},
                    "kick": {0: 104, 3: 90, 8: 102, 11: 90}},

    # Emo / mid-tempo syncopated
    "emo_syncopated": {"hat": _hat8(), "snare": {4: 112, 7: 44, 12: 112},
                       "kick": {0: 104, 6: 96, 10: 96, 11: 88}},

    # Modern revival (trap-inflected hats, sub kick, crisp snare)
    "trap_hat_modern": {"hat": _hat16_bounce(), "snare": {4: 116, 12: 116, 15: 46},
                        "kick": {0: 110, 7: 96, 8: 104}},

    # Emo / breakdown family
    "halftime": {"hat": _hat8(78, 90), "snare": {8: 116},
                 "kick": {0: 108, 4: 90, 12: 96, 14: 96}},
    "breakdown_chug": {"china": _quarters(108), "snare": {8: 118},
                       "kick": {0: 110, 2: 96, 3: 96, 8: 104, 10: 96, 11: 96}},
    "gang_break": {"crash": {0: 114, 8: 110}, "snare": {8: 118},
                   "kick": {0: 112, 8: 106}},

    # Melodic / sparse (Green Day "Longview")
    "longview_tom": {"tom_floor": {0: 104, 8: 104}, "tom_hi": {4: 96, 12: 96},
                     "hat_open": {6: 80, 14: 84}, "kick": {0: 102, 8: 100}},

    # Choruses
    "chorus_crash": {"crash": _quarters(108), "snare": {4: 114, 12: 114},
                     "kick": {0: 108, 2: 92, 8: 104, 10: 92}},
    "chorus_open_hat": {"hat_open": _hat8(96, 106), "snare": {4: 114, 12: 114},
                        "kick": {0: 108, 8: 104, 10: 95}},
    "chorus_ride_bell": {"ride": _hat8(80, 92), "ride_bell": {0: 100, 8: 100},
                         "snare": {4: 114, 12: 114}, "kick": {0: 108, 8: 104, 10: 95}},
    "chorus_doublebass": {"crash": _quarters(108), "snare": {4: 114, 12: 114},
                          "kick": {0: 108, 2: 92, 3: 92, 8: 106, 10: 92, 11: 92}},

    # Calmer pre-chorus
    "verse_ride": {"ride": _hat8(78, 92), "ride_bell": {0: 96, 8: 96},
                   "snare": {4: 108, 12: 108}, "kick": {0: 104, 8: 100}},
}


# ---------------------------------------------------------------------------
# FILL LIBRARY
# ---------------------------------------------------------------------------
def fill_tom_descend():
    return {"hat": {0: 88, 2: 84, 4: 88, 6: 84}, "snare": {8: 110, 9: 100},
            "tom_hi": {10: 108, 11: 100}, "tom_mid": {12: 110, 13: 102},
            "tom_low": {14: 110, 15: 104}}


def fill_snare_buildup():
    return {"snare": {i: int(70 + (i / (STEPS - 1)) * 50) for i in range(STEPS)},
            "kick": {0: 105, 8: 105}}


def fill_halfbar_toms():
    return {"hat": {0: 90, 2: 84, 4: 90, 6: 84}, "snare": {4: 110},
            "kick": {0: 105}, "tom_hi": {8: 106, 10: 104},
            "tom_mid": {11: 104, 12: 108},
            "tom_floor": {13: 106, 14: 110, 15: 108}}


def fill_triplet_snare():
    return {"hat": {0: 88, 4: 88}, "kick": {0: 104, 8: 104},
            "snare": {10: 104, 11: 104, 12: 110, 13: 104, 14: 104, 15: 108}}


def fill_ramones_crash():
    return {"hat": _hat8(), "snare": {4: 110, 12: 114},
            "kick": {0: 104, 8: 104}, "crash": {12: 112}}


def fill_dbeat_roll():
    return {"kick": {0: 106, 4: 104},
            "snare": {i: 96 + (i % 2) * 8 for i in range(8, STEPS)}}


def fill_marching_toms():
    return {"snare": {0: 108, 1: 96, 2: 100, 4: 108, 5: 96, 6: 100},
            "tom_hi": {8: 106, 9: 98}, "tom_mid": {10: 106, 11: 98},
            "tom_low": {12: 108, 13: 100}, "tom_floor": {14: 110, 15: 104}}


def fill_sparse_tom():
    return {"hat": _hat8(), "snare": {4: 108}, "kick": {0: 104, 8: 102},
            "tom_floor": {14: 108, 15: 104}}


def fill_double_bass():
    return {"kick": {i: 100 for i in range(0, STEPS)},
            "tom_hi": {8: 106}, "tom_mid": {10: 106},
            "tom_low": {12: 108}, "tom_floor": {14: 110},
            "crash": {0: 112}}


def fill_blast():
    return {"kick": {i: 100 for i in range(0, STEPS, 2)},
            "snare": {i: 100 for i in range(1, STEPS, 2)},
            "crash": {0: 112}}


def fill_china_choke():
    return {"kick": {0: 108, 8: 108}, "snare": {4: 110},
            "china": {12: 116}, "crash": {14: 110}}


def fill_linear():
    return {"kick": {0: 104, 3: 100, 8: 104, 11: 100},
            "snare": {2: 100, 5: 100, 10: 100, 13: 104},
            "tom_floor": {6: 100, 14: 106, 15: 104}}


def fill_tom_around():
    return {"snare": {0: 110, 1: 100}, "tom_hi": {2: 106, 3: 100},
            "tom_mid": {4: 106, 6: 104}, "tom_low": {8: 106, 10: 104},
            "tom_floor": {12: 108, 14: 110, 15: 104}}


FILLS = {
    "tom_descend": fill_tom_descend, "snare_buildup": fill_snare_buildup,
    "halfbar_toms": fill_halfbar_toms, "triplet_snare": fill_triplet_snare,
    "ramones_crash": fill_ramones_crash, "dbeat_roll": fill_dbeat_roll,
    "marching_toms": fill_marching_toms, "sparse_tom": fill_sparse_tom,
    "double_bass": fill_double_bass, "blast": fill_blast,
    "china_choke": fill_china_choke, "linear": fill_linear,
    "tom_around": fill_tom_around,
}


# ---------------------------------------------------------------------------
# PROFILES — named coordinates, grouped by era.
# Defaulted axes (ghost/ornament/double_bass/syncopation/breakdown/fill_prob/
# humanize) fall back to 0 / sensible values when omitted.
# ---------------------------------------------------------------------------
def _p(era, tempo, verse, chorus, bridge, intro, fills, **axes):
    d = {"era": era, "tempo": tempo, "verse": verse, "chorus": chorus,
         "bridge": bridge, "intro": intro, "fills": fills,
         "ghost": 0.5, "ornament": 0.4, "double_bass": 0.0, "syncopation": 0.0,
         "breakdown": 0.0, "fill_prob": 0.75, "humanize": 1.0}
    d.update(axes)
    return d


PROFILES = {
    # --- Generic / broad default ---
    "pop_punk": _p("generic", 172,
                   ["verse_basic", "skank", "surf", "verse_doubles",
                    "ramones_buzzsaw", "four_floor"],
                   ["chorus_crash", "chorus_open_hat", "chorus_ride_bell"],
                   ["halftime", "skank"], ["verse_basic", "verse_doubles"],
                   ["tom_descend", "snare_buildup", "triplet_snare", "ramones_crash"],
                   ghost=0.7, ornament=0.5, fill_prob=0.8),

    # --- First wave / '77 ---
    "ramones": _p("first_wave", 175,
                  ["ramones_buzzsaw", "two_step", "verse_basic"],
                  ["chorus_crash", "ramones_buzzsaw"], ["halftime"],
                  ["ramones_buzzsaw"],
                  ["ramones_crash", "tom_descend"],
                  ghost=0.1, ornament=0.2, fill_prob=0.5, humanize=1.0),

    # --- '90s skate / melodic punk ---
    "tre_cool": _p("90s_skate", 180,
                   ["verse_basic", "surf", "skank", "longview_tom", "verse_basic"],
                   ["chorus_ride_bell", "chorus_crash"],
                   ["halftime", "longview_tom"], ["verse_basic", "ramones_buzzsaw"],
                   ["marching_toms", "tom_descend", "triplet_snare", "sparse_tom"],
                   ghost=0.6, ornament=0.6, fill_prob=0.85),
    "offspring": _p("90s_skate", 172,
                    ["surf", "skank", "verse_basic", "two_step"],
                    ["chorus_crash", "chorus_open_hat"], ["halftime", "skank"],
                    ["surf", "verse_basic"],
                    ["tom_descend", "triplet_snare", "ramones_crash"],
                    ghost=0.4, ornament=0.4, fill_prob=0.7),
    "mxpx": _p("90s_skate", 195,
               ["skank", "ramones_buzzsaw", "dbeat", "skank"],
               ["chorus_crash", "skank"], ["skank", "halftime"],
               ["ramones_buzzsaw", "skank"],
               ["ramones_crash", "dbeat_roll", "tom_descend"],
               ghost=0.2, ornament=0.2, fill_prob=0.6, humanize=0.8),
    "skate_punk": _p("90s_skate", 205,
                     ["skank", "dbeat", "ramones_buzzsaw"],
                     ["chorus_crash", "skank"], ["dbeat", "skank"],
                     ["dbeat", "skank"], ["dbeat_roll", "ramones_crash", "blast"],
                     ghost=0.2, ornament=0.2, fill_prob=0.55, humanize=0.85),

    # --- 2000s mainstream / mall ---
    "barker": _p("2000s_mall", 168,
                 ["verse_16th", "verse_doubles", "verse_ride", "verse_16th"],
                 ["chorus_crash", "chorus_open_hat"], ["halftime", "skank"],
                 ["verse_doubles", "verse_16th"],
                 ["triplet_snare", "tom_descend", "marching_toms", "snare_buildup"],
                 ghost=1.0, ornament=1.0, fill_prob=0.95, humanize=0.8),
    "good_charlotte": _p("2000s_mall", 158,
                         ["verse_basic", "four_floor", "verse_basic"],
                         ["chorus_crash", "four_floor"], ["halftime"],
                         ["verse_basic", "four_floor"],
                         ["snare_buildup", "tom_descend"],
                         ghost=0.4, ornament=0.4, fill_prob=0.7),
    "simple_plan": _p("2000s_mall", 162,
                      ["verse_basic", "surf", "four_floor"],
                      ["chorus_crash", "chorus_open_hat"], ["halftime"],
                      ["verse_basic", "surf"], ["snare_buildup", "tom_descend"],
                      ghost=0.3, ornament=0.3, fill_prob=0.7, humanize=0.7),
    "new_found_glory": _p("2000s_mall", 178,
                          ["double_bass_verse", "verse_doubles", "skank"],
                          ["chorus_doublebass", "chorus_crash"],
                          ["breakdown_chug", "halftime"],
                          ["verse_doubles", "double_bass_verse"],
                          ["double_bass", "tom_descend", "china_choke"],
                          ghost=0.5, ornament=0.4, double_bass=0.7,
                          breakdown=0.6, fill_prob=0.85, humanize=0.85),
    "sum41": _p("2000s_mall", 188,
                ["skank", "double_bass_verse", "dbeat", "verse_doubles"],
                ["chorus_doublebass", "chorus_crash"],
                ["breakdown_chug", "halftime", "blast_beat"],
                ["dbeat", "skank"],
                ["double_bass", "dbeat_roll", "marching_toms", "blast"],
                ghost=0.3, ornament=0.4, double_bass=0.6, breakdown=0.5,
                fill_prob=0.85, humanize=0.85),
    "fall_out_boy": _p("2000s_mall", 168,
                       ["disco_punk", "four_floor", "verse_doubles", "double_bass_verse"],
                       ["chorus_crash", "chorus_doublebass"],
                       ["halftime", "emo_syncopated"],
                       ["disco_punk", "four_floor"],
                       ["tom_descend", "double_bass", "linear", "snare_buildup"],
                       ghost=0.6, ornament=0.5, double_bass=0.4, syncopation=0.5,
                       fill_prob=0.85, humanize=0.85),
    "all_time_low": _p("2000s_mall", 165,
                       ["four_floor", "verse_basic", "verse_doubles"],
                       ["chorus_crash", "chorus_open_hat"], ["halftime"],
                       ["four_floor", "verse_basic"],
                       ["snare_buildup", "tom_descend", "triplet_snare"],
                       ghost=0.4, ornament=0.4, fill_prob=0.75, humanize=0.8),

    # --- Emo crossover ---
    "paramore": _p("emo_crossover", 164,
                   ["tribal_toms", "emo_syncopated", "verse_basic", "verse_doubles"],
                   ["chorus_crash", "chorus_doublebass"],
                   ["halftime", "tribal_toms"], ["tribal_toms", "verse_basic"],
                   ["tom_around", "tom_descend", "linear", "triplet_snare"],
                   ghost=0.7, ornament=0.6, syncopation=0.5, double_bass=0.3,
                   fill_prob=0.85, humanize=0.9),
    "jimmy_eat_world": _p("emo_crossover", 150,
                          ["verse_basic", "surf", "emo_syncopated"],
                          ["chorus_crash", "chorus_open_hat"],
                          ["halftime", "emo_syncopated"],
                          ["verse_basic", "emo_syncopated"],
                          ["tom_descend", "snare_buildup"],
                          ghost=0.6, ornament=0.4, syncopation=0.3,
                          fill_prob=0.7, humanize=1.0),

    # --- Easycore / 2010s ---
    "easycore": _p("easycore_2010s", 182,
                   ["double_bass_verse", "skank", "verse_doubles", "blast_beat"],
                   ["chorus_doublebass", "chorus_crash"],
                   ["breakdown_chug", "gang_break"],
                   ["double_bass_verse", "blast_beat"],
                   ["double_bass", "blast", "china_choke", "tom_around"],
                   ghost=0.4, ornament=0.4, double_bass=0.85, breakdown=0.9,
                   fill_prob=0.9, humanize=0.85),
    "neck_deep": _p("easycore_2010s", 170,
                    ["verse_basic", "four_floor", "double_bass_verse", "emo_syncopated"],
                    ["chorus_crash", "chorus_doublebass"],
                    ["halftime", "breakdown_chug"],
                    ["verse_basic", "four_floor"],
                    ["tom_descend", "double_bass", "snare_buildup"],
                    ghost=0.6, ornament=0.5, double_bass=0.35, breakdown=0.4,
                    fill_prob=0.8, humanize=0.9),

    # --- Modern revival / 2020s ---
    "revival_2020s": _p("revival_2020s", 160,
                        ["trap_hat_modern", "four_floor", "verse_basic"],
                        ["chorus_crash", "chorus_doublebass"],
                        ["halftime", "trap_hat_modern"],
                        ["trap_hat_modern", "four_floor"],
                        ["tom_descend", "linear", "snare_buildup", "tom_around"],
                        ghost=0.8, ornament=0.6, syncopation=0.4, double_bass=0.3,
                        fill_prob=0.85, humanize=0.6),
    "pop_punk_pop": _p("revival_2020s", 158,
                       ["four_floor", "verse_basic", "trap_hat_modern"],
                       ["chorus_crash", "chorus_open_hat"], ["halftime"],
                       ["four_floor", "verse_basic"],
                       ["snare_buildup", "tom_descend", "triplet_snare"],
                       ghost=0.6, ornament=0.5, fill_prob=0.75, humanize=0.7),

    # --- Ska-punk ---
    "ska_punk": _p("ska_punk", 165,
                   ["ska_punk", "verse_basic", "ska_punk"],
                   ["chorus_crash", "skank"], ["ska_punk", "halftime"],
                   ["ska_punk", "verse_basic"], ["tom_descend", "ramones_crash"],
                   ghost=0.4, ornament=0.6, fill_prob=0.6),
}

ERA_ORDER = ["generic", "first_wave", "90s_skate", "2000s_mall",
             "emo_crossover", "easycore_2010s", "revival_2020s", "ska_punk"]
ROLE_FALLBACK = {"prechorus": "verse", "outro": "chorus"}
BREAKDOWN_POOL = ["breakdown_chug", "gang_break"]


# ---------------------------------------------------------------------------
# Build engine
# ---------------------------------------------------------------------------
def _normalize(groove):
    out = {}
    for inst, pattern in groove.items():
        if isinstance(pattern, list):
            out[inst] = list(pattern)
        else:
            row = [0] * STEPS
            for step, vel in pattern.items():
                row[int(step)] = vel
            out[inst] = row
    return out


def _add_crash_accent(groove):
    g = {k: list(v) for k, v in groove.items()}
    g.setdefault("crash", [0] * STEPS)
    g["crash"][0] = 112
    if "hat" in g and g["hat"][0]:
        g["hat"][0] = 0
    return g


def _apply_axes(groove, ghost=1.0, ornament=0.5, double_bass=0.0,
                syncopation=0.0, rng=None):
    g = {k: list(v) for k, v in groove.items()}
    # ghost notes: snare hits <= 50 are ghosts
    if "snare" in g:
        for i, v in enumerate(g["snare"]):
            if 0 < v <= 50:
                g["snare"][i] = 0 if ghost <= 0 else max(1, int(v * ghost))
    # ornament: flip a couple of closed-hat 8ths to open
    if ornament > 0 and "hat" in g and rng is not None:
        g.setdefault("hat_open", [0] * STEPS)
        for i in (6, 14):
            if g["hat"][i] and rng.random() < ornament * 0.5:
                g["hat_open"][i] = g["hat"][i] + 6
                g["hat"][i] = 0
    # double bass: thicken kick with 16th notes on the e/a
    if double_bass > 0 and "kick" in g and rng is not None:
        for i in DOUBLE_BASS_GRID:
            if g["kick"][i] == 0 and rng.random() < double_bass * 0.6:
                g["kick"][i] = 86
    # syncopation: occasionally push an off-1 downbeat kick forward by a 16th
    if syncopation > 0 and "kick" in g and rng is not None:
        for beat in (8, 12):
            if g["kick"][beat] and g["kick"][beat + 2 if beat + 2 < STEPS else beat] == 0:
                if rng.random() < syncopation * 0.4 and beat + 2 < STEPS:
                    g["kick"][beat + 2] = g["kick"][beat]
                    g["kick"][beat] = 0
    return g


def _pick(pool, rng):
    return rng.choice(pool)


def song_from_profile(profile_name, overrides=None):
    if profile_name not in PROFILES:
        raise ValueError(f"Unknown profile '{profile_name}'. "
                         f"Options: {sorted(PROFILES)}")
    prof = PROFILES[profile_name]
    ov = overrides or {}
    arrangement = [("intro", 4, False), ("verse", 8, True), ("chorus", 8, True),
                   ("verse", 8, True), ("chorus", 8, True), ("bridge", 4, True),
                   ("chorus", 8, True)]
    sections = []
    for role, bars, fill in arrangement:
        sec = {"role": role, "bars": bars}
        if fill:
            sec["fill_at_end"] = True
        if role == "chorus":
            sec["crash_in"] = True
        sections.append(sec)
    return {"ppq": 480, "profile": profile_name,
            "tempo": ov.get("tempo", prof["tempo"]),
            "overrides": ov, "sections": sections}


def _resolve_groove(sec, prof, rng, breakdown=0.0):
    if "groove" in sec:
        return sec["groove"]
    role = ROLE_FALLBACK.get(sec.get("role", "verse"), sec.get("role", "verse"))
    if role == "bridge" and breakdown > 0 and rng.random() < breakdown:
        return _pick(BREAKDOWN_POOL, rng)
    pool = prof.get(role) or prof.get("verse")
    return _pick(pool, rng)


def build_song(spec, tempo=None, seed=None):
    rng = random.Random(seed)
    ppq = spec.get("ppq", 480)
    step_ticks = ppq // (STEPS // 4)

    prof = PROFILES.get(spec.get("profile", "pop_punk"), PROFILES["pop_punk"])
    ov = spec.get("overrides", {})
    A = lambda k: ov.get(k, prof.get(k))
    ghost, ornament = A("ghost"), A("ornament")
    double_bass, syncopation = A("double_bass"), A("syncopation")
    breakdown, fill_prob = A("breakdown"), A("fill_prob")
    h = ov.get("humanize", spec.get("humanize", prof["humanize"]))

    events = []
    bar_index = 0
    for sec in spec["sections"]:
        groove_name = _resolve_groove(sec, prof, rng, breakdown=breakdown)
        if groove_name not in GROOVES:
            raise ValueError(f"Unknown groove '{groove_name}'. "
                             f"Options: {sorted(GROOVES)}")
        base = _normalize(GROOVES[groove_name])
        bars = sec.get("bars", 4)
        crash_in = sec.get("crash_in", False)

        want_fill = sec.get("fill") or (sec.get("fill_at_end") and
                                        rng.random() < fill_prob)
        fill_name = sec.get("fill") if isinstance(sec.get("fill"), str) else None
        if want_fill and not fill_name:
            fill_name = _pick(prof["fills"], rng)

        for b in range(bars):
            if want_fill and b == bars - 1:
                groove = _normalize(FILLS[fill_name]())
            else:
                groove = _apply_axes(base, ghost=ghost, ornament=ornament,
                                     double_bass=double_bass,
                                     syncopation=syncopation, rng=rng)
                if crash_in and b == 0:
                    groove = _add_crash_accent(groove)

            bar_start = bar_index * STEPS * step_ticks
            for inst, row in groove.items():
                note = GM[inst]
                for step, vel in enumerate(row):
                    if not vel:
                        continue
                    vjit = int(rng.uniform(-8, 8) * h)
                    tjit = int(rng.uniform(-6, 6) * h)
                    v = max(1, min(127, vel + vjit))
                    t = max(0, bar_start + step * step_ticks + tjit)
                    events.append((t, note, v, step_ticks - 2))
            bar_index += 1

    events.sort(key=lambda e: e[0])
    return events


def write_midi(events, out_path, tempo=170, ppq=480):
    mid = mido.MidiFile(ticks_per_beat=ppq)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(tempo), time=0))
    track.append(mido.MetaMessage("track_name", name="Pop-Punk Drums", time=0))
    timeline = []
    for t, note, vel, dur in events:
        timeline.append((t, "on", note, vel))
        timeline.append((t + dur, "off", note, 0))
    timeline.sort(key=lambda x: (x[0], 0 if x[1] == "off" else 1))
    prev = 0
    for t, kind, note, vel in timeline:
        delta = t - prev
        prev = t
        track.append(mido.Message("note_on" if kind == "on" else "note_off",
                                  channel=9, note=note, velocity=vel, time=delta))
    mid.save(out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser(description="Generate pop-punk drum MIDI.")
    ap.add_argument("--tempo", type=int, default=None)
    ap.add_argument("--out", default="pop_punk_drums.mid")
    ap.add_argument("--profile", default="pop_punk")
    ap.add_argument("--song")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--list-profiles", action="store_true")
    args = ap.parse_args()

    if args.list_profiles:
        for era in ERA_ORDER:
            names = [n for n, p in PROFILES.items() if p["era"] == era]
            if not names:
                continue
            print(f"\n[{era}]")
            for n in names:
                p = PROFILES[n]
                print(f"  {n:18s} tempo~{p['tempo']:>3}  db={p['double_bass']}  "
                      f"brk={p['breakdown']}  sync={p['syncopation']}  "
                      f"ghost={p['ghost']}  orn={p['ornament']}")
        return

    if args.song:
        with open(args.song) as f:
            spec = json.load(f)
    else:
        spec = song_from_profile(args.profile)

    prof_name = spec.get("profile", args.profile)
    prof_default = PROFILES.get(prof_name, PROFILES["pop_punk"])["tempo"]
    tempo = (args.tempo or spec.get("overrides", {}).get("tempo")
             or spec.get("tempo") or prof_default)
    spec["tempo"] = tempo
    events = build_song(spec, tempo=tempo, seed=args.seed)
    write_midi(events, args.out, tempo=tempo, ppq=spec.get("ppq", 480))
    bars = sum(s.get("bars", 4) for s in spec["sections"])
    print(f"Wrote {args.out}: {len(events)} hits, {bars} bars at {tempo} BPM "
          f"[profile={prof_name}].")


if __name__ == "__main__":
    main()
