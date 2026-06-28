"""Kickflip Shuffle drum engine — reused unchanged from the `pop-punk-drums` skill.

The engine is the source of truth for all musical data and generation. The app
layer (controller / UI) calls into these functions; do not port music logic up.
"""
from .generate import (
    PROFILES,
    GROOVES,
    FILLS,
    build_song,
    write_midi,
    song_from_profile,
)

__all__ = [
    "PROFILES",
    "GROOVES",
    "FILLS",
    "build_song",
    "write_midi",
    "song_from_profile",
]
