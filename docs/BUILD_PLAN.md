# Build Plan — Kickflip Shuffle (native macOS pop-punk drum generator)

Derived from `HANDOFF_pop_punk_drum_gui.md`, the engine skill zip, and the Claude Design handoff zip. Locked decisions are listed first; they drive every phase below.

## Locked decisions

| # | Decision | Choice |
|---|----------|--------|
| Name | App name | **Kickflip Shuffle** (skate trick + kick-drum pun + Barker half-time shuffle). Exact phrase unused, no music-software collision. Personal/unsigned use cleared; TM-clear the two-word mark in the music class before any paid distribution |
| Scope | Features in this build | **All of F1–F4** (Generate, Drop-audio, Groove browser, Playback) |
| UI | Shell | **PySide6 native** (Qt6, LGPL). Design HTML becomes *visual reference only* |
| Editor | Arrangement depth | **Full** — per-section role/groove/fill/axis editing + timeline |
| Packaging | Target | **Unsigned `.app`** via py2app (right-click → Open). No Apple Developer acct |
| Soundfont | Bundled GM `.sf2` | **FluidR3_GM** (MIT, ~140MB). Verify terms before bundling |
| Export | Default `.mid` destination | **Fixed folder + "Save As" option** |
| Output map | Articulation target | **Selectable. General MIDI = default** (DAW-agnostic, works anywhere); **EZ Drummer 3 = one preset**; more presets added in Phase 8 |
| F2 align | Default alignment mode | **Fixed grid** (snap to stated tempo); user can switch to follow-beats |

## What we reuse vs. build new

**Reuse, do not rewrite** — `engine/generate.py`:
- Data: `PROFILES` (20), `GROOVES` (~26), `FILLS` (~13), `GM` map, `STEPS` grid.
- `song_from_profile(name, overrides) -> spec`
- `build_song(spec, tempo=None, seed=None) -> events` where each event = `(tick, note, vel, dur)`, GM drums on channel 9 (GM ch.10).
- `write_midi(events, out_path, tempo=170, ppq=480) -> path`
- Spec schema: `{ppq, profile, tempo, overrides:{axes...}, sections:[{role|groove, bars, fill|fill_at_end, crash_in}]}`

**Build new:**
- `app/controller.py` — in-process API for the Qt UI (no JS bridge, native path).
- `engine/output_maps.py` — **articulation-map layer.** `build_song` emits abstract drum roles (kick/snare/hat-closed/hat-open/hat-pedal/crash/ride/ride-bell/toms/china/sidestick…); a selected **output map** translates those to concrete MIDI notes at write time. `GENERAL_MIDI` is the default and pass-through baseline (works in any DAW/sampler); `EZ_DRUMMER_3` is a preset hitting EZD3's articulations. New maps are data, not code.
- `app/analyze.py` — librosa audio → song spec (F2).
- `app/playback.py` — pyfluidsynth render + mix + transport (F4).
- `app/ui/` — PySide6 window, three modes, full arrangement editor, 16-step grid sequencer, axis sliders, transport.
- `assets/` — FluidR3_GM `.sf2`, grit texture PNG, stencil wordmark image, bundled fonts.
- `main.py`, `setup.py` (py2app), `requirements.txt`, `README.md`.

## Engine extensions to make (flagged, additive — not rewrites)

1. **Per-section axes.** `build_song` reads axes **once, globally** (`generate.py:528–532`): `ghost, ornament, double_bass, syncopation, breakdown, fill_prob, humanize` come from `overrides`/profile. Full per-section editing needs each `section` to optionally carry `axes:{...}` overriding the globals for that section only. Keep the global path as default when a section omits `axes`.

2. **Symbolic notes for the output-map layer.** `build_song` currently bakes GM note numbers into events (`note = GM[inst]`, `generate.py:563`). To support selectable output maps, carry the **symbolic `inst` role** in the event tuple and resolve to concrete MIDI notes at `write_midi`/playback time via the chosen map. `GENERAL_MIDI` reproduces today's exact output (zero behavior change as default); other maps (EZD3, etc.) are alternate translations. Additive: keep a GM-baked fast path if simpler, but the symbolic carry is what makes maps pluggable.

