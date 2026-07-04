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
import os
import random
import re

try:
    import mido
except ImportError:
    raise SystemExit("This script needs mido. Install with: pip install mido")

try:                                    # package import
    from .output_maps import (GENERAL_MIDI, ROLES, OUTPUT_MAPS,
                              list_output_maps, get_output_map)
except ImportError:                      # run directly as a script
    from output_maps import (GENERAL_MIDI, ROLES, OUTPUT_MAPS,
                             list_output_maps, get_output_map)

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

    # Marching / Latin backbeat (Green Day "Holiday" / "American Idiot" bridge)
    "marching": {"hat": _hat8(80, 92),
                 "snare": {2: 42, 4: 110, 6: 44, 10: 42, 12: 110, 14: 46, 15: 40},
                 "kick": {0: 106, 8: 104},
                 "tom_floor": {7: 84, 15: 84}},
    # Garage/Motown stomp (Green Day "Father of All" era) — big loose backbeat
    "garage_stomp": {"hat_open": {2: 92, 6: 92, 10: 92, 14: 92},
                     "snare": {4: 116, 12: 116},
                     "kick": {0: 108, 4: 92, 8: 108, 12: 92}},
    # Linear tom-weave (Dave Douglas-style busy syncopated groove/fill feel)
    "linear_tom": {"hat": _hat16(64, 88),
                   "snare": {4: 104, 10: 58, 12: 104},
                   "kick": {0: 104, 3: 90, 8: 100, 11: 90},
                   "tom_mid": {6: 82, 14: 82}, "tom_low": {7: 80, 15: 80}},

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

    # The namesake: Barker/Purdie half-time shuffle — backbeat on 3 only,
    # swung 16th hats (downbeat + swung "a", "e" dropped for the triplet
    # bounce), ghost-noted snare around the backbeat. Define-only; select it
    # explicitly per section (not wired into a profile pool).
    "half_time_shuffle": {
        "hat": {0: 88, 2: 62, 3: 74, 4: 88, 6: 62, 7: 74,
                8: 88, 10: 62, 11: 74, 12: 88, 14: 62, 15: 74},
        "snare": {3: 34, 7: 40, 8: 116, 11: 34, 15: 38},
        "kick": {0: 108, 10: 96}},
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
def _p(era, tempo, verse, chorus, bridge, intro, fills, eras=None, **axes):
    d = {"era": era, "tempo": tempo, "verse": verse, "chorus": chorus,
         "bridge": bridge, "intro": intro, "fills": fills,
         "ghost": 0.5, "ornament": 0.4, "double_bass": 0.0, "syncopation": 0.0,
         "breakdown": 0.0, "fill_prob": 0.75, "humanize": 1.0,
         "eras": list(eras) if eras else []}
    d.update(axes)
    return d


def _era(label, tempo, verse, chorus, bridge, intro, fills, **axes):
    """One selectable era-block for a profile. Pools are REQUIRED-COMPLETE (no
    partial fallback); only the axis keys that DIFFER from the flat profile need
    be given (the rest inherit via ``profile_view``)."""
    d = {"label": label, "tempo": tempo, "verse": verse, "chorus": chorus,
         "bridge": bridge, "intro": intro, "fills": fills}
    d.update(axes)
    return d


