# Phase 6a — Persistence + export polish (DRAFT for Plan-gate)

Save/load a project as `.ppd`, recent-files, a default export folder with
Save-As + Reveal-in-Finder, and theme persistence. Undo/redo is **6b**; the
playhead is deferred to **Phase 8** (owner call 2026-07-03).

Note: the BUILD_PLAN "replace every mocked element" bullet is already satisfied —
5a-ii/5b/5c wired all views to the real controller (scan found no live mocks).
6a is the persistence + export-polish slice of Phase 6.

## Owner decisions (LOCKED 2026-07-03)

- **Split 6a/6b.** 6a = persistence + export polish (this doc). 6b = undo/redo
  (spec-snapshot stack in the controller). Playhead → Phase 8.
- **`.ppd` = JSON `{version, spec, seed, output_map, selected_section, theme}`.**
  Undo history NOT persisted. Prefs (recent files, last export dir, last open/save
  dir, theme) live in **QSettings** (native macOS plist).
- **Undo model (6b, recorded here for continuity):** controller keeps a stack of
  `copy.deepcopy` specs; each arrangement mutation pushes; undo/redo swaps current.
- **Default export dir = `~/Music/Kickflip Shuffle/`** (auto-created). Export writes
  there directly with a de-duped name (`drums.mid`, `drums-2.mid`, …); "Export As…"
  prompts; "Reveal in Finder" opens it. Last-used dir remembered in QSettings.

## Facts (verified)

- `Controller` owns `spec` (property), `_seed`, `_output_map`; `export(out_path, *,
  spec, output_map, seed)` renders the `.mid` (unchanged). No persistence today.
- `main.py` creates the `QApplication` but sets **no** org/app name — QSettings
  needs both. `theme.apply(app, mode)` with `PALETTE = {"dark", "light"}`.
- Export today = `generate_view._on_export` → `QFileDialog.getSaveFileName` every
  time (no default folder, no reveal). Only export entry point.
- `generate_view.load_current_spec()` selects section row 0; needs an optional
  index arg to restore a saved selection.
- No `QSettings`, `.ppd`, recent-files, or theme toggle exist yet.

## Controller changes (`app/controller.py`) — headless, unit-tested

1. `to_project(extra=None) -> dict`: `{"version": 1, "spec": deepcopy(self._spec),
   "seed": self._seed, "output_map": self._output_map, **(extra or {})}`. Raises if
   no spec. `extra` carries UI-only state (`selected_section`, `theme`).
2. `save_project(path, *, extra=None)`: `json.dump(to_project(extra))`; returns path.
3. `load_project(path) -> dict`: read JSON, **validate BEFORE mutating any state** —
   require `version == 1` and a dict `spec` (else `ValueError` with a clear message;
   `self._spec` untouched). Then set `self._spec = deepcopy(data["spec"])`,
   `self._seed = data.get("seed")` (missing → `None` = auto-seed on next generate),
   `self._output_map` from `data.get("output_map")`. Deepcopy on both ends so the
   on-disk dict and the held spec never share references. Invalidate preview.
   - **output_map fallback owned HERE (not the UI):** an unknown/missing map name
     does NOT raise — set `GENERAL_MIDI` and add a human string to a returned
     `"warnings": [...]` list. Returns the full dict (incl. `selected_section`,
     `theme`, `warnings`) so the UI restores selection/theme and shows warnings on
     the status bar. Only `version`/`spec` problems raise.

## Prefs (`app/ui/settings.py`, new) — thin QSettings wrapper, injectable

4. `Prefs(qsettings=None)` — defaults to `QSettings()` (reads org/app set in
   `main.py`); tests inject a temp `QSettings(path, IniFormat)` so the suite never
   touches the real plist.
   - `recent_files() -> [str]`, `add_recent(path)` (dedup, most-recent-first, cap
     10, prune non-existent on read).
   - `export_dir() -> Path` (default `~/Music/Kickflip Shuffle`, `mkdir(parents,
     exist_ok)`), `set_export_dir(p)`.
   - `last_project_dir()` / `set_last_project_dir(p)`.
   - `theme() -> "dark"|"light"`, `set_theme(m)`.

## UI changes