3. **Editable grid rows.** Expose the resolved groove dict (post-`_apply_axes`/`_normalize`, **pre-humanize-jitter**) so the UI sequencer edits the real pattern, not jittered events. Events stay the source for playback + MIDI export only.

4. **Half-time shuffle groove (name-justifying add).** The app is named for the Barker half-time shuffle, so the engine should *have* one. Audit the ~26 `GROOVES` for a shuffle/swung pattern; if absent, add a `half_time_shuffle` groove (swung 16ths, ghost-noted snare, backbeat on 3) and reference it from the `barker` (and optionally `tre_cool`) profile pools. Additive data entry, no logic change.

## Native-path consequences (design HTML is reference only)

From the design handoff "If you go native instead" section:
- **Component map:** left rail → `QListWidget`/sidebar; arrangement → custom horizontal timeline widget; 16-step grid → custom `QPainter` sequencer; axis sliders → `QSlider`; groove/fill pickers → native menus; toggles → native switches.
- **Engine calls** are in-process Python (controller functions called directly), not a JS↔Python bridge.
- **Grit doesn't port from CSS** → pre-render the concrete + scratch + grain stack to a tiling **PNG** used as window background; **stencil wordmark → image asset**.
- Carry over framework-agnostic pieces verbatim: design tokens (dark/light palettes), type ramp (Space Grotesk / IBM Plex Mono / Special Elite / Saira Stencil One), radius/shape, the three screens, state model, and the engine-binding table.

## Branding & key art

**Hero image:** a skater mid-**kickflip over a drum kit** — board flipping under the feet, kit (kick, snare, hats, crash, toms) below. This is the signature art for the app icon, About/splash, and the Generate-view empty state.

- **Style:** match the design tokens — screenprinted skate-zine / stencil aesthetic. Monochrome base on the concrete-grit texture, **violet accent `#7E6CD6`** + **gold `#d8b34a`** highlights, SVG-grain overlay, torn-paper edges. Sits beside the `Saira Stencil One` wordmark.
  - **⚠ SUPERSEDED 2026-06-28:** the violet `#7E6CD6` / gold `#d8b34a` tokens above do **not** match the locked keyart. App UI palette derives from `keyart.svg`: ink `#0d0b07`, amber `#e2b84a`, misregister red `#c42b1e`, cream `#e8e2d2`. Token derivation happens in Phase 5.
- **Uses / deliverables:**
  - `assets/art/keyart.png` — full hero (transparent + on-grit variants), high-res.
  - `assets/icon/KickflipShuffle.icns` — macOS app icon (full icon set 16→1024; tight crop of the skater+board+kick for legibility at small sizes).
  - In-app: Generate-view empty state + About panel; optional faint watermark behind the arrangement timeline.
- **Status: LOCKED.** Authored as vector (MxPx *Panic*-inspired: distressed amber wall, black skater silhouette mid-kickflip over a drum kit, backwards snapback, Vans low-tops, red misregister ghost, scatter shards, torn spray logo). Files (currently `~/Downloads/`; move into `assets/` at Phase 0):
  - `kickflip-shuffle-keyart.svg` — master source; `keyart.png` (1024) + `@2048.png` — hero.
  - `kickflip-shuffle-icon-small.svg` — simplified **drum-kit** icon for small sizes.
  - `KickflipShuffle.icns` (+ `.iconset/`) — app icon: **kit icon at 16/32/64**, full poster at 128→1024 (poster collapses to a blob below ~128, so small slots use the kit).
- **Bundling:** drop key art + `.icns` into `Resources/` via py2app (Phase 7).

## Phases

### Phase 0 — Scaffold
- Create `kickflip-shuffle/` project structure (per handoff §8, adjusted for Qt: `app/ui/` instead of `app/web/`).
- Git init, Python venv, `requirements.txt` (mido, librosa, soundfile, numpy, pyfluidsynth, sounddevice, PySide6, py2app).
- Drop `engine/` in as an importable package; smoke-test `import` + CLI still runs.