# --- Artist era-blocks (DRAFT musical values — owner refines per era) ----------
# Pools are complete per era; only axes that differ from the flat profile are set.
# Tempo is a (lo, hi) RANGE per era (real songs span one); the default is the
# midpoint and Regenerate re-rolls within it.
_GREEN_DAY_ERAS = [
    _era("Dookie–Nimrod (94–97)", (143, 180),         # Basket Case 170 / Longview 143
         ["verse_basic", "skank", "two_step", "ramones_buzzsaw", "longview_tom"],
         ["chorus_crash", "chorus_open_hat"],
         ["halftime", "longview_tom"], ["verse_basic", "longview_tom"],
         ["tom_descend", "triplet_snare", "marching_toms", "sparse_tom"],
         ghost=0.4, ornament=0.4, fill_prob=0.8),
    _era("Warning (2000)", (130, 150),                # Minority 138
         ["verse_basic", "surf", "two_step", "four_floor"],
         ["chorus_open_hat", "chorus_ride_bell"], ["halftime"],
         ["verse_basic", "surf"],
         ["sparse_tom", "snare_buildup", "tom_descend"],
         ghost=0.3, ornament=0.45, fill_prob=0.55),
    _era("American Idiot–21st Century Breakdown (04–09)", (90, 186),  # AI 186 / ballads
         ["verse_basic", "verse_doubles", "tribal_toms", "marching", "ramones_buzzsaw"],
         ["chorus_crash", "chorus_doublebass", "chorus_ride_bell"],
         ["halftime", "tribal_toms", "marching", "gang_break"],
         ["verse_basic", "marching"],
         ["marching_toms", "tom_descend", "tom_around", "triplet_snare"],
         ghost=0.5, ornament=0.6, syncopation=0.3, fill_prob=0.85, humanize=0.9),
    _era("¡Uno!–Revolution Radio (12–16)", (75, 150),  # Still Breathing 75 / Bang Bang 127
         ["verse_basic", "four_floor", "skank", "surf", "ramones_buzzsaw"],
         ["chorus_crash", "chorus_open_hat"], ["halftime", "two_step"],
         ["verse_basic", "four_floor"],
         ["tom_descend", "triplet_snare", "snare_buildup"],
         ghost=0.4, ornament=0.4, fill_prob=0.7),
    _era("Father of All (2020)", (130, 170),          # garage-feel, Father of All 167
         ["garage_stomp", "four_floor", "disco_punk", "two_step"],
         ["garage_stomp", "chorus_crash"], ["halftime", "garage_stomp"],
         ["garage_stomp", "four_floor"],
         ["sparse_tom", "snare_buildup"],
         ghost=0.3, ornament=0.3, syncopation=0.3, fill_prob=0.5, humanize=1.0),
    _era("Saviors (2024)", (130, 180),                # American Dream 143 / Look Ma fast
         ["verse_basic", "two_step", "skank", "longview_tom", "ramones_buzzsaw"],
         ["chorus_crash", "chorus_ride_bell"], ["halftime", "tribal_toms", "marching"],
         ["verse_basic", "longview_tom"],
         ["tom_descend", "marching_toms", "triplet_snare"],
         ghost=0.45, ornament=0.5, fill_prob=0.8, humanize=0.95),
]

_RELIENT_K_ERAS = [
    # 1) debut — Stephen Cushman: raw, fast, simple ska-punk.
    _era("Relient K (2000) — Cushman", (165, 195),
         ["skank", "verse_basic", "two_step", "ramones_buzzsaw", "surf"],
         ["chorus_crash", "chorus_open_hat"], ["ska_punk", "halftime"],
         ["verse_basic", "surf"],
         ["snare_buildup", "tom_descend", "ramones_crash"],
         ghost=0.25, ornament=0.3, fill_prob=0.55, humanize=1.0),
    # 2) Anatomy–Two Lefts — Dave Douglas (early): tight ska-punk, quick fills.
    _era("Anatomy–Two Lefts (01–03) — Douglas", (160, 180),   # Sadie Hawkins 167
         ["skank", "ska_punk", "two_step", "verse_doubles", "surf"],
         ["chorus_crash", "chorus_open_hat"], ["ska_punk", "halftime"],
         ["verse_basic", "surf"],
         ["triplet_snare", "tom_descend", "marching_toms"],
         ghost=0.4, ornament=0.55, syncopation=0.35, fill_prob=0.85),
    # 3) Mmhmm–Five Score — Douglas (mature): technical/linear, dynamic, WIDE tempo.
    _era("Mmhmm–Five Score (04–07) — Douglas", (110, 170),    # Be My Escape 112!
         ["verse_basic", "verse_16th", "linear_tom", "four_floor", "emo_syncopated"],
         ["chorus_crash", "chorus_ride_bell", "chorus_open_hat"],
         ["halftime", "emo_syncopated", "linear_tom"], ["verse_basic", "surf"],
         ["triplet_snare", "tom_descend", "linear", "marching_toms"],
         ghost=0.55, ornament=0.7, syncopation=0.5, double_bass=0.2, fill_prob=0.85,
         humanize=0.9),
    # 4) FANSD — Ethan Luck: solid rock pocket, less busy than Douglas, tighter.
    _era("Forget and Not Slow Down (2009) — Ethan Luck", (140, 170),  # FANSD 167
         ["verse_basic", "verse_doubles", "four_floor", "two_step"],
         ["chorus_crash", "chorus_ride_bell"], ["halftime", "breakdown_chug"],
         ["verse_basic", "four_floor"],
         ["triplet_snare", "tom_descend", "snare_buildup"],
         ghost=0.4, ornament=0.45, syncopation=0.3, fill_prob=0.7, humanize=0.9),
]

