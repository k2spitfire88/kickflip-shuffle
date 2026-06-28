# Handoff: Pop Punk Drums — app front-end

## Overview
This is the front-end design for the **self-contained macOS "Pop Punk Drums" app**: drop audio in *or* dial a profile, and the app writes tightly-scoped pop-punk drums as a `.mid` the user drags onto an EZ Drummer 3 track. This package documents the UI and, crucially, **maps every mocked interaction in the prototype to the real Python engine call it stands in for.**

Read this alongside the two documents the user already has:
- `HANDOFF_pop_punk_drum_gui.md` — the architecture/packaging brief (pywebview + py2app, the 4 feature areas F1–F4, the EZD3 boundary, open decisions).
- `pop-punk-drums-skill/` — the engine: `scripts/generate.py` (the API), `references/grooves.md` (the idiom), `SKILL.md` (the spec schema).

## About these files — design reference AND the intended front-end
The HTML here is a **design reference** (a working prototype showing the intended look and behavior). But unlike a typical mock, this is **also the intended production front-end**: the chosen architecture is pywebview hosting an HTML/CSS/JS UI over the Python engine (see the brief). So the job is **not** to re-skin in React — it is to:

1. Lift this layout/visual language into the app's `app/web/` front-end.
2. **Replace the mocked JavaScript engine with real calls across the pywebview JS↔Python bridge** to a `controller.py` that wraps `generate.py` (+ `analyze.py`, `playback.py`).

The prototype is authored as a "Design Component" (`.dc.html` + `support.js` runtime). Treat that wrapper as scaffolding — the *markup, inline styles, and the `class Component` logic* are what matter. You can port them to plain `index.html` + `app.js` (vanilla, no framework needed) and drop the `support.js`/`DCLogic` shell. To view it as-is, open the `.dc.html` with `support.js` beside it in a browser.

## If you go native instead (PyQt/PySide or SwiftUI)
If a browser-engine dependency inside the app is unwanted, treat this HTML as **visual reference only** and rebuild the window with native widgets. Everything below still applies — the layout, tokens, type, screens, state model, and the engine-binding table are framework-agnostic. Adjust only:
- **Component mapping:** left rail → list/sidebar (`QListWidget` / `List`); arrangement timeline → a custom horizontal widget; the 16-step grid → a custom-drawn sequencer (`QPainter` / SwiftUI `Canvas`); axis sliders → native sliders; groove/fill pickers → native menus/pickers; toggles → native switches.
- **Engine calls** become **in-process Python** (PyQt/PySide) rather than a JS↔Python bridge — the same `controller.py` functions, called directly. (SwiftUI would shell out to the Python engine or embed it.)
- **Grit doesn't port** from CSS: pre-render the concrete + scratch + grain stack to a tiling **PNG/texture asset** and use it as the window background; keep the stencil wordmark as an image. Everything else is solid fills + the violet accent, which port directly.
- The mocked→real table, the song-spec JSON, and the BPM-follows-song rule are unchanged.

Per the brief, **pywebview is the recommended path** (it lets this HTML ship largely as-is); native is the fallback if you specifically want to avoid the browser engine.

## Fidelity: **hi-fi**
Final colors, type, spacing, grit, and interactions. Recreate pixel-accurately. All values are below.

---

## The window
- **Size:** 1280×800, `border-radius: 12px` (the pywebview window).
- **Aesthetic:** "restrained mix" — a precise dark DAW layout with **distressed-concrete grit** (inspired by the MxPx *Panic* cover the user supplied): concrete radial background, scratch lines, an SVG `feTurbulence` grain overlay, and a torn-paper **stencil wordmark**. Functional accent is a **muted electric violet**; gold is a sparse texture accent only.
- **Vertical structure:** title bar (46px) → mode tabs (56px) → body (flex) → status bar (50px).
- **Body columns:** left rail **252px** · center (flex) · right inspector **304px**.

## Screens / modes
The mode tabs (**Generate** / **Drop audio**, equal billing) and the left-rail tabs (**Profiles** / **Grooves**) together pick what the center shows.

