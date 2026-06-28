# Handoff — Kickflip Shuffle

**For:** the next session / Claude Code picking this up.
**State as of:** 2026-06-28. Planning + branding complete. **No application code written yet.** The engine is dropped in and the art is locked.

---

## 1. What this is

A self-contained, double-click **macOS app** that turns the existing Python pop-punk drum MIDI engine into a GUI. It can:

- **F1 — Generate** drums from a profile + tempo, with a full arrangement editor and axis controls (ghost, ornament, double_bass, syncopation, breakdown, fill_prob, humanize).
- **F2 — Drop audio** in and fit a drum part to it (librosa analysis → song spec).
- **F3 — Browse + preview** the groove/fill library.
- **F4 — Play** generated MIDI in-app through a bundled GM soundfont, optionally mixed over the imported audio.

Final output is always a `.mid` file dragged onto an **EZ Drummer 3** track (or any DAW). The app builds/auditions the *pattern*; the DAW makes the final *sound*.

## 2. Locked decisions

| Topic | Decision |
|---|---|
| **Name** | **Kickflip Shuffle** (skate trick + kick-drum pun + Barker half-time shuffle). Exact phrase unused, no music-software collision. Personal/unsigned use cleared; TM-clear the two-word mark in the music class before any paid distribution. |
| Scope | All of **F1–F4** in this build. |
| UI | **PySide6** native (Qt6, LGPL). The HTML design is *visual reference only*. |
| Editor | **Full** per-section arrangement editing + axis controls. |
| Packaging | **Unsigned `.app`** via py2app (right-click → Open). |
| Soundfont | **FluidR3_GM** (MIT, ~140MB) — download separately, license-verify before bundling. |
| Export | `.mid` to a **fixed folder, with "Save As"** on demand. |
| Output map | **Selectable articulation map. General MIDI = default** (any DAW); **EZ Drummer 3** preset; more in Phase 8. |
| F2 alignment | **Fixed grid** default (snap to stated tempo); follow-beats toggle. |

## 3. Repo layout

```
kickflip-shuffle/
├── engine/                 # REUSED unchanged — source of truth
│   ├── generate.py         # PROFILES, GROOVES, FILLS, build_song, write_midi, song_from_profile
│   ├── __init__.py         # re-exports the engine API
│   └── references/grooves.md
├── app/                    # NEW — not written yet
│   └── ui/                 # PySide6 widgets
├── assets/
│   ├── art/                # keyart.svg (master) + keyart.png/@2048
│   ├── icon/               # KickflipShuffle.icns (+ .iconset, icon-small.svg)
│   ├── soundfonts/         # FluidR3_GM.sf2 goes here (gitignored, download it)
│   ├── textures/ fonts/    # to populate (grit PNG, the 4 fonts)
├── docs/
│   ├── HANDOFF.md          # this file
│   ├── BUILD_PLAN.md       # the full phased plan — READ THIS
│   ├── HANDOFF_brief.md    # original GUI brief (input)
│   ├── SKILL.md            # engine skill docs
│   └── design_handoff/     # Claude Design output: .dc.html + support.js + README
├── main.py                 # NEW — boots the app (not written)
├── setup.py                # NEW — py2app config (not written)
├── requirements.txt
└── README.md
```

## 4. Engine API (do not rewrite — extend only)

From `engine/generate.py`:

- `PROFILES` — 20 named profiles (era, tempo, per-role groove pools, fill pool, axes).
- `GROOVES` — ~26 one-bar 16-step patterns. `FILLS` — ~13 fills.
- `song_from_profile(name, overrides=None) -> spec`
- `build_song(spec, tempo=None, seed=None) -> events` — each event = `(tick, note, vel, dur)`, GM drums on channel 9 (GM ch.10).
- `write_midi(events, out_path, tempo=170, ppq=480) -> path`
- Spec schema: `{ppq, profile, tempo, overrides:{axes...}, sections:[{role|groove, bars, fill|fill_at_end, crash_in}]}`

**Four additive engine extensions the app needs** (see BUILD_PLAN §"Engine extensions"):
1. **Per-section axes** — `build_song` currently reads axes globally (`generate.py:528–532`); let each section carry an optional `axes:{}`.
2. **Symbolic notes + output-map layer** — `build_song` bakes GM notes (`generate.py:563`); carry the symbolic `inst` role and resolve to MIDI at write time via a selected map. Add `engine/output_maps.py` with `GENERAL_MIDI` (byte-identical default) + `EZ_DRUMMER_3`.
3. **Editable grid rows** — expose the resolved groove dict (pre-humanize-jitter) for the UI sequencer; events stay for playback/export.
4. **Half-time shuffle groove** — the app is named for it; audit `GROOVES`, add `half_time_shuffle` if absent, wire to the `barker`/`tre_cool` pools.

**Gotchas:** `build_song`'s `tempo` param is inert (timing comes from `ppq`); tempo applies only at `write_midi`/playback — source it from `spec["tempo"]`.

## 5. Art — LOCKED

MxPx *Panic*-inspired poster: distressed amber wall, black skater silhouette mid-**kickflip over a drum kit**, backwards snapback + Vans low-tops, red misregister ghost, scatter shards, torn spray-paint logo.

- Master: `assets/art/keyart.svg` (edit here). Rendered via macOS `qlmanage` (WebKit handles the SVG filters); no rasterizer installed — for production installs `brew install librsvg` or `pip install cairosvg` for identical bakes.
- Icon: `assets/icon/KickflipShuffle.icns` — **drum-kit icon at 16/32/64** (the poster collapses to a blob below ~128px), full poster at 128→1024. Small-icon master = `assets/icon/icon-small.svg`.

To re-bake the icon after editing:
```bash
qlmanage -t -s 1024 -o . assets/art/keyart.svg      # → keyart.svg.png
# sips-resize into KickflipShuffle.iconset, then:
iconutil -c icns assets/icon/KickflipShuffle.iconset -o assets/icon/KickflipShuffle.icns
```

## 6. Open items before/while building

- **Download FluidR3_GM.sf2** into `assets/soundfonts/` and confirm MIT terms allow bundling.
- **Fonts:** add Space Grotesk, IBM Plex Mono, Special Elite, Saira Stencil One to `assets/fonts/`; confirm each OFL permits app bundling.
- **Confirm the per-section axes shape** with the owner before touching `build_song`.
- **TM clearance** for "Kickflip Shuffle" only needed if distributing commercially.

## 7. Next action

Start **Phase 0 → Phase 1** of `docs/BUILD_PLAN.md`:
0. Scaffold venv + `pip install -r requirements.txt`; confirm `engine` imports and CLI still runs.
1. Engine-as-library: add list helpers, `resolved_bar`, the 4 extensions, regression test (`GENERAL_MIDI` output == pre-refactor).

Then controller → analyze → playback → UI (vertical-slice: Generate first) → wire/persistence → py2app.
