"""Kickflip Shuffle application layer — controller + (later) UI.

The app layer is a thin in-process client of the `engine` package: it
orchestrates engine calls and holds UI-facing state. All musical data and
generation logic live in `engine`; never port music logic up into `app`.
"""
from .controller import Controller

__all__ = ["Controller"]