### Phase 1 — Engine-as-library
- Make `engine` importable cleanly (package `__init__`, no path hacks).
- Add read-only helpers the UI needs: `list_profiles()`, `list_grooves()`, `list_fills()` (keys + descriptions sourced from `references/grooves.md`), and `resolved_bar(section, profile, seed) -> rows` returning the **pre-jitter** groove dict so the UI sequencer edits the real pattern (extension #3).
- Implement the **per-section `axes` extension** (#1) and the **symbolic-note / output-map layer** (#2): `output_maps.py` with `GENERAL_MIDI` (default, byte-identical to current output) + `EZ_DRUMMER_3`.
- Unit tests: golden spec → deterministic events with a fixed seed; `GENERAL_MIDI` map output == pre-refactor output (regression guard).

### Phase 2 — Controller + headless smoke test
- `controller.py` exposing: `list_profiles/grooves/fills`, `song_from_profile`, `build_spec_from_ui_state`, `generate(spec, seed) -> events`, `resolved_bar(...)`, `render_preview(spec)`, `export(spec, out_path, output_map)`, `list_output_maps()`, `analyze_audio(path)`, `play/stop`.
- `export` takes the selected **output map** (default `GENERAL_MIDI`); same spec → different `.mid` per target.
- Headless test: generate + export a `.mid` for a profile with no UI; verify GM file opens in any MIDI reader, and the EZD3 map lands on EZ Drummer 3 articulations.

### Phase 3 — Audio analysis (F2)
- `analyze.py`: librosa → tempo estimate, beat frames, downbeats, structural segment boundaries, RMS/energy curve.
- Map energy → section roles (loud=chorus/heavier axes; quiet=verse/sparser); segments → bar counts; transitions → fills. Emit a song spec.
- Alignment: **fixed-grid default**, follow-beats toggle.
- Expose correction hooks (tempo, role map, alignment) — analysis is approximate; user edits **before** `build_song`.

### Phase 4 — Playback (F4)
- `playback.py`: render MIDI through bundled **FluidR3_GM** `.sf2` via pyfluidsynth; transport (play/stop/seek) over `sounddevice`.
- Context mix: render over the loaded audio file for "hear it over my track."
- Keep EZD3-boundary copy visible (preview = GM stand-in; final kit/mix in DAW).

### Phase 5 — PySide6 UI (vertical-slice first)
Build the hardest integration on the smallest surface before fanning out.
- **5a — Shell + Generate slice (vertical slice):** window chrome + dark/light themes from design tokens; bundle the four fonts; grit PNG background + wordmark image + **kickflip-over-drumkit key art** (window icon, About, Generate empty state). Then the **Generate view** end-to-end: profile list with axis fingerprints, BPM stepper, **full arrangement timeline** (add/remove/reorder sections, per-section role/groove/fill/crash-in + per-section axis sliders), 16-step `QPainter` grid, seed/regenerate, transport, output-map picker, export. Prove profile→edit→preview→**play**→export works before moving on.
- **5b — Drop audio:** drag-in zone, known-tempo + cut-to-click fields, detected tempo/role/alignment correction UI, "build drums to fit."
- **5c — Groove browser:** 26 grooves + 13 fills grouped by lineage with descriptions, preview pane with transport, "Used by" profiles, "Use in current section / Add as fill."

### Phase 6 — Wire UI → controller + persistence
- Replace every mocked element (faked 174-BPM analysis, silent playhead, simplified 5-lane grid, hand-keyed data) with real controller calls reading from the engine.
- Export: **fixed folder default, Save-As on demand**, output-map selector; "reveal in Finder."
- **Persistence:** save/load project as `.ppd` (JSON song spec + UI state) + recent files.
- **Undo/redo** stack for the arrangement editor.
- State model per design handoff (current spec, selection, theme, playback position, output map, undo history).

### Phase 7 — Packaging (unsigned `.app`)
- `setup.py` py2app config → `Kickflip Shuffle.app`, app icon = `KickflipShuffle.icns`.
- Resolve bundling: `libfluidsynth` native dylib (include + fix load path), librosa→numpy/scipy/**numba** hidden-import fiddling, `.sf2` + texture/wordmark + **key art/icon** + fonts into `Resources/`.
- Verify a **clean double-click launch on a second mac/user account** (no dev environment).
- Document right-click → Open (Gatekeeper, unsigned).

## Cross-cutting

- **License checks before bundling:** FluidR3_GM (MIT — confirm), the four fonts (Space Grotesk OFL, IBM Plex Mono OFL, Special Elite OFL, Saira Stencil One OFL — confirm each permits app bundling).
- **Determinism:** seed plumbed from UI → `build_song(seed=)` for reproducible regenerate.
- **Tempo handling:** `build_song` does not bake tempo into events; controller must pass `spec["tempo"]` to `write_midi` and to playback.

## Risks & gotchas

1. **py2app + librosa/numba** — hidden imports + large bundle (hundreds of MB). Budget time.
2. **libfluidsynth dylib** — must be inside the bundle with a fixed load path; common failure on a clean machine.
3. **py2app + PySide6/Qt** — Qt platform plugin (`libqcocoa`) and plugin path must be bundled; set `QT_PLUGIN_PATH`/`qt.conf` in the app. Separate from the librosa/fluidsynth bundling work.
4. **Engine extensions** — per-section axes, symbolic-note output map, resolved-rows helper; regression-test that `GENERAL_MIDI` + global-axes path stays byte-identical to current output.
5. **Output-map correctness** — EZD3 articulation note numbers must be verified against EZ Drummer 3's actual map; wrong numbers = silent/wrong articulations. Validate in EZD3 before shipping the preset.
6. **`build_song` tempo param is inert** — does not affect event timing; tempo applies only at `write_midi`/playback. Controller must source tempo from `spec["tempo"]`.
7. **Beat tracking** — reliable on tight/click material, shaky on rubato/ambient; surface limits + correction UI.
8. **Bundle size / launch time** — large `.sf2` + scientific stack; verify acceptable cold-start.

### Phase 8 — Enhancements (post-core)
Ordered by value-vs-cost. Built after F1–F4 + persistence are solid.

1. **Drag-out MIDI.** Drag the generated `.mid` straight from the app window onto a DAW/EZD3 track (`QDrag` + file URL). Removes the export→find→drag loop; matches the literal final step of the workflow.
2. **More output maps.** Extend the `output_maps.py` layer beyond GM + EZD3: Superior Drummer 3, Addictive Drums 2, GGD, etc. Pure data presets; UI already has the picker.
3. **Section lock on regenerate.** Lock liked sections; re-roll the seed only on unlocked ones.
4. **Section markers in export.** Write per-section MIDI markers so the arrangement shows on the DAW timeline.
5. **Batch variations.** Generate N seeds at once; audition; keep the best.
6. **Tap tempo** + **half-time / double-time** per-section toggle.
7. **Count-in / click track** for context preview.
8. **A/B compare** two seeds side by side.

(Save/load project + undo/redo were pulled forward into Phase 6 — they pair with the full editor and shouldn't wait.)

## Proposed structure (Qt-adjusted)

```
kickflip-shuffle/
├── engine/                  # existing skill engine (reused + extended)
│   ├── generate.py          # + per-section axes, symbolic notes, resolved_bar
│   ├── output_maps.py       # GENERAL_MIDI (default) + EZ_DRUMMER_3 (+ Phase 8 maps)
│   ├── __init__.py
│   └── references/grooves.md
├── app/
│   ├── controller.py
│   ├── analyze.py
│   ├── playback.py
│   └── ui/                  # PySide6 widgets (replaces app/web/)
│       ├── main_window.py
│       ├── generate_view.py
│       ├── drop_view.py
│       ├── browser_view.py
│       └── grid_widget.py
├── assets/
│   ├── soundfonts/FluidR3_GM.sf2
│   ├── textures/grit.png
│   ├── wordmark.png
│   ├── art/keyart.png        # skater kickflip over a drum kit (hero)
│   ├── icon/KickflipShuffle.icns
│   └── fonts/
├── main.py
├── setup.py                 # py2app → Kickflip Shuffle.app
├── requirements.txt
└── README.md
```