_RAMONES_ERAS = [
    # 1) Tommy: foundation buzzsaw, purest + least ornamented, minimal fills.
    _era("Buzzsaw (76–78) — Tommy", (165, 205),        # Blitzkrieg Bop 180 / Judy fast
         ["ramones_buzzsaw", "two_step", "verse_basic"],
         ["chorus_crash", "ramones_buzzsaw"], ["halftime"],
         ["ramones_buzzsaw"],
         ["ramones_crash", "tom_descend"],
         ghost=0.05, ornament=0.1, fill_prob=0.35),
    # 2) Marky I: harder hitter, tighter rock backbeat, more fills.
    _era("Rock'n'Roll (78–82) — Marky I", (145, 185),  # I Wanna Be Sedated 145
         ["ramones_buzzsaw", "two_step", "verse_basic", "verse_ride"],
         ["chorus_crash", "chorus_open_hat"], ["halftime", "surf"],
         ["verse_basic"],
         ["tom_around", "tom_descend", "snare_buildup"],
         ghost=0.15, ornament=0.25, fill_prob=0.55),
    # 3) Richie: fastest + most aggressive, hardcore-influenced.
    _era("Hardcore (83–87) — Richie", (195, 245),      # Wart Hog blazing
         ["ramones_buzzsaw", "dbeat", "two_step", "blast_beat"],
         ["chorus_crash", "ramones_buzzsaw"], ["halftime", "dbeat"],
         ["dbeat"],
         ["dbeat_roll", "snare_buildup", "tom_descend"],
         ghost=0.1, ornament=0.15, fill_prob=0.6),
    # 4) Marky II: return, wider dynamics, some moody mid-tempo.
    _era("Return (87–96) — Marky II", (135, 185),      # Pet Sematary 130-ish / Poison Heart
         ["verse_basic", "two_step", "surf", "ramones_buzzsaw"],
         ["chorus_crash", "chorus_ride_bell"], ["halftime", "surf"],
         ["verse_basic", "surf"],
         ["tom_descend", "tom_around", "ramones_crash"],
         ghost=0.2, ornament=0.3, fill_prob=0.5),
]

