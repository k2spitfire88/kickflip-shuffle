# Handoff: Pop-Punk Drum Generator — Self-Contained macOS GUI

**Purpose of this document.** A planning brief to take into Claude Code. It
describes what exists, what to build, the recommended architecture, feature
specs, packaging realities, and the open decisions — so the build can be planned
and executed without re-deriving any of the earlier work.

---

## 1. Goal

Turn the existing Python pop-punk drum MIDI engine into a **self-contained,
double-click macOS app** (no terminal, no separate Python install for the end
user) that can:

1. Generate drums from a **profile + tempo** (with an arrangement editor and the
   axis controls: ghost, ornament, double_bass, syncopation, breakdown, etc.).
2. **Drop in an audio file** and fit a drum part to it (tempo/beat/section/energy
   analysis → song spec).
3. **Browse + preview** the groove and fill library.
4. **Play/hear** the generated MIDI in-app through a bundled General-MIDI
   soundfont, including **mixed over the imported audio** for context.

Final output is always a `.mid` file the user drags onto an EZ Drummer 3 track.
The app builds and auditions the *pattern*; EZD3 produces the final *sound*.

---

## 2. What already exists (reuse, do not rewrite)

A working skill folder `pop-punk-drums/`:

- `scripts/generate.py` — the engine. Key API surface:
  - `PROFILES` — 20 named profiles grouped by era (`pop_punk`, `ramones`,
    `tre_cool`, `offspring`, `mxpx`, `skate_punk`, `barker`, `good_charlotte`,
    `simple_plan`, `new_found_glory`, `sum41`, `fall_out_boy`, `all_time_low`,
    `paramore`, `jimmy_eat_world`, `easycore`, `neck_deep`, `revival_2020s`,
    `pop_punk_pop`, `ska_punk`). Each sets a tempo, per-role groove pools, a
    fill pool, and feel axes.
  - `GROOVES` — ~25 one-bar patterns (16-step grid). `FILLS` — ~13 fills.
  - `build_song(spec, tempo=None, seed=None) -> events` — expands a song spec
    into timed note events.
  - `write_midi(events, out_path, tempo, ppq)` — writes a GM-mapped, channel-10
    `.mid`.
  - `song_from_profile(profile_name, overrides=None) -> spec` — builds a
    standard arrangement spec for a profile.
  - Axes: `ghost`, `ornament`, `double_bass`, `syncopation`, `breakdown`,
    `fill_prob`, `humanize`.
  - Song-spec schema (JSON): `{ppq, profile, tempo, overrides:{...},
    sections:[{role|groove, bars, fill|fill_at_end, crash_in}]}`.
  - CLI: `--profile`, `--tempo`, `--song`, `--seed`, `--list-profiles`.
- `references/grooves.md` — the idiom knowledge: groove/fill grid notation, the
  tempo guide, the influence-stream map, the axis/profile system, and the
  "reach any band by dialing axes" recipe.
- `SKILL.md` — workflow + schema docs.

**Integration principle:** the GUI is a thin shell over this engine. The engine
functions (`build_song`, `write_midi`, `song_from_profile`, plus the `PROFILES`,
`GROOVES`, `FILLS` dicts) are the API the GUI calls. Do not port the music logic
into the UI layer.

---

## 3. Recommended architecture

**Python engine + HTML/CSS UI in a native window shell, packaged as a `.app`.**

```
[ HTML/CSS/JS front end ]  <-- designed in Claude Design, iterated visually
          |  (pywebview JS<->Python bridge)
[ Python controller layer ]  <-- new glue code: exposes engine + audio + playback to the UI
          |
[ Existing engine: generate.py ]  +  librosa (analysis)  +  fluidsynth (preview)
          |
[ py2app ]  --> double-click  Pop Punk Drums.app
```

**Why this stack:**
- Keeps the Python engine (mido, librosa) untouched — no rewrite, no second
  implementation to maintain.
- Front end is HTML/CSS, so **Claude Design can produce and iterate the actual
  interface**, not just a mockup.
- `pywebview` wraps the HTML in a native macOS window and provides a clean
  JS↔Python bridge for calls like `generate(spec)`, `analyzeAudio(path)`,
  `play(midiPath, withBackingTrack)`.
