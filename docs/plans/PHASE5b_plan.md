# Phase 5b — Drop audio (F2 UI) (DRAFT for Plan-gate)

Goal: a **Drop-audio** mode — drag in an audio file, set known-tempo / alignment,
run analysis (already built: `Controller.analyze_audio`), review the detected
tempo / per-segment roles, pick a profile, and **"Build drums to fit"** → a spec
loaded into the Generate view for correction/play/export.

## Owner decisions (LOCKED 2026-06-30)
- **Add a left mode rail + `QStackedWidget`** to MainWindow (Generate / Drop audio;
  Browser added in 5c). Drop is a switchable mode, not a dialog.
- **Minimal Drop view; correct in the arrangement editor.** Drop does drag-in +
  known-tempo/alignment/profile + a detected readout; "Build" hands the spec to the
  Generate view, where the existing timeline/section/axis/grid editor does the
  correction (no duplicated per-segment UI).
- **Analysis runs on a worker thread** (librosa is slow/blocking) — reuse the
  `_RenderWorker` QThread pattern from `generate_view.py`.

## Facts (verified)
- `Controller.analyze_audio(path, *, alignment="fixed_grid", known_tempo=None,
  beats_per_bar=4) -> AnalysisResult`; holds it as `controller.analysis`.
- `Controller.spec_from_analysis(profile, *, result=None, overrides=None) -> spec`;
  `result` defaults to the held analysis; stores + returns the spec as current.
- `AnalysisResult` fields: `tempo, sr, duration, alignment, beat_times,
  downbeat_times, segments[(start,end)], segment_energy[0..1], sections[{role,bars,
  fill_at_end?,crash_in?}], confidence{tempo, segmentation}`.
- Analysis is profile-agnostic; the profile is chosen at build time.
- MainWindow currently sets `GenerateView` as the central widget directly; the
  left mode rail is only mentioned as a stub.

## Plan-gate fixes folded (2026-06-30)
5 must-fixes + MED/LOW below. Verified: `spec_from_analysis(profile)` with no
`result=` reads the HELD `_analysis` (set only by the real `analyze_audio`), so a
monkeypatched analyze leaves it `None` → Build would raise. Child `closeEvent` does
NOT fire for widgets inside a `QStackedWidget`. Profile-row `setCurrentRow` fires
`_on_profile_selected → song_from_profile`, clobbering an analysed arrangement.