### 1. Generate (rail: Profiles)
- **Left rail:** all 20 profiles grouped by era, each with a 3-bar "axis fingerprint" (double_bass / breakdown / ghost) and a **`~tempo`** label (tilde = suggested, not locked). Search box filters.
- **Center, top:** **Arrangement timeline** — horizontal chips, one per section, showing an energy sparkline, role name, bar count, and markers (✦ crash-in, ▸ fill). Click a chip to select; `+ Section` appends. Total bar count shown.
- **Center, middle:** the selected section's **16-step grid** (lanes: Crash, Hat, Snare, Tom, Kick), with a beat ruler and a playhead that sweeps during playback. Open hi-hats render as outlined cells; a china crash gets a gold inset.
- **Center, bottom:** transport — play / stop / loop, progress, "1 bar loop", "GM PREVIEW" pill.
- **Right inspector:** **Section** (groove dropdown, bars stepper, Fill-end + Crash-in toggles, and — when Fill is on — a **Fill-pattern dropdown**: Auto or any of 13 named fills) and **Feel axes** (7 sliders grouped Feel / Density / Form / Looseness) + "Reset to profile".

### 2. Drop audio (mode: Drop)
- **Dropzone** → **Analyzing** (staged progress: tempo → beats → structure → energy) → **Detected** panel:
  - Editable **detected tempo** (stepper).
  - **Alignment** toggle: *Fixed grid* (cut to a click) vs *Follow detected beats*.
  - **Section map**: one card per detected segment with an energy bar; **the role on each card is a button — click to cycle intro → verse → chorus → bridge** (corrections flow into the build).
  - **Build drums to fit** → maps the (corrected) map to a song spec, builds, returns to Generate, and shows a "Fitted to …" banner + updates the output path.

### 3. Groove browser (rail: Grooves)
- Rail lists all **26 grooves** grouped by lineage + all **13 fills**, each with a one-line description.
- Center **preview pane**: kind tag (GROOVE/FILL), name, description, the animated notation with its own Preview transport, a **"Used by"** row of profiles that draw on it (click to jump to that profile), and **"Use in current section / Add as fill"**.

---

## Interactions → engine bindings
The prototype fakes the engine in JS. Replace each with a bridge call to `controller.py`. (`generate.py` already exposes `PROFILES`, `GROOVES`, `FILLS`, `build_song(spec, tempo, seed)`, `write_midi(events, path, tempo, ppq)`, `song_from_profile(name, overrides)`.)

| Prototype (mocked in JS) | Real implementation |
|---|---|
| Profile list + axis fingerprints | `controller.list_profiles()` → `PROFILES` (era, tempo, axes) |
| Selecting a profile sets axes + arrangement | `song_from_profile(name)` for the default spec; profile axes seed the sliders |
| Groove/fill browser data + descriptions | `controller.list_grooves()` / `list_fills()` → `GROOVES` / `FILLS` keys (+ descriptions from `references/grooves.md`) |
| Grid render + axis sliders changing the grid | The engine's `_apply_axes` / `build_song` is the source of truth — render one expanded bar from the engine instead of the prototype's simplified 5-lane preview |
| **Preview / transport play** (grid playhead, GM) | `controller.play(midiPath)` — render MIDI through bundled `.sf2` via `pyfluidsynth`; the JS playhead just visualizes position |
| **Generate** (build from profile + arrangement + axes) | Assemble the spec (below) → `build_song` → `write_midi` |
| **Drop audio → analyze** | `controller.analyzeAudio(path)` → `analyze.py` (librosa): `{tempo, beats, downbeats, segments:[{role,bars,energy}], alignment}` |
| Detected tempo / role edits / alignment toggle | User corrections to the analyze result **before** building |
| **Build drums to fit** | Corrected analysis → song spec → `build_song` |
| **Export .mid** | `controller.export(spec, outPath)` → `write_midi` + native save dialog (or default folder) |
| Context preview "over my track" (not yet in UI) | `playback.py` mixes the fluidsynth render over the loaded audio (F4) |
| Light/dark toggle, BPM stepper, seed/regenerate | Pure UI, except `seed` → `build_song(..., seed=n)` and BPM → spec `tempo` |

### The song spec the UI must emit
Matches `generate.py` / `SKILL.md`:
```json
{
  "ppq": 480,
  "profile": "new_found_glory",
  "tempo": 178,
  "overrides": { "ghost": 0.5, "ornament": 0.4, "double_bass": 0.7,
                 "syncopation": 0.0, "breakdown": 0.6, "fill_prob": 0.85, "humanize": 0.85 },
  "sections": [
    { "role": "intro",  "bars": 4 },
    { "role": "verse",  "bars": 8, "fill_at_end": true },
    { "role": "chorus", "bars": 8, "crash_in": true, "fill_at_end": true },
    { "role": "verse",  "bars": 8, "fill_at_end": true },
    { "role": "chorus", "bars": 8, "crash_in": true, "fill_at_end": true },
    { "role": "bridge", "bars": 4, "fill_at_end": true },
    { "role": "chorus", "bars": 8, "crash_in": true }
  ]
}
```
- The inspector's **groove dropdown** sets `"groove": "<name>"` on a section (overrides the profile's role pick).
- The **fill picker**: "Auto" → `"fill_at_end": true`; a named fill → `"fill": "<name>"`.
- **Crash-in** → `"crash_in": true`.

