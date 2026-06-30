# Phase 5a-i — PySide6 shell + Generate core (vertical slice) (DRAFT for Plan-gate)

Goal: the smallest end-to-end native UI that proves **profile -> generate -> play
-> export** through the existing `Controller`. App shell + keyart-palette theme +
a Generate view with profile list, BPM, seed/regenerate, transport, output-map
picker, and export. NO arrangement timeline / per-section editing / 16-step grid
yet — that is 5a-ii.

## Owner decisions (LOCKED 2026-06-29)
- **Core slice first** (this doc); arrangement timeline + QPainter grid = 5a-ii.
- **Defer fonts** — system-font fallback now, keep type ROLES so the four OFL
  fonts drop in later (packaging). License-verify then.
- **pytest-qt + `QT_QPA_PLATFORM=offscreen`** widget tests; controller/playback
  monkeypatched so no real audio/device.

## Facts
- PySide6 6.11.1; offscreen QApplication verified. pytest-qt NOT installed → add
  to `requirements-dev.txt`.
- Assets present: `assets/art/keyart.png` (+ `@2048`, `.svg`), `assets/icon/
  KickflipShuffle.icns` + iconset. MISSING (deferred): 4 OFL fonts, grit texture,
  wordmark image — slice uses a flat themed background + the keyart image.
- Controller surface consumed (all exist): `list_profiles`, `song_from_profile`,
  `build_spec_from_ui_state`, `generate`, `render_preview`, `play`, `stop`,
  `set_output_map`/`output_map`, `list_output_maps`, `export`, `seed`/`set_seed`/
  `new_seed`. UI calls ONLY the controller (no direct engine/playback).

## Palette (derived from keyart — supersedes design HTML violet/gold)
Dark (default): `ink #0d0b07` (bg), warm-dark panels `#16130d` / `#211c14`,
`cream #e8e2d2` (fg), `muted #928e86`, `amber #e2b84a` (accent/selection),
`red #c42b1e` (record/active/destructive), line `rgba(232,226,210,.10)`. Radius +
panel structure carried from the HTML tokens. A light set (cream bg / ink fg) is
defined but dark is the default this slice. Type ROLES (display=Saira-Stencil-ish
wordmark, ui=Space-Grotesk-ish sans, mono=IBM-Plex/Special-Elite) map to system
fallbacks now via a single place to re-point later.

## Plan-gate fixes folded (2026-06-30)
All 9 must-fixes + MED/LOW resolved below. Verified: `list_output_maps()` returns
**tuples** `(name, n_roles, verified)` (NOT dicts like `list_profiles()`);
`song_from_profile` leaves `controller.seed == None`; `generate()` does NOT call
`playback.render_events`; `QSpinBox` defaults to max 99; `getSaveFileName` returns
`(path, filter)`.

## Files (new)
- `main.py` (repo root) — `def main()`: `QApplication.instance() or
  QApplication(sys.argv)` (NEVER a second instance / none at import), set window
  icon from **`keyart.png`** (not `.icns` — Qt runtime can render it blank),
  `theme.apply(app)`, `MainWindow`, `app.exec()`. Construction only under
  `if __name__ == "__main__"`. [H4, M4]
- `app/ui/__init__.py`
- `app/ui/theme.py` — `PALETTE` (dark/light), `apply(app, mode="dark")` (QSS +
  `QPalette`); `ASSETS = Path(__file__).resolve().parents[2] / "assets"` +
  `asset_path(*parts)` (NOT cwd-relative); `font_role(name) -> QFont` (system
  fallback). No widgets. [L1]
- `app/ui/generate_view.py` — `GenerateView(QWidget)` holding a `Controller`.
  **Single source of truth = `controller.spec` + controller state**; widgets render
  from it. All programmatic widget updates wrapped in `blockSignals(True/False)` so
  `setValue`/`setCurrentIndex` during (re)load don't re-enter handlers. [H1]
  - Left: `QListWidget` of profiles (name + era; `AxisFingerprint` mini-viz per
    row). Select -> `controller.song_from_profile(name)`; refresh BPM/seed/output-
    map (blocked); leave empty state; **enable** the gated controls.
  - BPM `QSpinBox`: **`setRange(40, 300)` BEFORE any `setValue`** (else clamps to
    99). [C1] On change, preserve state: `controller.build_spec_from_ui_state(
    profile, axes=spec["overrides"], sections=spec["sections"], tempo=bpm,
    ppq=spec["ppq"])` (do NOT pass `sections=None` — that rebuilds the arrangement
    and drops overrides). [M1]
  - Seed `QLabel` + **Regenerate** (`new_seed()` then `generate()`); seed is `None`
    after profile-select, and `play`/`export` materialise one internally — so
    **refresh the label from `controller.seed` after every Regenerate/Play/Export**
    (show "—" when None). [H2]
  - Output-map `QComboBox`: items are TUPLES `(name, n, verified)` — show
    `name` (+ "(unverified)" when not `verified`), store `name` as itemData;
    on change call `controller.set_output_map(name)` (the string, never the tuple).
    [C3] Note: map affects EXPORT only; preview/play are GM — UI copy must not imply
    it changes playback. [L4]
  - Transport: **Play** = `render_preview()` THEN `play()` (required — `play()`
    only renders when no buffer is held; after a BPM/seed/profile change the held
    buffer is stale, so the explicit render refreshes it; not a double-render).
    **Stop** = `stop()`. [M2]
  - **Export** -> `path, _ = QFileDialog.getSaveFileName(...)` (unpack the 2-tuple);
    if `path`: `controller.export(path)`; refresh seed label. [M5]
  - **Control gating**: Regenerate/Play/Stop/Export/BPM/output-map **disabled until
    a profile is selected** (controller raises `ValueError` on `spec is None`). [H3]
  - **Error surfacing**: Play/Export wrapped in `try/except Exception` ->
    `MainWindow` status bar message (missing sf2 / no audio device must not crash
    the window). [M3]
  - Empty state: keyart image + hint `QLabel` until a profile is picked.
  - `AxisFingerprint(QWidget)` — `QPainter` row of 7 mini bars (the 7 axes, 0..1),
    read-only; define `sizeHint`/`minimumSize` so offscreen layout doesn't collapse
    it to 0x0. [L2]