_OFFSPRING_ERAS = [
    # 1) Welty I: raw fast skate-punk, aggressive + driving.
    _era("Skate (92–97) — Welty I", (150, 205),        # Come Out and Play 165 / Bad Habit
         ["verse_basic", "ramones_buzzsaw", "two_step", "skank", "surf"],
         ["chorus_crash", "chorus_open_hat"], ["halftime", "skank"],
         ["surf", "verse_basic"],
         ["tom_descend", "snare_buildup", "dbeat_roll"],
         ghost=0.3, ornament=0.3, fill_prob=0.6),
    # 2) Welty II: radio pop-punk, polished, ska/novelty detours, wider dynamics.
    _era("Americana (98–03) — Welty II", (100, 170),   # Kids Aren't Alright 160 / Pretty Fly 110
         ["verse_basic", "disco_punk", "ska_punk", "four_floor", "surf"],
         ["chorus_crash", "chorus_ride_bell"], ["halftime", "ska_punk"],
         ["verse_basic", "surf"],
         ["triplet_snare", "tom_around", "tom_descend"],
         ghost=0.45, ornament=0.5, syncopation=0.3, fill_prob=0.7),
    # 3) Parada: tighter, arena-produced, controlled power.
    _era("Modern (08–21) — Parada", (130, 195),        # Go Far Kid 140 / Hammerhead 190
         ["verse_basic", "verse_doubles", "four_floor", "two_step"],
         ["chorus_crash", "chorus_doublebass"], ["halftime", "breakdown_chug"],
         ["verse_basic", "four_floor"],
         ["tom_descend", "marching_toms", "snare_buildup"],
         ghost=0.4, ornament=0.4, fill_prob=0.65, humanize=0.9),
]


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
                  ghost=0.1, ornament=0.2, fill_prob=0.5, humanize=1.0,
                  eras=_RAMONES_ERAS),

    # --- '90s skate / melodic punk ---
    "tre_cool": _p("90s_skate", 180,
                   ["verse_basic", "surf", "skank", "longview_tom", "verse_basic"],
                   ["chorus_ride_bell", "chorus_crash"],
                   ["halftime", "longview_tom", "half_time_shuffle"],
                   ["verse_basic", "ramones_buzzsaw"],
                   ["marching_toms", "tom_descend", "triplet_snare", "sparse_tom",
                    "halfbar_toms"],
                   ghost=0.6, ornament=0.6, fill_prob=0.85,
                   eras=_GREEN_DAY_ERAS),
    "offspring": _p("90s_skate", 172,
                    ["surf", "skank", "verse_basic", "two_step"],
                    ["chorus_crash", "chorus_open_hat"], ["halftime", "skank"],
                    ["surf", "verse_basic"],
                    ["tom_descend", "triplet_snare", "ramones_crash"],
                    ghost=0.4, ornament=0.4, fill_prob=0.7, eras=_OFFSPRING_ERAS),
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
                 ["chorus_crash", "chorus_open_hat"],
                 ["halftime", "skank", "half_time_shuffle"],
                 ["verse_doubles", "verse_16th"],
                 ["triplet_snare", "tom_descend", "marching_toms", "snare_buildup",
                  "halfbar_toms"],
                 ghost=1.0, ornament=1.0, fill_prob=0.95, humanize=0.8),
    "good_charlotte": _p("2000s_mall", 158,
                         ["verse_basic", "four_floor", "verse_basic"],
                         ["chorus_crash", "four_floor"], ["halftime"],
                         ["verse_basic", "four_floor"],
                         ["snare_buildup", "tom_descend"],
                         ghost=0.4, ornament=0.3, syncopation=0.2, fill_prob=0.7),
    "simple_plan": _p("2000s_mall", 162,
                      ["verse_basic", "surf", "four_floor"],
                      ["chorus_crash", "chorus_open_hat"], ["halftime"],
                      ["verse_basic", "surf"], ["snare_buildup", "tom_descend"],
                      ghost=0.3, ornament=0.45, fill_prob=0.7, humanize=0.7),
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
                       ghost=0.4, ornament=0.5, syncopation=0.3, fill_prob=0.75,
                       humanize=0.8),
    # Relient K — melodic/technical pop-punk through *Forget and Not Slow Down*
    # (2009): busy Dave-Douglas fills, early ska bridge, syncopated melodic feel.
    "relient_k": _p("2000s_mall", 172,
                    ["verse_16th", "verse_doubles", "surf", "two_step"],
                    ["chorus_crash", "chorus_open_hat", "chorus_ride_bell"],
                    ["halftime", "ska_punk", "emo_syncopated"],
                    ["verse_basic", "surf"],
                    ["triplet_snare", "tom_descend", "marching_toms", "linear",
                     "snare_buildup"],
                    ghost=0.5, ornament=0.7, syncopation=0.5, double_bass=0.2,
                    fill_prob=0.85, humanize=1.0, eras=_RELIENT_K_ERAS),

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


def song_from_profile(profile_name, overrides=None, era=None):
    if profile_name not in PROFILES:
        raise ValueError(f"Unknown profile '{profile_name}'. "
                         f"Options: {sorted(PROFILES)}")
    prof = profile_view(profile_name, era)      # era tempo/pools; flat when era=None
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
    # The final section has nothing to transition into — a trailing fill would
    # "fill into silence" (the audible "goes off the rails at the end"). End on the
    # groove instead.
    sections[-1].pop("fill_at_end", None)
    # An era may carry a (lo, hi) tempo RANGE (real songs span one); default to the
    # midpoint and remember the range so `regenerate` can re-roll within it. A flat
    # profile keeps a single int tempo.
    base_tempo = prof["tempo"]
    tempo_range = None
    if isinstance(base_tempo, (tuple, list)):
        lo, hi = int(base_tempo[0]), int(base_tempo[1])
        tempo_range = [lo, hi]
        base_tempo = (lo + hi) // 2
    spec = {"ppq": 480, "profile": profile_name,
            "tempo": ov.get("tempo", base_tempo),
            "overrides": ov, "sections": sections}
    if era:
        spec["era"] = era          # only writer of spec['era']; tempo co-written above
    if tempo_range:
        spec["tempo_range"] = tempo_range
    return spec