5. **`main.py`**: set `app.setOrganizationName("Kickflip Shuffle")` +
   `app.setApplicationName("Kickflip Shuffle")` (before any QSettings). Read
   `Prefs().theme()` and pass to `theme.apply`.
6. **`main_window.py`** — File menu + recent + theme, holds current project path:
   - Menu **File**: New, Open… (`*.ppd`), Save (`Ctrl+S`, Save-As if no path),
     Save As… (`Ctrl+Shift+S`), **Open Recent ▸** (from `Prefs`), separator, Quit.
   - Menu **View**: Dark / Light radio (persists via `Prefs.set_theme` + re-applies
     `theme.apply(app, mode)` live). MainWindow holds an app ref (or uses
     `QApplication.instance()`) + `_current_project_path` (None = Untitled).
  - **Theme model (resolved):** QSettings holds the app-wide last-used theme (the
     startup default). `.ppd.theme` is a per-project restore — on open, apply the
     project's theme live AND write it back to `Prefs.set_theme` so it becomes the
     current default. On save, `extra["theme"]` = the live theme.
   - `_open(path)` → `controller.load_project` → `generate_view.load_current_spec(
     selected_section)` + apply theme + `Prefs.add_recent` + set window title to
     file stem. `_save(path)` → `controller.save_project(path, extra={selected_
     section, theme})` + add_recent + title. Guard load errors to the status bar
     (never crash).
   - Window title reflects the open project (`— <name>` / `— Untitled`).
7. **`generate_view.py`** — export polish:
   - `load_current_spec(selected_section=0)` — restore a saved row. **Clamp** the
     index to `0..len(sections)-1` (a `.ppd` saved before sections were deleted must
     not select out of range); empty arrangement → no selection.
   - Replace the single Export button flow: **Export** writes straight to
     `Prefs.export_dir()` with a de-duped filename; **Export As…** keeps the
     `getSaveFileName` path (seeded at the export dir); **Reveal** runs
     `open -R <path>` (guarded to darwin; no-op + status elsewhere). Surface all
     outcomes on the status bar.

## Risks / guards

- 🔴 **Tests must not touch the real macOS plist** — `Prefs` takes an injectable
  `QSettings`; every test builds one over a `tmp_path` IniFormat file. No bare
  `QSettings()` in tests.
- 🟡 **`load_project` on a malformed / wrong-version file** — validate `version`
  and required keys; raise a clear `ValueError`; UI catches → status bar, no crash,
  held spec unchanged (validate BEFORE mutating `self._spec`).
- 🟡 **Reference sharing** — deepcopy on save and load so editing after load can't
  mutate the file image, and re-saving can't alias the live spec.
- 🟡 **Export de-dup race / overwrite** — never overwrite silently; increment
  suffix until free (`drums-N.mid`).
- 🔵 **`output_map` from an old file no longer valid** — `_resolve_map` name check
  raises; fall back to `GENERAL_MIDI` with a status note rather than failing load.
- 🔵 **Recent entries that were moved/deleted** — pruned on read; clicking a stale
  recent surfaces a status-bar error.

## Test plan (`tests/test_persistence.py`)

- Controller: `to_project` shape + raises with no spec; `save`→`load` round-trip
  restores spec/seed/output_map; loaded spec is deep-copied (mutating it doesn't
  change a re-read of the file); bad `version` raises; unknown `output_map` falls
  back to GENERAL_MIDI.
- Prefs (temp QSettings): recent add/dedup/cap/prune; `export_dir` default created;
  theme round-trip.
- UI (offscreen): save then load restores spec + `selected_section`; Export writes
  a file into a temp export dir and de-dups on a second export; theme toggle updates
  `Prefs`; malformed `.ppd` open → status message, no crash. `open -R` monkeypatched.

## Files

- `app/controller.py` (`to_project`/`save_project`/`load_project`)
- `app/ui/settings.py` (new — `Prefs`)
- `app/ui/main_window.py` (File/View menus, open/save/recent, title, theme)
- `app/ui/generate_view.py` (`load_current_spec(selected_section)`, export polish)
- `main.py` (org/app name, theme from prefs)
- `tests/test_persistence.py` (new)