- `app/ui/main_window.py` — `MainWindow(QMainWindow)`: title/icon, central
  `GenerateView`, a `QStatusBar` (used by error surfacing), menu/About dialog
  (keyart + version). Left mode rail stubbed for 5b/c; only Generate wired now.

`requirements-dev.txt` += `pytest-qt`. (`requirements.txt` unchanged — PySide6 listed.)

## Threading note
`render_preview` (fluidsynth, ~0.15s + render) and `play` run on the UI thread this
slice — acceptable for short previews; a worker thread is a 5a-ii/later refinement
(flagged, not done now). `play()` is non-blocking (sounddevice callback).

## Tests — `tests/test_ui.py` (pytest-qt, offscreen)
conftest: set `QT_QPA_PLATFORM=offscreen` in env BEFORE any Qt import. Tests use
`qtbot`; a `Controller` with **playback monkeypatched** — `monkeypatch.setattr(
"app.playback.render_events", ...)` (tiny non-silent buffer) and
`"app.playback.Player"` (fake recording load/play/stop). Confirmed patchable:
controller does `from . import playback` then module-qualified calls. [L3]
1. `GenerateView` populates the profile list from `list_profiles()` (count + first
   name).
2. Select a profile -> `controller.spec["profile"]` == picked; empty state gone;
   gated controls enabled.
3. BPM spinbox: `setRange` allows 172; setting it -> `controller.spec["tempo"]`
   == value (float ok); `spec["sections"]`/`overrides` preserved (not rebuilt). [C1,M1]
4. Output-map combo lists all `list_output_maps()` tuples; selecting EZ_DRUMMER_3
   (by name itemData) -> `controller.output_map == "EZ_DRUMMER_3"`. [C3,L4]
5. Regenerate -> `controller.seed` changes and is non-None; `generate()` returns
   non-empty events. (Do NOT assert render_events — `generate` doesn't call it.) [C2]
6. Play -> fake Player `load`+`play` called (render_preview ran first); Stop ->
   `stop` called. No device opened. [M2]
7. Export: monkeypatch `QFileDialog.getSaveFileName` -> `(str(tmp_path/'out.mid'),
   '')` (2-tuple); click Export -> a real `.mid` written + re-readable via mido. [M5]
8. `theme.apply(app)` runs; stylesheet non-empty; `asset_path("art","keyart.png")`
   exists (resolved from package root, not cwd). [L1]
9. `MainWindow` constructs (under the qtbot qapp), title set, central is a
   `GenerateView`, has a status bar.
10. `import main` is clean and does NOT create a second QApplication at import
    (construction guarded under `__main__` / `.instance()`). [H4]
11. Empty state: a fresh `GenerateView` has Regenerate/Play/Export/BPM disabled;
    enabling happens only after select. [H3]
12. Error surfacing: monkeypatch `render_preview` to raise -> Play shows a status
    message and does NOT propagate (window survives). [M3]

## Sequencing
1. `theme.py` (palette/QSS/asset+font helpers) + test 8.
2. `AxisFingerprint` + `GenerateView` populate/select (tests 1-3).
3. Output-map picker + Regenerate (tests 4-5).
4. Transport + Export (tests 6-7).
5. `MainWindow` + `main.py` (test 9); manual launch smoke (`python main.py`).
6. Full suite green (69 + new) under offscreen.

## Gates
- Plan-gate: `Plan` agent critique -> fold -> owner approval.
- Diff-gate: `code-reviewer` on `git diff --cached` -> fix -> commit (Co-Authored-By
  trailer) -> push `main`.

## Risks
1. **Headless Qt** — tests force `offscreen`; never show a real window.
2. **Audio in tests** — playback monkeypatched; no `Player` opens a device. Real
   runs wrap Play/Export in try/except -> status bar (missing sf2 / no device). [M3]
3. **Signal re-entry** — programmatic widget updates wrapped in `blockSignals`. [H1]
4. **QSpinBox clamp** — BPM `setRange(40,300)` before `setValue`. [C1]
5. **Output-map shape** — tuples `(name,n,verified)`, pass `name` to set_output_map. [C3]
6. **Seed desync** — refresh label from `controller.seed` after Regenerate/Play/
   Export (None after song_from_profile; materialised internally by play/export). [H2]
7. **Empty-state crashes** — controls gated until a profile is selected (controller
   raises on `spec is None`). [H3]
8. **QApplication lifecycle** — only under `__main__`/`.instance()`; main.py import
   test guards it. [H4]
9. **UI-thread render hitch** — short previews only; worker thread deferred to later.
10. **Spec/state coupling** — UI mutates spec ONLY via controller; BPM preserves
    sections/overrides (no arrangement rebuild). [M1]
11. **Fonts/decorative assets absent** — system fallback + flat themed bg; type
    roles centralised so OFL fonts + grit/wordmark slot in later.