- `py2app` bundles Python + deps into a double-click `.app`.

**Alternative considered:** pure **PyQt/PySide** native GUI. Pros: most "native
mac" look, single language. Cons: Claude Design can only supply reference
mockups (not usable code), and UI iteration is slower. Choose this only if a
browser-engine dependency inside the app is unwanted. *Recommendation: pywebview
unless there's a reason to avoid it.*

---

## 4. Tech stack / dependencies

| Concern | Choice | Notes |
|--------|--------|-------|
| MIDI generation | existing `generate.py` (mido) | unchanged |
| Audio analysis | `librosa` | tempo, beat grid, downbeats, structural segmentation, RMS energy |
| Audio I/O | `soundfile`, `numpy` | load dropped track, mix |
| MIDI→audio preview | `pyfluidsynth` + libfluidsynth | renders MIDI through a `.sf2` soundfont |
| GM soundfont | a freely redistributable GM set (e.g. GeneralUser GS or FluidR3_GM) | confirm license permits bundling/redistribution |
| Playback | `sounddevice` (or pyfluidsynth's audio driver) | play preview, optionally mixed with backing track |
| UI shell | `pywebview` | native window hosting the HTML UI |
| Front end | HTML/CSS/JS (vanilla or a light framework) | designed via Claude Design |
| Packaging | `py2app` | produces the `.app` |

---

## 5. Feature specs

### F1 — Generate from profile + tempo
- UI: profile picker (grouped by era), tempo field/slider, arrangement editor
  (ordered list of sections: role or explicit groove, bar count, fill toggle,
  crash-in toggle), and axis sliders (ghost, ornament, double_bass, syncopation,
  breakdown, fill_prob, humanize) that populate `overrides`.
- A "use profile defaults" button calls `song_from_profile`; advanced users edit
  the arrangement and axes.
- Action: build the song spec, call `build_song` + `write_midi`, then enable
  Play and Export.
- Export: native save dialog, or a configurable default output folder so MIDI
  drops straight where the user wants it.

### F2 — Drop audio in, fit to track
- UI: drag-in zone for an audio file; fields for known tempo and whether the
  track was cut to a click; profile picker; style notes.
- New module `analyze.py`:
  - `librosa` → tempo estimate, beat frames, downbeats, structural segment
    boundaries, RMS/energy curve.
  - Map energy → section roles (loud = chorus/crash/heavier axes; quiet =
    verse/sparser); segment boundaries → bar counts; transitions → fills.
  - Emit a song spec, hand to `build_song`.
- Two alignment modes (ask the user, per the click question): **fixed grid** at
  the stated tempo (snaps to DAW bars) or **follow detected beats** (fits a loose
  take, won't sit on a clean grid).
- **Honest limits to surface in the UI:** analysis is signal-based, not
  "hearing"; beat tracking is reliable on tight/click material and shaky on
  rubato/ambient; section detection is approximate. Let the user correct the
  detected tempo and section map before generating.

### F3 — Browse + preview grooves/fills
- UI: list of all grooves and fills with their one-line description and grid
  notation (from `references/grooves.md` / the dicts), plus which profiles use
  each.
- "Preview" renders a short 2-bar MIDI of that single groove/fill and plays it
  through the soundfont in isolation. (Add `--preview`/list helpers to the engine
  to support this cleanly.)

### F4 — In-app playback (GM soundfont)
- Render the generated MIDI to audio via `pyfluidsynth` + the bundled `.sf2`.
- **Context preview:** when an audio file was dropped in (F2), mix the rendered
  drums over that track at matching tempo so the user hears the fit in context.
- Transport: play / stop / loop a section. Optional metronome.
- **Boundary to state in the UI:** preview = generic GM drums for auditioning the
  pattern. It is NOT the EZD3 sound and NOT a final mix. Final render happens in
  the DAW after dragging the `.mid` onto the EZD3 track.

---

## 6. The EZD3 boundary (important, restated)

The app never drives EZD3 and never produces EZD3-quality audio. It writes MIDI
and previews it with a stand-in GM synth. "Render inside the full track" is
supported only as an *in-app context preview* (GM drums over the imported audio);
the real full-track render is a DAW step the user does with their EZD3 kit and
mix. Keep this explicit in the UI so expectations are right.

---

## 7. Packaging, signing, Gatekeeper

- `py2app` produces `Pop Punk Drums.app`.
- **Bundling gotchas:**
  - librosa pulls in numpy/scipy/numba → large bundle (hundreds of MB) and
    occasional py2app hidden-import fiddling.
  - `libfluidsynth` is a native dylib; it must be included in the `.app` and its
    load path fixed up. Budget time for this.
  - The `.sf2` soundfont ships inside the bundle (`Resources/`).
- **Gatekeeper:** unsigned apps trigger "unidentified developer." For personal
  use: right-click → Open once. For a clean no-warning launch: Apple Developer
  account ($99/yr) + codesign + notarize. **Open decision (see §10).**

---

## 8. Proposed project structure

```
pop-punk-drums-app/
├── engine/                 # existing skill engine, imported as a package
│   ├── generate.py
│   └── references/grooves.md
├── app/
│   ├── controller.py       # pywebview API: generate(), analyze(), play(), export()
│   ├── analyze.py          # librosa audio -> song spec
│   ├── playback.py         # fluidsynth render + mix + transport
│   └── web/                # HTML/CSS/JS front end (Claude Design output)
│       ├── index.html
│       ├── styles.css
│       └── app.js
├── assets/
│   └── soundfonts/GM.sf2   # bundled, license-cleared
├── main.py                 # boots pywebview window
├── setup.py                # py2app config
└── README.md
```

---

## 9. Suggested build phases (for planning in Claude Code)

1. **Engine-as-library:** package `generate.py` so the app imports it cleanly;
   add `--preview` and groove/fill listing helpers.
2. **Controller + headless smoke test:** `controller.py` exposing
   generate/export; verify MIDI out without a UI.
3. **Playback:** `playback.py` — fluidsynth render + transport; then context-mix
   with a loaded audio file.
4. **Audio analysis:** `analyze.py` — librosa → spec; manual-correction hooks.
5. **Front end:** build the HTML UI (Claude Design), wire to the controller via
   pywebview.
6. **Packaging:** py2app build; resolve libfluidsynth + librosa bundling; test a
   clean double-click launch on a second mac/user account.
7. **Signing/notarization** (if chosen).

---

## 10. Open decisions to resolve before/while building

1. **Signing:** ship unsigned (right-click-to-open) for personal use, or set up
   codesign + notarization for a clean launch? (Needs Apple Developer acct.)
2. **Soundfont choice:** pick the specific redistributable GM `.sf2` and confirm
   its license allows bundling. (GeneralUser GS and FluidR3_GM are common
   candidates — verify current terms.)
3. **Arrangement editor depth:** simple (profile defaults + tempo) vs full
   (per-section role/groove/fill/axis editing). Recommend shipping simple first,
   full second.
4. **Default export location:** fixed project folder vs save-dialog each time.
5. **Front-end framework:** vanilla JS vs a light framework — affects Claude
   Design handoff. Decide before the F5 phase.
6. **Alignment default** for F2: fixed-grid vs follow-beats as the default.

---

## 11. Where Claude Design fits

Use Claude Design to design and produce the **HTML/CSS front end** (the window
layout: profile picker, arrangement editor, axis sliders, drag-in zone, groove
browser, transport bar). Because the chosen shell renders HTML, Claude Design's
output is usable directly, then Claude Code wires it to the Python controller.
If the project switches to PyQt, Claude Design's role drops to visual reference
only.

---

## 12. Risks & gotchas (summary)

- Bundle size and py2app friction from librosa (numpy/scipy/numba).
- Native `libfluidsynth` dylib bundling/path fixups.
- Soundfont licensing — must be redistributable.
- Beat/section detection reliability on loose material — give the user
  correction controls; don't present detection as ground truth.
- Gatekeeper friction if unsigned.
- Keep the EZD3 boundary explicit so preview audio isn't mistaken for final
  output.
```
