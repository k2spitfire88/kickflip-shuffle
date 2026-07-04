# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

**Kickflip Shuffle** — a planned self-contained macOS `.app` that wraps an existing Python pop-punk drum **MIDI** engine in a native PySide6 GUI. The app builds/auditions the drum *pattern*; the user's DAW/sampler (EZ Drummer 3 etc.) makes the final *sound*. Output is always a `.mid` dragged onto a DAW track.

**As of 2026-07-03: Phases 0–6 are done and pushed** (git repo on GitHub `k2spitfire88/kickflip-shuffle`, branch `main`; Phase 6 = 6a persistence/export + 6b undo/redo; the playhead is the one Phase 6 item deferred to Phase 8). Built so far:
- `engine/` — reused + extended (output maps, per-section axes, `resolved_bar`, list helpers, note-ladder, `groove_usage`).
- `app/controller.py` — stateful `Controller` (the UI-facing API).
- `app/analyze.py` — librosa audio → editable `AnalysisResult` → spec (F2).
- `app/playback.py` — pyfluidsynth offline render + `sounddevice` transport + context mix (F4).
- `app/ui/` — PySide6 shell + full Generate view (arrangement timeline + per-section editor + 16-step `QPainter` grid), Drop-audio view, Groove browser, `.ppd` persistence + recent files + export folder/Save-As/Reveal + undo/redo (`main.py`, `theme.py`, `generate_view.py`, `editor_widgets.py`, `drop_view.py`, `browser_view.py`, `settings.py`, `main_window.py`).
- Persistence: `Controller.save_project`/`load_project` (`.ppd` = version+spec+seed+output_map+UI extras); `app/ui/settings.py` `Prefs` over QSettings. Undo/redo = deep-copied spec-snapshot stack in the controller.
- Tests: pytest suite (151 — engine golden, controller, analyze, playback, UI, browser, persistence, undo under `QT_QPA_PLATFORM=offscreen`; `tests/conftest.py` isolates QSettings to a temp dir).

**Phase 7 (packaging) — built, dev-box verified.** `setup.py` (py2app) builds `dist/Kickflip Shuffle.app` (unsigned beta `0.9.0`, id `com.kickflipshuffle.app`, ~1.6 GB, bundles the sf2). `app/_bootstrap.py` shims the fluidsynth dylib + `resource_root()` for frozen asset paths. libfluidsynth's transitive dylib tree is fully relocated into the bundle (0 Homebrew-absolute deps). Builds + boots on the dev box. **Remaining Phase 7 sign-off:** clean double-click launch on a second Mac/user account (no dev env) — see `docs/HANDOFF.md` §8.

**Phase 8 (enhancements) — in progress.** Master plan `docs/plans/PHASE8_plan.md` (plan-gated) sub-phases all 9 items. **8a drag-out MIDI** (`app/ui/drag.py`) + **8c playhead** (QTimer → step-grid overlay during preview) shipped. **8d section markers** (`compute_section_markers` + `write_midi(markers=)`; export writes DAW-timeline markers, default path byte-identical) shipped. **8e section lock** (🔒 timeline toggle freezes a section's groove/fill across regenerate; `resolved_section_grooves` + `set_section_locked`/`regenerate`) shipped. Remaining sub-phases: 8b verify EZ_DRUMMER_3 map (owner-in-loop), 8f tap tempo + half/double-time, 8g count-in/click, 8h batch + A/B. Plus the clean-machine packaging verify (Phase 7, HANDOFF §8). Read `docs/BUILD_PLAN.md` + `docs/plans/` before continuing; locked decisions live there and in `docs/HANDOFF.md`.

**Open follow-up:** `EZ_DRUMMER_3` note values are UNVERIFIED (only `tom_hi` 50→48 diverges from GM); audition `EZ_DRUMMER_3_ladder.mid` (regenerate via `Controller.write_note_ladder(path, output_map="EZ_DRUMMER_3")`) in EZ Drummer 3.

## Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # mido, librosa, pyfluidsynth, PySide6, py2app, ...

# Run the app (Generate-view vertical slice)
python main.py

# Run the engine CLI
python engine/generate.py --list-profiles
python engine/generate.py --profile pop_punk --tempo 170 --seed 1 --out out.mid
python engine/generate.py --song spec.json --out out.mid   # spec = JSON song spec

# Tests (UI tests need offscreen Qt)
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q
```

**Env note:** `.venv` is built on Homebrew `python@3.11` (NOT pyenv) — pyenv's build lacked `_lzma`, which breaks librosa. `libfluidsynth` is a native playback dep (`brew install fluid-synth`, installed). The GM soundfont `FluidR3_GM.sf2` (MIT, ~142MB) lives in `assets/soundfonts/` (gitignored); needed for playback only, not the engine CLI. The four bundled fonts (`assets/fonts/`, OFL/Apache, licenses included) are registered at startup but only under the real Qt platform (offscreen can't register app fonts → system fallback in tests).

The pytest suite covers engine golden (byte-identical `GENERAL_MIDI` regression guard), controller, analyze, playback, and UI.

## Architecture

Two layers, strictly separated:

- **`engine/` — the source of truth. Reuse, do not rewrite.** All musical data and generation logic lives here. The app layer calls into it; never port music logic up into the app. `engine/__init__.py` re-exports the public API.
- **`app/` — controller + UI only.** In-process Python calls into the engine (no JS↔Python bridge). `controller.py` (UI-facing API — the only thing the UI talks to), `analyze.py` (librosa audio→spec, F2), `playback.py` (pyfluidsynth render/transport + context mix, F4), `ui/` (PySide6 widgets; the UI drives the controller, never the engine/playback directly).

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
