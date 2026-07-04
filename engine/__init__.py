"""Kickflip Shuffle drum engine — reused from the `pop-punk-drums` skill,
extended in Phase 1 (output maps, per-section axes, resolved_bar, list helpers).

The engine is the source of truth for all musical data and generation. The app
layer (controller / UI) calls into these functions; do not port music logic up.
"""
from .generate import (
    PROFILES,
    GROOVES,
    FILLS,
    GM,
    build_song,
    write_midi,
    song_from_profile,
    resolved_bar,
    _validate_pattern,
    list_profiles,
    list_grooves,
    list_fills,
    groove_usage,
    compute_section_markers,
    resolved_section_grooves,
    profile_view,
    note_ladder_events,
    write_note_ladder,
)
from .output_maps import (
    GENERAL_MIDI,
    EZ_DRUMMER_3,
    OUTPUT_MAPS,
    ROLES,
    list_output_maps,
    get_output_map,
)

__all__ = [
    "PROFILES",
    "GROOVES",
    "FILLS",
    "GM",
    "build_song",
    "write_midi",
    "song_from_profile",
    "resolved_bar",
    "_validate_pattern",
    "list_profiles",
    "list_grooves",
    "list_fills",
    "groove_usage",
    "compute_section_markers",
    "resolved_section_grooves",
    "profile_view",
    "note_ladder_events",
    "write_note_ladder",
    "GENERAL_MIDI",
    "EZ_DRUMMER_3",
    "OUTPUT_MAPS",
    "ROLES",
    "list_output_maps",
    "get_output_map",
]