def _resolve_groove(sec, prof, rng, breakdown=0.0):
    if "groove" in sec:
        return sec["groove"]
    role = ROLE_FALLBACK.get(sec.get("role", "verse"), sec.get("role", "verse"))
    if role == "bridge" and breakdown > 0 and rng.random() < breakdown:
        return _pick(BREAKDOWN_POOL, rng)
    pool = prof.get(role) or prof.get("verse")
    return _pick(pool, rng)


def _effective_axes(sec, glob):
    """Merge a section's optional `axes` over the global axis values, per key.

    `glob` is the dict of global (overrides->profile) axis values. A section
    that omits `axes` (or a key within it) inherits the global value verbatim,
    so the global-only path stays byte-identical. humanize's global value
    already carries its 3-tier (overrides->spec->profile) resolution; a section
    may override it on top.
    """
    sax = sec.get("axes", {})
    return {k: sax.get(k, glob[k]) for k in glob}


def _resolved_bar_rows(base, sec, b, bars, want_fill, fill_name, ax, rng):
    """Resolve a single bar's pattern dict, PRE humanize-jitter.

    Scope is deliberately narrow: normalize + _apply_axes + optional crash
    accent only. Groove/fill selection (the per-section draws) happen in the
    caller, ONCE per section. `rng` is the caller's stream (never created here),
    so draw order/count is preserved.
    """
    if want_fill and b == bars - 1:
        return _normalize(FILLS[fill_name]())
    groove = _apply_axes(base, ghost=ax["ghost"], ornament=ax["ornament"],
                         double_bass=ax["double_bass"],
                         syncopation=ax["syncopation"], rng=rng)
    if sec.get("crash_in", False) and b == 0:
        groove = _add_crash_accent(groove)
    return groove


def _validate_pattern(rows):
    """Validate an edited-grid pattern override: {inst: [STEPS vels]}.

    Raises ValueError (never clamps/silently fixes) on a bad instrument, wrong
    row length, non-int, or out-of-range velocity. An empty dict or all-zero
    rows are legal (a silent bar).
    """
    if not isinstance(rows, dict):
        raise ValueError("pattern must be a dict of inst -> velocity list")
    for inst, row in rows.items():
        if inst not in GM:
            raise ValueError(f"unknown instrument '{inst}' (not in GM)")
        if not isinstance(row, (list, tuple)) or len(row) != STEPS:
            raise ValueError(f"pattern row for '{inst}' must be length {STEPS}")
        for v in row:
            if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 127:
                raise ValueError(
                    f"velocity {v!r} for '{inst}' must be an int in 0..127")
    return rows


def _bar_override(sec, b):
    """Return a section's edited-grid override for bar `b`, or None.

    PURE dict lookup — makes ZERO rng draws and does not alter control flow on
    the None path; the byte-identical golden guarantee depends on this (a spec
    with no `patterns` is exactly today's flow). Bar keys are accepted as int or
    str (JSON/.ppd round-trip); a DEEP copy is returned so callers never alias
    the stored spec rows.
    """
    patterns = sec.get("patterns")
    if not patterns:
        return None
    if b in patterns:
        rows = patterns[b]
    elif str(b) in patterns:
        rows = patterns[str(b)]
    else:
        return None
    _validate_pattern(rows)
    return {inst: list(row) for inst, row in rows.items()}


# Per-section "feel" -> integer (numerator, denominator) bar/step time-scale.
# normal = 1x, half = bars twice as long, double = bars half as long. Kept as
# integer ratios so ticks stay exact (ppq must be divisible by 8 for `double`).
_FEEL = {"normal": (1, 1), "half": (2, 1), "double": (1, 2)}


