# Kickflip Shuffle

A self-contained macOS app that generates pop-punk drum **MIDI** to drag onto an
EZ Drummer 3 (or any DAW) track. The app builds and auditions the *pattern*; your
DAW/sampler produces the final *sound*.

Native PySide6 UI over the existing Python drum engine, packaged as a double-click
`.app`.

- **Status:** planned + branded; no app code yet. See [`docs/HANDOFF.md`](docs/HANDOFF.md).
- **Build plan:** [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md).
- **Engine:** [`engine/`](engine/) — reused unchanged from the `pop-punk-drums` skill.

## Quick start (once Phase 0/1 land)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

`libfluidsynth` is a native dependency (`brew install fluid-synth`) and the GM
soundfont is downloaded separately — see HANDOFF.