## Files
- `app/ui/drop_view.py` (new) — `DropView(QWidget)` + `_AnalyzeWorker(QObject)`.
  - `status = Signal(str)`, `specBuilt = Signal()`.
  - **Drop zone**: a `QFrame` with `setAcceptDrops(True)`. Factor the accept
    decision into a pure predicate `_is_audio_url(url)` (ext ∈ `.wav .flac .ogg
    .aif .aiff .mp3 .m4a`); `dragEnterEvent`/`dropEvent` are thin wrappers calling
    it + `event.acceptProposedAction()`. Real work in **`load_file(path)`** (tests
    drive it directly + unit-test `_is_audio_url`, NOT a synthetic `QDragEnterEvent`
    — awkward/version-sensitive offscreen). [MED drag test] A "Choose file…" button
    (`path, _ = QFileDialog.getOpenFileName(...)`, unpack the 2-tuple) → `load_file`.
  - **Inputs**: "known tempo" `QCheckBox` + `QSpinBox` (40..300; unchecked =
    `known_tempo=None`); alignment combo (`fixed_grid` default / `follow_beats`);
    **"Cut to click (starts on beat 1)"** `QCheckBox` — checking it AUTO-checks +
    enables the known-tempo control and sets alignment `fixed_grid`; Analyze is
    DISABLED until a tempo is entered (else `analyze_audio` raises on
    `known_tempo<=0`). [MED #4 gating]
    - **RESOLVED (2026-07-01, satisfied-by-design):** the implemented `known_spin`
      is bounded 40..300, so `known_tempo` is never `<=0` — the raise the gate
      guarded against is unreachable. Unchecked known-tempo (`None`) is the valid
      auto-detect path and must stay analysable (dropping audio to *detect* tempo
      is the primary use). Analyze therefore gates on `_path` only, not on
      `known_check`. Diff-gate flagged this as drift; owner accepted current
      behavior as safe by construction. No code change.
  - **Analyze** button → `_start_analyze(path)`: disable inputs **and the mode rail**,
    status "Analysing…", spawn `_AnalyzeWorker` on a `QThread` calling
    `controller.analyze_audio(path, alignment=…, known_tempo=…)`. On `done(result)`
    → **store `self._result = result`** and `_show_result(result)`; on `failed(msg)`
    → status; always re-enable + `_finish_thread` (quit/wait). [MED #5 rail]
  - **Detected readout** (`QLabel`s + `QListWidget`): tempo (+ `confidence["tempo"]`),
    duration, effective alignment; one row per section from
    **`zip(result.sections, result.segment_energy)`** (`role · bars · energy`;
    energy is NOT on the section dict). [LOW energy] Build enabled once `_result` exists.
  - **Profile** `QComboBox` from `controller.list_profiles()`, storing the profile
    **name** as `userData` (mirror generate_view). [LOW combo data]
  - **Build drums to fit** → `controller.spec_from_analysis(self.profile.currentData(),
    result=self._result)` — pass the CAPTURED result explicitly (do NOT rely on the
    held `_analysis`; the worker-thread field is racy and a monkeypatched analyze
    never sets it) → `specBuilt.emit()`. [HIGH #1]
  - `shutdown()`: quit/wait any running analyze thread (called by MainWindow.closeEvent).
- `app/ui/main_window.py` (edit) — left mode rail (`QListWidget`: "Generate",
  "Drop audio") + `QStackedWidget([GenerateView, DropView])` sharing the SAME
  controller. Rail `currentRow` → `stack.setCurrentIndex`. Both views' `status`
  → status bar. `DropView.specBuilt` → switch to Generate mode +
  `generate_view.load_current_spec()`. **`MainWindow.closeEvent`** must explicitly
  tear down BOTH views' worker threads (child `closeEvent` does NOT fire inside a
  `QStackedWidget`) — call a `shutdown()` on each view. [MED #3]
- `app/ui/generate_view.py` (edit) — add public `load_current_spec()`: reuse the
  existing `_refresh_from_spec` body (it does NOT call `song_from_profile`, so the
  analysed arrangement survives), PLUS a **signal-blocked** profile-row sync that
  locates the item by `data(Qt.UserRole) == controller.spec["profile"]` and sets it
  under `self.profiles.blockSignals(True/False)` (never via a plain `setCurrentRow`,
  which fires `_on_profile_selected → song_from_profile` and would DISCARD the
  analysed sections). [HIGH #2] Add `shutdown()` (delegates to the existing thread
  quit/wait) for MainWindow teardown.

## Threading
`_AnalyzeWorker` mirrors `_RenderWorker`: `done(object)` / `failed(str)`,
`moveToThread`, `started->run`, UI-thread slots quit/wait the thread; inputs
disabled during analysis; `closeEvent` guards teardown. `spec_from_analysis` +
UI updates happen on the UI thread after `done`.

## Tests — `tests/test_drop.py` (pytest-qt, offscreen)
Monkeypatch `controller.analyze_audio` to return a hand-built `AnalysisResult`
(real librosa is slow/nondeterministic; the real pipeline is already covered by
`test_analyze.py`). The fake has **2 sections** (≠ the 7-section profile default)
so readout/reload assertions can't pass vacuously against a stale arrangement.
Async worker awaited via `qtbot.waitUntil`.
1. `load_file(path)` + Analyze → worker runs → readout populated (tempo label shows
   the fake tempo; `QListWidget` rows == `len(result.sections)` == 2); Build enabled.
2. known-tempo + alignment passed through to `analyze_audio` (a spy monkeypatch
   records kwargs). Separate test: checking "cut to click" auto-enables known-tempo
   + sets fixed_grid; with no tempo entered, Analyze is disabled. [gating]
3. Build → `spec_from_analysis(name, result=<captured>)` called; `controller.spec`
   has 2 sections; `specBuilt` emitted. (Build works even though the monkeypatched
   analyze never set `controller.analysis`.) [HIGH #1]
4. Analyze error (monkeypatch raises) → status message, no crash, inputs + rail
   re-enabled.
5. `_is_audio_url` predicate: accepts `file:///x.wav`, rejects `.txt` (unit test the
   predicate; do NOT synthesize a QDragEnterEvent). [MED #5]
6. MainWindow: rail switches the stacked view; `DropView.specBuilt` → Generate mode
   shown + editor panel not hidden + `controller.spec` has the 2 analysed sections
   (arrangement NOT clobbered by a profile-select). [HIGH #2]
7. `GenerateView.load_current_spec()`: build a 2-section spec on the controller,
   call it, assert BPM + timeline/editor reflect it and the profile row is selected
   WITHOUT `song_from_profile` overwriting the sections.
8. `MainWindow.closeEvent` tears down cleanly with no running threads (no
   "QThread destroyed" — call close on a window whose views have no active worker). [MED #3]

## Sequencing
1. `generate_view.load_current_spec()` refactor + test.
2. `MainWindow` mode rail + stacked + wiring + test.
3. `DropView` (drop zone + inputs + `load_file` + readout + profile + build) + tests.
4. `_AnalyzeWorker` threading + error path + tests.
5. Full suite green (104 + new); manual `python main.py` drop smoke.

## Gates
- Plan-gate: `Plan` agent critique -> fold -> owner approval.
- Diff-gate: `code-reviewer` on `git diff --cached` -> fix -> commit -> push.

## Risks
1. **Build depends on held `_analysis`** [HIGH, fixed] — capture the worker result
   and pass `result=` explicitly; never rely on the thread-mutated held field.
2. **Profile-row select clobbers the analysed arrangement** [HIGH, fixed] —
   signal-blocked, name-matched row sync; reuse `_refresh_from_spec` (no
   `song_from_profile`).
3. **Thread teardown inside a stack** [MED, fixed] — child `closeEvent` won't fire;
   `MainWindow.closeEvent` calls `shutdown()` on both views.
4. **Cut-to-click ↔ known-tempo** [MED, fixed] — auto-enable tempo + gate Analyze.
5. **Cross-view races** [MED] — disable the rail during analysis; analyze only
   mutates `_analysis` (independent field); Build is sequential.
6. **Drag-drop headless testing** — pure `_is_audio_url` predicate + `load_file`;
   thin event handlers.
7. **Profile-agnostic analysis** — energy-band roles; user refines in the
   arrangement editor after Build (locked scope). Role-only (no-groove) analysed
   sections render fine (verified: valid engine roles, grid/editor handle them).
8. **No new engine/controller work** — 5b is UI only; `analyze_audio`/
   `spec_from_analysis` already exist and are tested.