def profile_view(profile_name, era=None):
    """Effective profile dict for a spec: the selected era-block merged over the
    flat profile, or the flat profile itself when no era is chosen.

    `era=None` (or an unknown/absent era) returns the flat `PROFILES` object
    UNCHANGED — the byte-identity guarantee for the default path. An era returns a
    NEW merged dict (never mutates `PROFILES`): the era-block's complete pools +
    tempo + any axes it overrides, with unspecified axes inheriting the flat
    profile."""
    prof = PROFILES.get(profile_name, PROFILES["pop_punk"])
    if not era:
        return prof
    block = next((b for b in prof.get("eras", []) if b.get("label") == era), None)
    if block is None:
        return prof
    view = dict(prof)
    view.update(block)              # era pools (complete) + tempo + overridden axes
    return view


def _iter_bars(spec, rng, omap):
    """Drive the full per-section / per-bar resolution off a single rng stream.

    Yields `(bar_index, rows, bar_events)` where `rows` is the bar's pattern
    dict PRE-jitter and `bar_events` are its `(t, note, vel, dur)` tuples. Both
    `build_song` (events) and `resolved_bar` (rows) consume this generator, so
    they see an identical draw sequence by construction — the basis of the
    byte-identical guarantee and the resolved_bar==rendered-bar mirror.
    """
    ppq = spec.get("ppq", 480)
    step_ticks = ppq // (STEPS // 4)
    prof = profile_view(spec.get("profile", "pop_punk"), spec.get("era"))
    ov = spec.get("overrides", {})
    A = lambda k: ov.get(k, prof.get(k))
    glob = {"ghost": A("ghost"), "ornament": A("ornament"),
            "double_bass": A("double_bass"), "syncopation": A("syncopation"),
            "breakdown": A("breakdown"), "fill_prob": A("fill_prob"),
            "humanize": ov.get("humanize", spec.get("humanize",
                                                    prof["humanize"]))}

    bar_index = 0
    bar_start = 0                        # cumulative tick start (bars vary with feel)
    for sec_index, sec in enumerate(spec["sections"]):
        ax = _effective_axes(sec, glob)
        groove_name = _resolve_groove(sec, prof, rng, breakdown=ax["breakdown"])
        if groove_name not in GROOVES:
            raise ValueError(f"Unknown groove '{groove_name}'. "
                             f"Options: {sorted(GROOVES)}")
        base = _normalize(GROOVES[groove_name])
        bars = sec.get("bars", 4)

        # Per-section feel time-scale (normal => identical to today, byte-for-byte).
        num, den = _FEEL.get(sec.get("feel", "normal"), (1, 1))
        sstep = max(1, step_ticks * num // den)          # scaled step spacing
        sbar = STEPS * step_ticks * num // den           # scaled bar width
        note_dur = max(1, sstep - 2)

        want_fill = sec.get("fill") or (sec.get("fill_at_end") and
                                        rng.random() < ax["fill_prob"])
        fill_name = sec.get("fill") if isinstance(sec.get("fill"), str) else None
        if want_fill and not fill_name:
            fill_name = _pick(prof["fills"], rng)

        for b in range(bars):
            override = _bar_override(sec, b)
            if override is not None:
                rows = override          # verbatim edited pattern; skip groove/axes
            else:
                rows = _resolved_bar_rows(base, sec, b, bars, want_fill,
                                          fill_name, ax, rng)
            h = ax["humanize"]
            bar_events = []
            for inst, row in rows.items():
                note = omap[inst]
                for step, vel in enumerate(row):
                    if not vel:
                        continue
                    vjit = int(rng.uniform(-8, 8) * h)
                    tjit = int(rng.uniform(-6, 6) * h)
                    v = max(1, min(127, vel + vjit))
                    t = max(0, bar_start + step * sstep + tjit)
                    bar_events.append((t, note, v, note_dur))
            yield sec_index, bar_index, groove_name, fill_name, rows, bar_events
            bar_index += 1
            bar_start += sbar


def build_song(spec, tempo=None, seed=None, output_map=None):
    rng = random.Random(seed)
    omap = output_map if output_map is not None else GENERAL_MIDI
    events = []
    for *_head, bar_events in _iter_bars(spec, rng, omap):
        events.extend(bar_events)
    events.sort(key=lambda e: e[0])
    return events


def resolved_bar(spec, section_index, bar_index, seed=None, output_map=None):
    """Return the PRE-jitter pattern dict (inst -> [16 vels]) for one bar,
    exactly as `build_song` renders it at the same (section, bar) position.

    For the UI sequencer: the editable pattern is the real one build_song uses
    (MIRROR contract). `output_map` is accepted for symmetry but does not affect
    rows (it only resolves note numbers in events).
    """
    sections = spec["sections"]
    if not 0 <= section_index < len(sections):
        raise IndexError(f"section_index {section_index} out of range "
                         f"(0..{len(sections) - 1})")
    sec_bars = sections[section_index].get("bars", 4)
    if not 0 <= bar_index < sec_bars:
        raise IndexError(f"bar_index {bar_index} out of range for section "
                         f"{section_index} (0..{sec_bars - 1})")
    target = sum(s.get("bars", 4) for s in sections[:section_index]) + bar_index

    # Rows are pre-jitter patterns independent of the note mapping; drive the
    # generator with the always-complete default map so a partial custom
    # `output_map` can never KeyError here (the param is accepted for API
    # symmetry only and does not affect rows).
    rng = random.Random(seed)
    for _si, bi, _g, _f, rows, _ev in _iter_bars(spec, rng, GENERAL_MIDI):
        if bi == target:
            return rows
    raise IndexError(f"bar {target} not produced")  # pragma: no cover


def resolved_section_grooves(spec, seed=None):
    """`[{'groove': name, 'fill': fill_or_None}]` — the seed-resolved pick per
    section, exactly as `build_song` renders it under `seed`. Used by section-lock
    to pin a locked section's current choice before a reseed."""
    rng = random.Random(seed)
    out = [None] * len(spec.get("sections", []))     # index-aligned to sections
    for si, _bi, groove_name, fill_name, _rows, _ev in _iter_bars(spec, rng,
                                                                   GENERAL_MIDI):
        if out[si] is None:                          # first bar of the section
            out[si] = {"groove": groove_name, "fill": fill_name}
    return out                                       # bars=0 sections stay None


def compute_section_markers(spec):
    """`[(tick, label)]` at each section's start, for DAW-timeline markers. Label =
    section ``label`` -> ``role`` -> ``groove`` -> ``"section N"``. Purely
    positional (mirrors ``_iter_bars`` bar math); does NOT affect ``build_song``
    output — markers are written only when passed to ``write_midi``."""
    ppq = spec.get("ppq", 480)
    step_ticks = ppq // (STEPS // 4)
    markers = []
    tick = 0                                    # cumulative (bars vary with feel)
    for i, sec in enumerate(spec.get("sections", [])):
        label = (sec.get("label") or sec.get("role") or sec.get("groove")
                 or f"section {i + 1}")
        markers.append((tick, str(label)))
        num, den = _FEEL.get(sec.get("feel", "normal"), (1, 1))
        tick += int(sec.get("bars", 4)) * STEPS * step_ticks * num // den
    return markers


def write_midi(events, out_path, tempo=170, ppq=480, markers=None):
    mid = mido.MidiFile(ticks_per_beat=ppq)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(tempo), time=0))
    track.append(mido.MetaMessage("track_name", name="Pop-Punk Drums", time=0))
    # (tick, priority, kind, a, b): priority orders same-tick events — markers (−1)
    # then note-offs (0) then note-ons (1), preserving the original off-before-on
    # ordering so the default (markers=None) output stays byte-identical.
    timeline = []
    for t, note, vel, dur in events:
        timeline.append((t, 1, "on", note, vel))
        timeline.append((t + dur, 0, "off", note, 0))
    for t, label in (markers or []):
        timeline.append((t, -1, "marker", label, 0))
    timeline.sort(key=lambda x: (x[0], x[1]))
    prev = 0
    for t, _pri, kind, a, b in timeline:
        delta = t - prev
        prev = t
        if kind == "marker":
            track.append(mido.MetaMessage("marker", text=str(a), time=delta))
        else:
            track.append(mido.Message("note_on" if kind == "on" else "note_off",
                                      channel=9, note=a, velocity=b, time=delta))
    mid.save(out_path)
    return out_path