## State model (the controller/front-end need)
- `profile` (one base coordinate; mutually exclusive selection).
- `bpm` + **`bpmFromSong` flag** — **important: the song's tempo wins.** Once the user sets a tempo or fits to a dropped track, switching profiles must **not** overwrite `bpm`; the profile's tempo becomes a *suggestion* (the UI shows a "~tempo, use it" pill). This mirrors the engine, where `--tempo` / spec `tempo` override the profile default.
- `axes` (7 values; seeded from profile, then user-editable as `overrides`).
- `arr` (ordered sections: `{role, bars, fill, fillName|null, crash, groove}`).
- `sel` (selected section index), `seed`, `align` (`grid`|`beats`), `dropSegs` (the editable detected map).
- UI-only: `mode`, `railTab`, `playing`, `loop`, `dark`, `preview`.

---

## Design tokens
**Dark (default)**
| Token | Value |
|---|---|
| `--bg` | `#0e0e10` |
| `--panel` | `#161619` |
| `--panel2` | `#1e1e23` |
| `--fg` | `#ECEAE6` |
| `--muted` | `#928e86` |
| `--line` | `rgba(255,255,255,.09)` |
| `--accent` (violet) | `#7E6CD6` (grid cells `rgb(126,108,214)`) |
| `--accent2` (press) | `#6E5EC2` |
| `--gold` (texture) | `#d8b34a` |
| `--ok` (toast) | `#46c06a` |

**Light**
`--bg #E7E4DC` · `--panel #F4F2EC` · `--panel2 #FBFAF6` · `--fg #1A1814` · `--muted #6e6a61` · `--line rgba(0,0,0,.11)` · accent unchanged.

**Type**
- **Space Grotesk** — UI text, headers, buttons (400/500/600/700).
- **IBM Plex Mono** — all numerics (BPM, values, paths).
- **Special Elite** — small typewriter labels (section/panel headers, lane labels).
- **Saira Stencil One** — the torn-paper wordmark only.

**Radius / shape:** window 12; panels/buttons 8–10; cells 4; chips 9. **Lane cell height** 32, gap 7; column gap 3.

**Grit (intensity ~70/100):** concrete `radial-gradient` base; scratch `repeating-linear-gradient`s (~.62 opacity); SVG `feTurbulence` grain (`mix-blend:overlay`, .22 dark / .10 light); mottle radial blotches (.6). All texture layers are `z-index:0` behind the `z-index:2` content, so panels stay legible.

## What's mocked — replace with real
- **Analysis is faked** (fixed 174 BPM + a fixed 7-segment map) → real `librosa` in `analyze.py`. Keep the correction UI (tempo, roles, alignment) — the brief stresses analysis is approximate.
- **Audio is silent** — the playhead is visual only → render through `pyfluidsynth` + bundled GM `.sf2`.
- **The grid is a simplified 5-lane, 1-bar preview** that visualizes ghost/ornament/double_bass only. The engine has the full GM map (kick 36, snare 38, hats 42/44/46, crashes 49/57, toms, ride/bell, etc. — see `grooves.md` §6) and applies all axes incl. `syncopation`, `fill_prob`, `humanize`. Render previews from the engine output, not the JS approximation.
- **Data is transcribed, not imported:** the 26 grooves, 13 fills, and 20 profiles in the prototype mirror `generate.py`, but the engine is the source of truth — read them from it, don't re-key by hand.
- **Keep the EZD3 boundary visible** (status bar copy) — preview = GM stand-in, final kit/mix happens in the DAW.

## Files
- `Pop Punk Drums — App.dc.html` — the full interactive prototype (open with `support.js` beside it).
- `support.js` — the Design-Component runtime (scaffolding; not needed once ported to vanilla).
- `../Pop Punk Drums - Explorations.dc.html` (in the project root) — the aesthetic/layout exploration that led to this direction, if you want the rationale (4 visual directions, axis-control options, layout options).
