"""PySide6 UI layer for Kickflip Shuffle.

Widgets are thin: they render from and drive the in-process `Controller`; they
never touch the engine or playback directly. Phase 5a-i ships the app shell + a
Generate-view core (profile -> generate -> play -> export).
"""