# ---------------------------------------------------------------------------
# Library helpers (read-only, for the controller / UI)
# ---------------------------------------------------------------------------
_DOCS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "references", "grooves.md")
_AXIS_KEYS = ("ghost", "ornament", "double_bass", "syncopation",
              "breakdown", "fill_prob", "humanize")


def _parse_doc_descriptions(path=_DOCS_PATH):
    """Parse `references/grooves.md` -> ({groove: desc}, {fill: desc}).

    Grooves are `### name — desc` (§3 headings); fills are `- **name** — desc`
    (§4 bullets). The em dash (—) is the field separator.
    """
    grooves, fills = {}, {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^###\s+(\w+)\s+—\s+(.+?)\s*$", line)
                if m:
                    grooves[m.group(1)] = m.group(2)
                    continue
                m = re.match(r"^-\s+\*\*(\w+)\*\*\s+—\s+(.+?)\s*$", line)
                if m:
                    fills[m.group(1)] = m.group(2)
    except FileNotFoundError:
        pass
    return grooves, fills


def list_profiles():
    """[{name, era, tempo, axes:{...7...}, eras:[labels]}] in definition order.
    `eras` is the selectable era labels (empty for flat profiles)."""
    return [{"name": n, "era": p["era"], "tempo": p["tempo"],
             "axes": {k: p[k] for k in _AXIS_KEYS},
             "eras": [b["label"] for b in p.get("eras", [])]}
            for n, p in PROFILES.items()]


def list_grooves():
    """[{name, description}] for every GROOVES key (description from grooves.md)."""
    desc, _ = _parse_doc_descriptions()
    return [{"name": n, "description": desc.get(n)} for n in GROOVES]


def list_fills():
    """[{name, description}] for every FILLS key (description from grooves.md)."""
    _, desc = _parse_doc_descriptions()
    return [{"name": n, "description": desc.get(n)} for n in FILLS]


_GROOVE_ROLE_KEYS = ("verse", "chorus", "bridge", "intro")


def groove_usage():
    """Reverse-map every GROOVES + FILLS name to how the profiles use it.

    {name: {"roles": [...], "profiles": [...], "eras": [...]}} where grooves draw
    roles from the verse/chorus/bridge/intro pools and fills carry role "fill".
    Names present in no profile pool come back with empty lists (orphans). Used by
    the UI groove browser for role grouping + the "Used by" badge.
    """
    usage = {n: {"roles": set(), "profiles": [], "eras": set()}
             for n in list(GROOVES) + list(FILLS)}
    for pname, prof in PROFILES.items():
        # Scan the flat profile AND every era-block, so era-only grooves count.
        holders = [(prof["era"], prof)]
        holders += [(b.get("label", prof["era"]), b) for b in prof.get("eras", [])]
        for tag, holder in holders:
            for role in _GROOVE_ROLE_KEYS:
                for gname in holder.get(role, []):
                    u = usage[gname]
                    u["roles"].add(role)
                    u["eras"].add(tag)
                    if pname not in u["profiles"]:
                        u["profiles"].append(pname)
            for fname in holder.get("fills", []):
                u = usage[fname]
                u["roles"].add("fill")
                u["eras"].add(tag)
                if pname not in u["profiles"]:
                    u["profiles"].append(pname)
    order = {n: i for i, n in enumerate(_GROOVE_ROLE_KEYS + ("fill",))}
    return {n: {"roles": sorted(u["roles"], key=lambda r: order[r]),
                "profiles": u["profiles"],
                "eras": sorted(u["eras"])}
            for n, u in usage.items()}


def note_ladder_events(output_map=None, ppq=480, vel=100):
    """One hit per symbolic role, in ROLES order, one beat apart."""
    omap = output_map if output_map is not None else GENERAL_MIDI
    return [(i * ppq, omap[role], vel, ppq // 2)
            for i, role in enumerate(ROLES)]


def write_note_ladder(out_path, output_map=None, tempo=120, ppq=480):
    """Emit a .mid striking each of the 17 roles once (ROLES order, one per
    beat). Drag into a sampler (e.g. EZ Drummer 3) to validate which
    articulation each role triggers under a given output map — the way to
    verify EZ_DRUMMER_3's UNVERIFIED note numbers."""
    return write_midi(note_ladder_events(output_map, ppq=ppq), out_path,
                      tempo=tempo, ppq=ppq)


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
