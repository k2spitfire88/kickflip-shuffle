# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

**Kickflip Shuffle** — a planned self-contained macOS `.app` that wraps an existing Python pop-punk drum **MIDI** engine in a native PySide6 GUI. The app builds/auditions the drum *pattern*; the user's DAW/sampler (EZ Drummer 3 etc.) makes the final *sound*. Output is always a `.mid` dragged onto a DAW track.

**As of now: planning + branding are complete; no application code exists.** The only real code is `engine/` (reused unchanged). `app/`, `main.py`, `setup.py`, and tests are *not written yet*. Before building, read `docs/HANDOFF.md` then `docs/BUILD_PLAN.md` — they hold the locked decisions and the phased plan that drive everything.

Not a git repo yet (Phase 0 does `git init`).

## Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # mido, librosa, pyfluidsynth, PySide6, py2app, ...

# Run the engine CLI (only runnable entry point today)
python engine/generate.py --list-profiles
python engine/generate.py --profile pop_punk --tempo 170 --seed 1 --out out.mid
python engine/generate.py --song spec.json --out out.mid   # spec = JSON song spec

# Once the app lands (Phase 1/5): python main.py
```

`libfluidsynth` is a native dependency for playback (`brew install fluid-synth`); the GM soundfont (`FluidR3_GM.sf2`) is downloaded separately into `assets/soundfonts/` (gitignored, ~140MB). Neither is needed to run the engine CLI.

No test suite exists yet — Phase 1 adds the first one (golden spec → deterministic events; `GENERAL_MIDI` output must stay byte-identical to current engine output as a regression guard).

## Architecture

Two layers, strictly separated:

- **`engine/` — the source of truth. Reuse, do not rewrite.** All musical data and generation logic lives here. The app layer calls into it; never port music logic up into the app. `engine/__init__.py` re-exports the public API.
- **`app/` (to be built) — controller + UI only.** In-process Python calls into the engine (no JS↔Python bridge). Planned: `controller.py` (UI-facing API), `analyze.py` (librosa audio→spec, F2), `playback.py` (pyfluidsynth render/transport, F4), `ui/` (PySide6 widgets).

### Engine API (`engine/generate.py`)

- `PROFILES` (20 named profiles: era, tempo, per-role groove pools, fill pool, axes), `GROOVES` (~26 one-bar 16-step patterns), `FILLS` (~13), `GM` (drum-name→note map), `STEPS=16`.
- `song_from_profile(name, overrides=None) -> spec`
- `build_song(spec, tempo=None, seed=None) -> events` — each event is `(tick, note, vel, dur)`.
- `write_midi(events, out_path, tempo=170, ppq=480) -> path`
- Spec schema: `{ppq, profile, tempo, overrides:{axes...}, sections:[{role|groove, bars, fill|fill_at_end, crash_in}]}`
- Axes: `ghost, ornament, double_bass, syncopation, breakdown, fill_prob, humanize`.

### Critical engine invariants (do not break)

- **`build_song`'s `tempo` param is inert** — event timing comes from `ppq`, not tempo. Tempo applies only at `write_midi`/playback. Always source it from `spec["tempo"]`.
- Drums emit on **MIDI channel 9** (GM channel 10).
- `seed` is the only source of randomness — plumb it through for reproducible regenerate.

### Planned additive engine extensions (Phase 1 — extend, never rewrite)

These are flagged in `BUILD_PLAN.md` and must keep the default path byte-identical to today's output:
1. **Per-section axes** — let each `section` carry optional `axes:{}` overriding the globals read at `generate.py:528–532`. **Confirm the per-section axes shape with the owner before touching `build_song`.**
2. **Symbolic notes + output-map layer** — `build_song` currently bakes GM notes (`generate.py:563`). Carry the symbolic `inst` role in the event and resolve to MIDI at write time via a selected map. Add `engine/output_maps.py` with `GENERAL_MIDI` (default, pass-through baseline) + `EZ_DRUMMER_3`. New maps are data, not code.
3. **Editable grid rows** — expose the resolved groove dict (post-axes/normalize, **pre-humanize-jitter**) so the UI sequencer edits the real pattern; events stay for playback/export only.
4. **`half_time_shuffle` groove** — the app is named for the Barker half-time shuffle; audit `GROOVES`, add it if absent, wire to `barker`/`tre_cool` pools.

## Conventions

- Engine functions/data and CLI live in one file (`engine/generate.py`); groove/fill descriptions are in `engine/references/grooves.md` (the planned UI list helpers source descriptions from there).
- Key art is **LOCKED** (`assets/art/keyart.svg` is the master; `assets/icon/KickflipShuffle.icns` is the app icon). Re-bake steps are in `docs/HANDOFF.md` §5.
- Before bundling third-party assets, license-verify: FluidR3_GM (MIT) and the four OFL fonts (Space Grotesk, IBM Plex Mono, Special Elite, Saira Stencil One).
