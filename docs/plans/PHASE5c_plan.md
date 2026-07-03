# Phase 5c — Groove browser (DRAFT for Plan-gate)

Browse the 26 grooves + 13 fills, preview each with transport, see which
profiles use it, and push a groove/fill into the current arrangement section.
Third entry on the MainWindow mode rail (reserved in 5b: "Browser added in 5c").

## Owner decisions (LOCKED 2026-07-01)

- **Grouping = by ROLE + "Used by" badge.** Grooves grouped verse / chorus /
  bridge (primary-role, deduped); fills in their own group. Each row carries a
  "Used by" badge (profiles/eras that reference it) so lineage info survives
  without lineage-based grouping. Era grouping rejected — 16/26 grooves span
  multiple eras → heavy duplication.
- **Preview = flavored by the current profile.** Preview renders the selected
  groove/fill through the Generate view's currently-selected profile + its axes
  (not a neutral loop). Preview reflects song context.
- **Apply actions disabled until a section is picked.** "Use in current section"
  / "Add as fill" are greyed until a spec exists AND a section is selected in the
  Generate view. Browse-only when no arrangement — no silent no-op.
- **Fix the two orphans now** (Phase-1 extension #4 follow-up, folded into 5c):
  - `half_time_shuffle` groove → wire into `barker` + `tre_cool` bridge pools.
  - `halfbar_toms` fill → wire into `barker` + `tre_cool` fills pools.
  Both wired ONLY to `barker`/`tre_cool` (the extension #4 named targets) — never
  to `pop_punk`/`ramones`, so the golden regression guard stays byte-identical.

## Facts (verified)

- `Controller.list_grooves() -> [{name, description}]`, `list_fills()` same,
  `list_profiles() -> [{name, era, tempo, axes}]`. No usage/lineage data exposed.
- Profile groove pools live in `engine.PROFILES[name]` under keys
  `verse/chorus/bridge/intro` (lists of groove names) + `fills` (list); plus
  `era`, `tempo`, and the 7 axis floats. Role pools are the "Used by" source.
- Reverse-map (computed): primary-role grouping gives verse(8)/chorus(7)/
  bridge(10) + 1 orphan (`half_time_shuffle`). `halfbar_toms` fill also orphan.
- `barker` (era 2000s_mall) + `tre_cool` (era 90s_skate) profiles both exist;
  bridge pools = `['halftime','skank']` / `['halftime','longview_tom']`.
- **Golden fixtures use only `pop_punk` + `ramones`** (`tests/golden/*.json`).
  Editing `barker`/`tre_cool` pools cannot change golden output.
- `Controller.render_preview(spec, *, seed, sample_rate, ...)` renders a spec to
  audio; `_RenderWorker` QThread in `generate_view.py` is the reuse pattern for
  off-thread render. `play()/stop()/seek()` drive transport.
- MainWindow (5b) has a left mode rail + `QStackedWidget` (Generate / Drop);
  `specBuilt` signal → Generate `load_current_spec`. Cross-view wiring pattern.
- Child `closeEvent` does NOT fire for widgets inside a `QStackedWidget` (5b
  finding) — teardown must be driven explicitly from MainWindow.closeEvent.

## Engine changes (additive, data-only where possible)

1. **Wire orphans** in `engine/generate.py` `PROFILES`:
   - `barker`, `tre_cool`: append `half_time_shuffle` to `bridge`, append
     `halfbar_toms` to `fills`. Pure data edit; no logic change.
2. **New read-only helper** `engine.groove_usage() -> {groove_name: {roles:set→
   sorted list, profiles:[...], eras:[...]}}` covering grooves AND fills
   (`fills` maps to role `"fill"`). Derived from `PROFILES`; no state. Re-export
   in `engine/__init__.py`. This is the "Used by" + role-grouping data source —
   keeps derivation in the engine (convention: list helpers live in engine).

## Controller changes (`app/controller.py`)

3. `list_groove_usage()` passthrough to `engine.groove_usage()`.
4. `preview_groove(name, *, kind="groove", bars=2) -> spec`: build a throwaway
   spec from the CURRENT profile with a single section — `groove=name, bars` for a
   groove, or a 1-bar section with `fill=name, fill_at_end=True` for a fill —
   carrying the current profile axes. Returns the spec; caller renders via existing
   `render_preview(spec)`. Does NOT mutate `self._spec`.
   - **No-spec contract (LOCKED):** if `self._spec is None`, fall back to profile
     `pop_punk` with that profile's default axes. Explicitly documented + unit-
     tested (reviewer 🟡).
   - This throwaway fill-section is PREVIEW ONLY — distinct from the apply action
     in step 6, which sets `fill=` on the user's existing current section rather
     than adding a bar.

## UI changes

5. **New `app/ui/browser_view.py` — `BrowserView(QWidget)`**:
   - Left: grouped tree/list (role headers verse/chorus/bridge/fills; rows =
     name + description + "Used by" badge).
   - Right: detail pane — description, full "Used by" profile list, transport
     (Play/Stop) driving a threaded preview render, and two buttons
     "Use in current section" / "Add as fill".
   - Owns its own `_RenderWorker` (mirror generate_view) + `shutdown()`.
   - Signals: `useGroove(str)`, `addFill(str)` emitted to MainWindow.
   - Apply buttons `setEnabled(False)` unless MainWindow reports an active
     section (see step 7).
6. **`generate_view.py`** (all NEW — reviewer confirmed none exist yet):
   - `current_section_index() -> int | None` — **the row currently selected in the
     arrangement editor** (not last-rendered); `None` if no selection / no spec.
   - `apply_groove_to_current_section(name)` → `controller.update_section(idx,
     groove=name, role=None)`. **`role=None` explicit** — `update_section` does NOT
     auto-clear `role`, so a role-based section would otherwise carry both keys
     (reviewer 🟡). Bounds-check `idx < len(spec['sections'])` first; no-op if stale.
   - `apply_fill_to_current_section(name)` → `controller.update_section(idx,
     fill=name)` on the CURRENT section (does NOT add a bar). Same bounds-check.
   - `sectionSelectionChanged` signal (emit index-or-None) so the browser toggles
     apply-button enabled state. Add `shutdown()` if missing.
7. **`main_window.py`**: add third mode-rail button + `BrowserView` page in the
   `QStackedWidget`. Wire `browser.useGroove → generate.apply_groove_to_current_
   section` then switch to Generate view; same for `addFill`. Relay
   `generate.sectionSelectionChanged → browser.set_apply_enabled`. Call
   `browser.shutdown()` in `closeEvent` (QStackedWidget children don't self-close).

## Risks / guards

- 🔴 **Golden byte-identity** — mitigated: orphans wired ONLY to barker/tre_cool;
  golden covers pop_punk/ramones. Guard = `test_golden.py` stays green unchanged.
- 🟡 **Preview render latency** — librosa-free (fluidsynth render only) but still
  off-thread via `_RenderWorker`; disable Play while a render is in flight.
- 🟡 **Apply with stale section index** — section could be deleted between select
  and apply; `apply_*` must bounds-check `current_section_index` against
  `len(spec['sections'])` and no-op safely.
- 🔵 **Fill vs groove target** — "Add as fill" sets `section['fill']`; "Use in
  current section" sets `section['groove']` + `role=None`. Reviewer confirmed
  `_resolve_groove()` (`generate.py:530–536`) already handles both `groove` and
  `fill` section keys — schema-compatible, no engine change needed for apply.

## Test plan

- `test_engine`/`test_golden`: unchanged, must stay green (regression guard).
- New engine test: `groove_usage()` covers all 26 grooves + 13 fills, no orphans
  remain (`half_time_shuffle`, `halfbar_toms` now have ≥1 profile).
- New controller test: `preview_groove` builds a valid single-section spec from
  current profile without mutating `_spec`; renders non-empty audio.
- New UI test (offscreen): BrowserView builds; apply buttons disabled with no
  spec; `useGroove` emission routes to `update_section`; `shutdown()` joins worker.

## Files

- `engine/generate.py` (pool edits + `groove_usage`), `engine/__init__.py` (re-export)
- `app/controller.py` (`list_groove_usage`, `preview_groove`)
- `app/ui/browser_view.py` (new)
- `app/ui/generate_view.py` (selection signal + apply methods)
- `app/ui/main_window.py` (3rd mode + wiring + teardown)
- `tests/` (engine usage, controller preview, UI browser)
