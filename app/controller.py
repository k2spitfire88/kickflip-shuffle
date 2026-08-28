"""Controller — the in-process API the PySide6 UI calls into.

`Controller` is a thin, stateful orchestrator over the `engine` package. It
holds the UI-facing state that the rest of the app reads and edits:

  * the current song spec,
  * the selected output map (articulation target),
  * the active seed (so a regenerate is reproducible and an export reproduces
    exactly what was previewed).

It adds **no** musical logic — every generation/rendering decision is delegated
to `engine`. Future-phase capabilities (audio analysis, playback) are declared
here as stubs so the API surface is locked now; Phases 3/4 fill in the bodies.

Determinism contract
---------------------
The seed is materialised as a concrete int and held. `generate` sets/holds it;
`export` and `resolved_bar` *use* the held seed but do not overwrite it. Because
a concrete int (never ``None``) is always passed to the engine, a seedless
`export` reproduces byte-for-byte what a prior seedless `generate` produced.

Engine invariants honoured here
-------------------------------
  * ``build_song``'s ``tempo`` param is inert — timing comes from ``ppq``. Tempo
    is sourced from ``spec["tempo"]`` and applied only at ``write_midi``.
  * Drums emit on MIDI channel 9 (handled inside ``write_midi``).
  * ``seed`` is the only source of randomness — plumbed through every call.
"""
import copy
import json
import random

import engine
from . import analyze

PROJECT_VERSION = 1

# Upper bound for an auto-drawn seed. 2**63 keeps it a positive 64-bit int,
# comfortably within Python's arbitrary-precision range and JSON-serialisable
# for the Phase 6 project file.
_SEED_BOUND = 2 ** 63

DEFAULT_OUTPUT_MAP = "GENERAL_MIDI"


class Controller:
    def __init__(self, *, output_map=DEFAULT_OUTPUT_MAP, seed=None):
        engine.get_output_map(output_map)  # validate name early
        self._output_map = output_map
        self._seed = int(seed) if seed is not None else None
        self._spec = None
        self._analysis = None
        self._context_audio = None
        self._context_sr = None
        self._context_path = None       # source file, for .ppd persistence
        self._context_len_s = 0.0
        self._auto_offset_s = 0.0       # analysis lead-in (first downbeat)
        self._context_nudge_ms = 0      # manual correction, +/- one bar
        self._drums_gain = 1.0
        self._bed_gain = 0.8
        self._detected_tempo = None     # tempo the analysis reported (drift warning)
        self._align_export = True       # pad exported .mid by the alignment offset
        self._context_error = None      # last context-load failure (shown in warnings)
        self._preview_buf = None
        self._preview_sr = None
        # Seconds of buffer BEFORE musical tick 0 — count-in when playing dry, the
        # alignment offset (+ any count-in deficit) when mixed. NEVER negative:
        # play_section slices with it and a negative head is a tail-relative slice.
        self._preview_offset = 0.0
        self._play_head_s = 0.0         # head used by the LAST play_section slice
        self._play_base = 0.0           # musical seconds the current play buffer starts at
        self._count_in = 0              # preview count-in beats (0 = off)
        self._player = None
        self._undo = []
        self._redo = []

    # ------------------------------------------------------------------
    # Held state (read accessors the UI renders from)
    # ------------------------------------------------------------------
    @property
    def spec(self):
        """The current song spec (last built/generated), or ``None``."""
        return self._spec

    @property
    def seed(self):
        """The held seed (concrete int once any generation has run), or ``None``."""
        return self._seed

    @property
    def output_map(self):
        """Name of the selected output map."""
        return self._output_map

    def set_seed(self, n):
        """Pin the seed (UI 'lock seed'). Returns the stored int."""
        self._seed = int(n)
        self._invalidate_preview()
        return self._seed

    def new_seed(self):
        """Draw, store, and return a fresh seed (UI 'reroll')."""
        self._seed = random.randrange(_SEED_BOUND)
        self._invalidate_preview()
        return self._seed

    def clear_spec(self):
        """Drop the held arrangement (File → New). Public so the UI never pokes
        `_spec` directly."""
        self._spec = None
        self._reset_history()
        self._invalidate_preview()

    # ------------------------------------------------------------------
    # Undo/redo — deep-copied spec snapshots (arrangement editor)
    # ------------------------------------------------------------------
    _HISTORY_CAP = 100

    def _snapshot(self):
        """Push the current spec onto the undo stack (pre-edit state) and drop the
        redo stack. Called by the tracked mutators before they change the spec."""
        if self._spec is None:
            return
        self._undo.append(copy.deepcopy(self._spec))
        if len(self._undo) > self._HISTORY_CAP:
            self._undo.pop(0)
        self._redo.clear()

    def _reset_history(self):
        """Clear undo/redo — called when a new document replaces the spec wholesale
        (profile pick, fresh build, project load, analysis build)."""
        self._undo.clear()
        self._redo.clear()

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        if not self._undo:
            return False
        self._redo.append(copy.deepcopy(self._spec))
        self._spec = self._undo.pop()
        self._invalidate_preview()
        return True

    def redo(self):
        if not self._redo:
            return False
        self._undo.append(copy.deepcopy(self._spec))
        self._spec = self._redo.pop()
        self._invalidate_preview()
        return True

    def set_tempo(self, value):
        """Set the spec tempo in place (tracked). No-op — and no snapshot — when the
        value is unchanged, so a spin-box drag doesn't bloat the undo stack."""
        spec = self._require_spec()
        fv = float(value)
        if fv == spec.get("tempo"):
            return spec
        self._snapshot()
        spec["tempo"] = fv
        self._invalidate_preview()
        return spec

    def _invalidate_preview(self):
        """Drop the held preview buffer so the next play() re-renders. Called on
        any change that alters the rendered output (spec edit or seed change)."""
        self._preview_buf = None

    def set_output_map(self, name):
        """Select the output map by name (validated). Returns the name."""
        engine.get_output_map(name)
        self._output_map = name
        return name

    def _ensure_seed(self):
        """Materialise a concrete held seed if none is set; return it.

        Never returns ``None`` — this is what makes seedless export reproduce a
        seedless generate.
        """
        if self._seed is None:
            self._seed = random.randrange(_SEED_BOUND)
        return self._seed

    def _resolve_map(self, m):
        """Accept either an output-map name (str) or a role->note dict."""
        if isinstance(m, dict):
            return m
        return engine.get_output_map(m)

    # ------------------------------------------------------------------
    # Read-only catalogue passthroughs (UI lists / pickers)
    # ------------------------------------------------------------------
    def list_profiles(self):
        return engine.list_profiles()

    def list_grooves(self):
        return engine.list_grooves()

    def list_fills(self):
        return engine.list_fills()

    def list_output_maps(self):
        return engine.list_output_maps()

    def list_groove_usage(self):
        """{name: {roles, profiles, eras}} for the groove browser (role grouping
        + 'Used by' badge). Passthrough to ``engine.groove_usage``."""
        return engine.groove_usage()

    def preview_groove(self, name, *, kind="groove", bars=2):
        """Build a THROWAWAY single-section spec to audition one groove/fill.

        Flavored by the current profile + its axes so the preview matches song
        context. If no spec is held yet, falls back to profile ``pop_punk`` with
        that profile's default axes. Never mutates ``self._spec`` — returns the
        spec for the caller to hand to ``render_preview(spec)``.

        ``kind="groove"`` -> a ``bars``-bar section playing ``name``.
        ``kind="fill"``   -> a 1-bar section ending on fill ``name`` (audition
        only; the arrangement 'Add as fill' action is separate).
        """
        era = None
        if self._spec is not None:
            profile = self._spec["profile"]
            overrides = dict(self._spec.get("overrides") or {})
            ppq = self._spec.get("ppq", 480)
            tempo = self._spec.get("tempo") or engine.PROFILES[profile]["tempo"]
            era = self._spec.get("era")          # audition in the current era's flavor
        else:
            profile = "pop_punk"
            overrides = {}
            ppq = 480
            tempo = engine.PROFILES[profile]["tempo"]
        if kind == "fill":
            section = {"groove": "verse_basic", "bars": 1,
                       "fill": name, "fill_at_end": True}
        elif kind == "groove":
            section = {"groove": name, "bars": int(bars)}
        else:
            raise ValueError(f"kind must be 'groove' or 'fill', got {kind!r}")
        spec = {
            "ppq": ppq,
            "profile": profile,
            "tempo": float(tempo),
            "overrides": overrides,
            "sections": [section],
        }
        if era:
            spec["era"] = era
        return spec

    # ------------------------------------------------------------------
    # Spec construction
    # ------------------------------------------------------------------
    def song_from_profile(self, profile_name, overrides=None, era=None):
        """Build a default-arrangement spec for a profile (optionally an era);
        store as current."""
        self._spec = engine.song_from_profile(profile_name, overrides, era=era)
        self._reset_history()
        return self._spec

    def list_profile_eras(self, profile_name):
        """Selectable era labels for a profile (empty list for flat profiles)."""
        return [b["label"] for b in engine.PROFILES.get(profile_name, {}).get("eras", [])]

    def apply_era(self, era, *, keep_tempo=True):
        """Re-flavor the CURRENT song with an era, keeping its sections (and,
        by default, its tempo) — instead of rebuilding a fresh default arrangement.
        Role-based sections then resolve from the era's pools; explicit-groove
        sections keep theirs. Tracked/undoable; NOT a new document. This is the
        'my uploaded song, in <era> style, at my BPM' path.

        `keep_tempo=True` pins the current tempo (drops `tempo_range` so Regenerate
        won't re-roll it). `keep_tempo=False` adopts the era's midpoint + range."""
        spec = self._require_spec()          # guarantees a tempo is already present
        self._snapshot()
        if era:
            spec["era"] = era
        else:
            spec.pop("era", None)
        if keep_tempo:
            spec.pop("tempo_range", None)
        else:
            t = engine.profile_view(spec["profile"], era).get("tempo")
            if isinstance(t, (tuple, list)):
                lo, hi = int(t[0]), int(t[1])
                spec["tempo"], spec["tempo_range"] = (lo + hi) // 2, [lo, hi]
            else:
                spec.pop("tempo_range", None)
        self._invalidate_preview()
        return spec

    def set_tempo_locked(self, on):
        """Lock/unlock tempo re-roll on Regenerate. Locked -> drop `tempo_range`
        (keep the set BPM). Unlocked -> restore the current era's range, if the era
        actually has one (flat/int tempo -> no range to restore)."""
        spec = self._require_spec()
        if on:
            spec.pop("tempo_range", None)
        else:
            t = engine.profile_view(spec["profile"], spec.get("era")).get("tempo")
            if isinstance(t, (tuple, list)):
                spec["tempo_range"] = [int(t[0]), int(t[1])]
        self._invalidate_preview()
        return spec

    def build_spec_from_ui_state(self, profile, *, axes=None, sections=None,
                                 tempo=None, ppq=480):
        """Assemble an engine spec from explicit UI-supplied parts; store it.

        Thin and explicit (no speculative ``ui_state`` object — the richer
        mapper firms up with the real UI in Phase 5/6):

          * ``profile``  — profile name (validated).
          * ``axes``     — global axis overrides dict -> ``spec["overrides"]``.
          * ``sections`` — list of section dicts (``role``/``groove``, ``bars``,
            ``fill``/``fill_at_end``, ``crash_in``, optional per-section
            ``axes``). If ``None``, fall back to the profile's default
            arrangement.
          * ``tempo``    — spec tempo (defaults to the profile tempo).
          * ``ppq``      — pulses per quarter note.
        """
        if profile not in engine.PROFILES:
            raise ValueError(f"Unknown profile '{profile}'. "
                             f"Options: {sorted(engine.PROFILES)}")
        overrides = dict(axes or {})
        spec_tempo = float(tempo) if tempo is not None else float(engine.PROFILES[profile]["tempo"])
        if sections is None:
            sections = engine.song_from_profile(profile, overrides or None)["sections"]
        self._spec = {
            "ppq": ppq,
            "profile": profile,
            "tempo": spec_tempo,
            "overrides": overrides,
            "sections": sections,
        }
        self._reset_history()
        return self._spec

    # ------------------------------------------------------------------
    # Generation (preview path — GENERAL_MIDI stand-in; final kit in DAW)
    # ------------------------------------------------------------------
    def generate(self, spec=None, *, seed=None):
        """Generate events for preview. Holds the spec and the seed.

        Always renders with ``GENERAL_MIDI`` (the DAW-agnostic preview voice);
        the selected output map is applied at ``export`` time. Passing ``seed``
        pins it; otherwise the held seed is reused (or materialised).
        """
        spec = spec if spec is not None else self._spec
        if spec is None:
            raise ValueError("no spec to generate from; call song_from_profile / "
                             "build_spec_from_ui_state or pass spec=")
        if seed is not None:
            self._seed = int(seed)
        self._spec = spec
        return engine.build_song(spec, seed=self._ensure_seed(),
                                 output_map=engine.GENERAL_MIDI)

    def set_section_locked(self, index, locked):
        """Lock/unlock a section (structural-only). Locking FREEZES the section's
        currently-resolved groove/fill by writing them explicitly, so a later
        `regenerate` (new seed) keeps this section's part while re-rolling the
        others — `_resolve_groove` returns an explicit groove verbatim. Unlocking
        restores the section to its pre-lock role so it re-rolls again. Tracked
        (undoable); a no-op if already in the requested state."""
        spec = self._require_spec()
        sec = spec["sections"][index]
        if bool(locked) == bool(sec.get("locked")):
            return spec                            # already in requested state
        if locked:
            pick = engine.resolved_section_grooves(
                spec, seed=self._ensure_seed())[index]
            self._snapshot()
            added = []
            if pick is not None:                   # None only for a bars=0 section
                if "role" in sec:
                    sec["_prelock_role"] = sec.pop("role")
                if "groove" not in sec:
                    added.append("groove")
                sec["groove"] = pick["groove"]
                if pick["fill"] and "fill" not in sec:
                    sec["fill"] = pick["fill"]
                    added.append("fill")
            sec["locked"] = True
            sec["_lock_added"] = added
        else:
            self._snapshot()
            for key in sec.pop("_lock_added", []):
                sec.pop(key, None)
            if "_prelock_role" in sec:
                sec["role"] = sec.pop("_prelock_role")
            sec.pop("locked", None)
        self._invalidate_preview()
        return spec

    def global_axes(self):
        """Effective global axis values for the current spec: the per-spec
        ``overrides`` on top of the profile defaults. The section editor shows
        these as each section's INHERITED baseline (so barker reads high ghost,
        mxpx low), and only writes a per-section override for axes moved off it."""
        spec = self._require_spec()
        prof = engine.profile_view(spec["profile"], spec.get("era"))   # era-aware
        ov = spec.get("overrides", {})
        from engine.generate import _AXIS_KEYS
        return {k: float(ov.get(k, prof.get(k, 0.0))) for k in _AXIS_KEYS}

    def set_section_feel(self, index, feel):
        """Set a section's time-feel: 'normal' (default, unsets the key so the path
        stays byte-identical), 'half' (bars twice as long), or 'double' (half as
        long). Tracked/undoable via update_section."""
        if feel not in ("normal", "half", "double"):
            raise ValueError(f"feel must be normal/half/double, got {feel!r}")
        return self.update_section(index, feel=(None if feel == "normal" else feel))

    def regenerate(self):
        """Draw a new seed and re-generate. Locked sections carry an explicit
        (frozen-at-lock) groove so they keep their part; unlocked sections re-roll.
        Returns the new events. NOTE: a reroll changes the seed, which the
        spec-only undo stack (6b) does not capture — regenerate is not undoable
        (matches the pre-8e behaviour). If the spec carries an era `tempo_range`,
        the tempo also re-rolls within that range off the new seed (real songs in
        an era span a tempo range)."""
        seed = self.new_seed()
        rng = self._spec.get("tempo_range") if self._spec else None
        if rng:
            lo, hi = int(rng[0]), int(rng[1])
            self._spec["tempo"] = random.Random(seed).randint(lo, hi)   # int, like midpoint
        return self.generate()

    def resolved_bar(self, section_index, bar_index, *, spec=None, seed=None):
        """Pre-jitter pattern rows (inst -> [16 vels]) for the grid editor.

        MIRROR contract: exactly the rows ``build_song`` uses at that
        (section, bar). Uses the held seed for consistency with ``generate``
        unless an explicit ``seed`` is given (transient, not stored).
        """
        spec = spec if spec is not None else self._spec
        if spec is None:
            raise ValueError("no spec; pass spec= or build one first")
        s = int(seed) if seed is not None else self._ensure_seed()
        return engine.resolved_bar(spec, section_index, bar_index, seed=s)

    # ------------------------------------------------------------------
    # Arrangement editing (5a-ii) — mutate the held spec in place so per-bar
    # `patterns` overrides and unknown keys are never dropped.
    # ------------------------------------------------------------------
    def _require_spec(self):
        if self._spec is None:
            raise ValueError("no spec; build one (song_from_profile/...) first")
        return self._spec

    def set_bar_pattern(self, section_index, bar_index, rows):
        """Store an edited grid pattern for (section, bar). Bar key is int."""
        engine._validate_pattern(rows)
        sec = self._require_spec()["sections"][section_index]
        self._snapshot()
        sec.setdefault("patterns", {})[int(bar_index)] = copy.deepcopy(rows)
        self._invalidate_preview()
        return self._spec

    def clear_bar_pattern(self, section_index, bar_index):
        """Remove a bar override (revert to generated). No-op if absent."""
        sec = self._require_spec()["sections"][section_index]
        patterns = sec.get("patterns")
        if patterns:
            self._snapshot()               # only snapshot when actually clearing
            patterns.pop(int(bar_index), None)
            patterns.pop(str(bar_index), None)
            if not patterns:
                sec.pop("patterns", None)
            self._invalidate_preview()
        return self._spec

    @staticmethod
    def _prune_patterns(sec):
        """Drop overrides whose bar index is now out of range for the section."""
        patterns = sec.get("patterns")
        if patterns:
            bars = sec.get("bars", 4)
            for key in [k for k in patterns if int(k) >= bars]:
                del patterns[key]
            if not patterns:
                sec.pop("patterns", None)

    def set_sections(self, sections):
        """Replace the arrangement using the given (existing) section dict
        references — preserves each section's `patterns`/unknown keys. Globals
        (profile/overrides/tempo/ppq) untouched."""
        spec = self._require_spec()
        self._snapshot()
        for sec in sections:
            self._prune_patterns(sec)
        spec["sections"] = list(sections)
        self._invalidate_preview()
        return spec

    def update_section(self, index, **fields):
        """Overlay changed fields (role/groove/fill/crash_in/bars/axes) onto the
        EXISTING section dict (so `patterns` survive). Prunes out-of-range
        overrides if `bars` shrank."""
        sec = self._require_spec()["sections"][index]
        if fields:
            self._snapshot()               # empty call changes nothing -> no snapshot
        for key, value in fields.items():
            if value is None:               # None -> unset (e.g. groove "from role")
                sec.pop(key, None)
            else:
                sec[key] = value
        self._prune_patterns(sec)
        self._invalidate_preview()
        return self._spec

    # ------------------------------------------------------------------
    # Export (selected output map; explicit destination this phase)
    # ------------------------------------------------------------------
    def export(self, out_path, *, spec=None, output_map=None, seed=None,
               align=None):
        """Render ``spec`` through the selected output map and write a ``.mid``.

        Reproduces the previewed generation: uses the held seed (an explicit
        ``seed`` is transient and does NOT overwrite the held one — export is a
        sink). Tempo is sourced from the spec (build_song's tempo param is
        inert) and applied at ``write_midi``.

        ``align`` (default: the held ``align_export``) shifts every event — and
        every section marker — later by the context-mix alignment offset, so the
        ``.mid`` dropped into the DAW lands where it was auditioned against the
        track. With no context track loaded the shift is 0 and the output is
        byte-identical to an unaligned export.
        """
        spec = spec if spec is not None else self._spec
        if spec is None:
            raise ValueError("no spec to export; generate or pass spec=")
        omap = self._resolve_map(output_map if output_map is not None
                                 else self._output_map)
        s = int(seed) if seed is not None else self._ensure_seed()
        tempo = spec.get("tempo")
        if tempo is None:
            tempo = engine.PROFILES[spec["profile"]]["tempo"]
        ppq = spec.get("ppq", 480)
        events = engine.build_song(spec, seed=s, output_map=omap)
        markers = engine.compute_section_markers(spec)   # DAW-timeline section markers
        shift = self._export_offset_ticks(
            spec, float(tempo), ppq,
            self._align_export if align is None else align)
        if shift:
            events = [(tick + shift, note, vel, dur)
                      for tick, note, vel, dur in events]
            markers = [(tick + shift, label) for tick, label in markers]
        return engine.write_midi(events, out_path, tempo=tempo, ppq=ppq,
                                 markers=markers)

    # ------------------------------------------------------------------
    # Persistence (.ppd = JSON song spec + seed/output_map + UI extras)
    # ------------------------------------------------------------------
    def to_project(self, extra=None):
        """Serialisable project dict. `extra` carries UI-only state
        (selected_section, theme). Raises if there is no spec to save."""
        if self._spec is None:
            raise ValueError("no spec to save; build/generate a spec first")
        data = {
            "version": PROJECT_VERSION,
            "spec": copy.deepcopy(self._spec),
            "seed": self._seed,
            "output_map": self._output_map,
        }
        if self._context_path is not None:
            # Additive, optional — no PROJECT_VERSION bump (the version check is
            # strict equality, so bumping would make every existing .ppd
            # unloadable). `auto_offset_s` must be persisted too: load_project
            # does not re-run analysis, so the nudge alone would restore a
            # silently wrong alignment.
            data["context_audio"] = {
                "path": self._context_path,
                "nudge_ms": self._context_nudge_ms,
                "auto_offset_s": self._auto_offset_s,
                "detected_tempo": self._detected_tempo,
            }
        data["align_export"] = self._align_export
        if extra:
            data.update(extra)
        return data

    def save_project(self, path, *, extra=None):
        """Write the current project to `path` as JSON. Returns the path."""
        with open(path, "w") as f:
            json.dump(self.to_project(extra), f, indent=2)
        return path

    def load_project(self, path):
        """Load a `.ppd`, replacing held spec/seed/output_map. Validates BEFORE
        mutating any state: a bad version or non-dict spec raises `ValueError`
        with `self._spec` untouched. An unknown/missing output_map does NOT raise
        — it falls back to GENERAL_MIDI and is reported in the returned
        ``warnings`` list. Returns the full dict so the UI can restore
        selected_section/theme and surface warnings."""
        with open(path) as f:
            data = json.load(f)
        if data.get("version") != PROJECT_VERSION:
            raise ValueError(
                f"unsupported project version {data.get('version')!r} "
                f"(expected {PROJECT_VERSION})")
        spec = data.get("spec")
        if not isinstance(spec, dict):
            raise ValueError("project file has no valid 'spec'")
        warnings = []
        omap = data.get("output_map", DEFAULT_OUTPUT_MAP)
        try:
            engine.get_output_map(omap)
        except Exception:                              # noqa: BLE001 - unknown map
            warnings.append(
                f"output map {omap!r} not found; using {DEFAULT_OUTPUT_MAP}.")
            omap = DEFAULT_OUTPUT_MAP
        # All validated — now mutate.
        self._spec = copy.deepcopy(spec)
        seed = data.get("seed")
        self._seed = int(seed) if seed is not None else None
        self._output_map = omap
        self._reset_history()
        self._invalidate_preview()
        self._align_export = bool(data.get("align_export", True))
        self._restore_context_audio(data.get("context_audio"), warnings)
        return {**data, "output_map": omap, "warnings": warnings}

    def _restore_context_audio(self, block, warnings):
        """Re-attach a saved context track. NEVER raises: the audio libs are
        imported lazily inside load_context_audio, so a machine without
        fluidsynth/portaudio/soundfile — or a moved audio file — must degrade to
        a warning, exactly like an unknown output map."""
        self.unload_context_audio()
        self._auto_offset_s = 0.0
        self._context_nudge_ms = 0
        self._detected_tempo = None
        self._context_error = None
        if not isinstance(block, dict):
            return
        self._auto_offset_s = float(block.get("auto_offset_s") or 0.0)
        self._context_nudge_ms = int(block.get("nudge_ms") or 0)
        dt = block.get("detected_tempo")
        self._detected_tempo = float(dt) if dt else None
        path = block.get("path")
        if not path:
            return
        try:
            self.load_context_audio(path)
        except Exception as exc:                       # noqa: BLE001 - see docstring
            # Remembered so `mix_warnings` keeps surfacing it — an export would
            # otherwise silently lose the alignment the project was saved with.
            self._context_error = f"context audio {path!r} could not be loaded: {exc}"
            warnings.append(self._context_error)

    def write_note_ladder(self, out_path, *, output_map=None):
        """Emit a one-hit-per-role ladder ``.mid`` for auditing an output map's
        articulations in a sampler (e.g. verifying EZ_DRUMMER_3 in EZD3)."""
        omap = self._resolve_map(output_map if output_map is not None
                                 else self._output_map)
        return engine.write_note_ladder(out_path, output_map=omap)

    # ------------------------------------------------------------------
    # Audio analysis (F2) — librosa audio -> editable result -> spec
    # ------------------------------------------------------------------
    @property
    def analysis(self):
        """The last AnalysisResult produced by analyze_audio, or None."""
        return self._analysis

    def analyze_audio(self, path, *, alignment="fixed_grid", known_tempo=None,
                      beats_per_bar=analyze.BEATS_PER_BAR_DEFAULT,
                      cut_to_click=False):
        """Analyse an audio file into an editable AnalysisResult; hold it.

        Also captures the alignment context the mix needs: the lead-in (seconds
        to the first downbeat, which the drums are shifted by) and the detected
        tempo (the reference for the drift warning and the count-in click).
        """
        self._analysis = analyze.analyze_audio(
            path, alignment=alignment, known_tempo=known_tempo,
            beats_per_bar=beats_per_bar, cut_to_click=cut_to_click)
        self._auto_offset_s = float(self._analysis.lead_in_s)
        self._detected_tempo = float(self._analysis.tempo)
        self._context_nudge_ms = 0            # a new analysis resets the manual fix
        self._invalidate_preview()
        return self._analysis

    def spec_from_analysis(self, profile, *, result=None, overrides=None):
        """Build (and hold as current) an engine spec from an analysis result and
        a chosen profile. `result` defaults to the held analysis."""
        result = result if result is not None else self._analysis
        if result is None:
            raise ValueError("no analysis; call analyze_audio or pass result=")
        self._spec = analyze.spec_from_analysis(result, profile, overrides=overrides)
        self._reset_history()
        return self._spec

    # ------------------------------------------------------------------
    # Playback (F4) — offline render -> buffer -> sounddevice transport
    # ------------------------------------------------------------------
    def load_context_audio(self, path, *, sample_rate=44100, buffer=None):
        """Load an audio track to mix previews over ('hear it over my track').

        `buffer` accepts an already-decoded buffer (the drop view decodes on its
        analysis worker thread so the UI never blocks on a full-song decode).
        """
        from . import playback  # lazy: keep the MIDI path usable without audio libs
        if buffer is None:
            buffer = playback.load_audio(path, sample_rate=sample_rate)
        self._context_audio = buffer
        self._context_sr = sample_rate
        self._context_path = str(path) if path is not None else None
        self._context_len_s = len(buffer) / float(sample_rate) if sample_rate else 0.0
        self._context_error = None
        self._invalidate_preview()
        return self._context_audio

    def unload_context_audio(self):
        """Drop the loaded context track (mix controls disable again)."""
        self._context_audio = None
        self._context_sr = None
        self._context_path = None
        self._context_len_s = 0.0
        self._invalidate_preview()

    @property
    def has_context_audio(self):
        return self._context_audio is not None

    @property
    def context_path(self):
        return self._context_path

    @property
    def context_offset_s(self):
        """Seconds from the start of the track to musical tick 0 of the drums:
        the analysis lead-in plus the manual nudge. May be negative (nudged
        earlier than the detected downbeat)."""
        return self._auto_offset_s + self._context_nudge_ms / 1000.0

    @property
    def context_nudge_ms(self):
        return self._context_nudge_ms

    def set_context_nudge(self, ms):
        """Manual alignment correction in milliseconds (+/- one bar, clamped by
        the UI). Invalidates the preview."""
        self._context_nudge_ms = int(ms)
        self._invalidate_preview()
        return self._context_nudge_ms

    def nudge_beat(self, direction):
        """Shift the alignment by exactly one beat at the current tempo. The beat
        detector has no phase estimation, so a one-beat correction is the common
        fix (see PHASE9_plan Risk A)."""
        tempo = self._alignment_tempo()
        self._context_nudge_ms += int(round((1 if direction >= 0 else -1)
                                            * 60_000.0 / tempo))
        self._invalidate_preview()
        return self._context_nudge_ms

    def _alignment_tempo(self):
        """Tempo the alignment maths runs at: the DETECTED tempo when known (the
        track's own grid), else the spec's."""
        if self._detected_tempo:
            return float(self._detected_tempo)
        if self._spec is not None:
            t = self._spec.get("tempo")
            if t:
                return float(t)
            return float(engine.PROFILES[self._spec["profile"]]["tempo"])
        return 120.0

    @property
    def mix_gains(self):
        return {"drums": self._drums_gain, "bed": self._bed_gain}

    def set_mix_gains(self, *, drums=None, bed=None):
        """Set the preview mix gains (1.0 = unity). Invalidates the preview."""
        if drums is not None:
            self._drums_gain = max(0.0, float(drums))
        if bed is not None:
            self._bed_gain = max(0.0, float(bed))
        self._invalidate_preview()
        return self.mix_gains

    @property
    def align_export(self):
        return self._align_export

    def set_align_export(self, on):
        """Whether export pads the .mid by the alignment offset so it drops into
        the DAW where it was auditioned."""
        self._align_export = bool(on)
        return self._align_export

    def _export_offset_ticks(self, spec, tempo, ppq, align):
        """Ticks of silence to prepend on export so the .mid lands under the
        track. Only ever positive — a negative alignment means the drums start
        before the file does, which no amount of padding can express."""
        if not align or not self.has_context_audio:
            return 0
        offset = max(0.0, self.context_offset_s)
        return int(round(offset * ppq * tempo / 60.0))

    @property
    def mix_warnings(self):
        """User-facing warnings about the current mix (empty when all is well)."""
        out = []
        if self._context_error:
            out.append(self._context_error)
        if not self.has_context_audio or self._spec is None:
            return out
        tempo = self._spec.get("tempo") or engine.PROFILES[self._spec["profile"]]["tempo"]
        tempo = float(tempo)
        if self._detected_tempo:
            # Express drift as time ACCUMULATED over the track, not raw BPM: a
            # 0.5 BPM error matters over 4 minutes and not at all over 20 seconds.
            drift_s = (abs(tempo - self._detected_tempo) / self._detected_tempo
                       * self._context_len_s)
            if drift_s > 0.5 * 60.0 / tempo:          # half a beat
                out.append(
                    f"Tempo drift: {tempo:g} BPM vs {self._detected_tempo:.1f} "
                    f"detected — drums drift ~{drift_s:.1f}s over the track.")
        drums_len_s = self._drums_length_s(self._spec)
        gap = abs(drums_len_s - max(0.0, self._context_len_s - max(0.0, self.context_offset_s)))
        bar_s = 4 * 60.0 / tempo
        if gap > bar_s:
            out.append(
                f"Length mismatch: drums {drums_len_s:.0f}s vs track "
                f"{self._context_len_s:.0f}s ({gap:.0f}s apart).")
        return out

    def _drums_length_s(self, spec):
        """Musical length of the arrangement in seconds (excludes render tail)."""
        if not spec.get("sections"):
            return 0.0
        tempo = spec.get("tempo") or engine.PROFILES[spec["profile"]]["tempo"]
        ppq = spec.get("ppq", 480)
        return engine.song_ticks(spec) * 60.0 / (float(tempo) * ppq)

    def render_preview(self, spec=None, *, seed=None, sample_rate=44100,
                       with_context=False, count_in=None):
        """Render the spec's drums to an audio buffer and hold it.

        Preview always uses GENERAL_MIDI (the bundled sf2 is a GM bank; an EZD3
        map would mis-trigger), consistent with `generate`. Held-seed contract
        matches `generate`. With `with_context`, mixes over the loaded context
        track. Returns a stereo float32 buffer.
        """
        from . import playback
        spec = spec if spec is not None else self._spec
        if spec is None:
            raise ValueError("no spec to render; generate/build a spec or pass spec=")
        if seed is not None:
            self._seed = int(seed)
        self._spec = spec
        events = engine.build_song(spec, seed=self._ensure_seed(),
                                   output_map=engine.GENERAL_MIDI)
        tempo = spec.get("tempo") or engine.PROFILES[spec["profile"]]["tempo"]
        buf = playback.render_events(
            events, tempo=tempo, ppq=spec.get("ppq", 480), sample_rate=sample_rate)
        # Count-in is PREVIEW ONLY — never in export (export uses
        # build_song/write_midi, not this path).
        ci = self._count_in if count_in is None else int(count_in)
        if with_context and self._context_audio is not None:
            buf, self._preview_offset = self._mix_with_context(
                playback, buf, ci, sample_rate)
        elif ci > 0:
            import numpy as np
            click = playback.click_track(ci, tempo, sample_rate=sample_rate)
            buf = np.concatenate([click, buf])
            self._preview_offset = ci * 60.0 / tempo
        else:
            self._preview_offset = 0.0
        self._preview_buf, self._preview_sr = buf, sample_rate
        # The held buffer is what play() will load, so the playhead head matches
        # it until a play_section slice replaces it.
        self._play_head_s = self._preview_offset
        return buf

    def _context_bed(self, playback, sample_rate):
        """The context track at `sample_rate`, re-loading if the held buffer was
        decoded at a different rate (mixing buffers of differing rates would play
        the track at the wrong speed and scale every offset wrongly)."""
        if self._context_sr == sample_rate or self._context_audio is None:
            return self._context_audio
        if self._context_path is None:
            raise ValueError(
                f"context audio is at {self._context_sr} Hz but the preview "
                f"renders at {sample_rate} Hz, and the source path is unknown")
        self._context_audio = playback.load_audio(self._context_path,
                                                  sample_rate=sample_rate)
        self._context_sr = sample_rate
        self._context_len_s = len(self._context_audio) / float(sample_rate)
        return self._context_audio

    def _mix_with_context(self, playback, drums, count_in_beats, sample_rate):
        """Mix the rendered drums over the context track, aligned to the track's
        first downbeat. Returns `(buffer, preview_offset_seconds)`.

        Offset bookkeeping (PHASE9_plan §A) — `preview_offset` is the seconds of
        buffer before musical tick 0 and is NEVER negative:

            o         = context_offset_s            (may be negative)
            deficit   = count-in that does not fit in the lead-in
            drums_pad = max(0, o) + deficit
            bed_pad   = max(0, -o) + deficit
        """
        bed = self._context_bed(playback, sample_rate)
        o = self.context_offset_s
        click_tempo = self._alignment_tempo()      # the TRACK's grid, not the spec's
        need_s = max(0, int(count_in_beats)) * 60.0 / click_tempo
        deficit_s = max(0.0, need_s - max(0.0, o))
        drums_pad_s = max(0.0, o) + deficit_s
        bed_pad_s = max(0.0, -o) + deficit_s
        # normalize=False: the click is summed in below and must be inside the
        # peak calculation, or a mixed preview with a count-in can exceed 1.0 and
        # clip at the transport.
        buf = playback.mix(
            drums, bed, drums_gain=self._drums_gain, bed_gain=self._bed_gain,
            drums_pad_frames=int(round(drums_pad_s * sample_rate)),
            bed_pad_frames=int(round(bed_pad_s * sample_rate)),
            normalize=False)
        if count_in_beats > 0:
            # Lay the click OVER the track's lead-in, ending exactly at the first
            # downbeat, at the detected tempo — so it counts you into the TRACK.
            click = playback.click_track(count_in_beats, click_tempo,
                                         sample_rate=sample_rate)
            buf = playback.overlay(
                buf, click, int(round((drums_pad_s - need_s) * sample_rate)))
        return playback.peak_normalize(buf), drums_pad_s

    @property
    def preview_offset(self):
        """Seconds of count-in prepended to the current preview buffer (0 if none).
        The playhead subtracts this to map playback position to musical time."""
        return self._preview_offset

    def set_count_in(self, beats):
        """Set the preview count-in length in beats (0 = off)."""
        self._count_in = max(0, int(beats))
        self._invalidate_preview()

    def audition(self, spec, *, seed=0, sample_rate=44100):
        """Render a THROWAWAY spec into the preview buffer for immediate playback,
        WITHOUT touching the held spec/seed (groove-browser audition path — unlike
        `render_preview`, which holds its spec/seed). Uses a fixed local seed so
        auditions are deterministic and independent of the arrangement's seed.
        Returns the buffer; play with `play()`."""
        from . import playback
        events = engine.build_song(spec, seed=int(seed),
                                   output_map=engine.GENERAL_MIDI)
        buf = playback.render_events(
            events, tempo=spec.get("tempo") or engine.PROFILES[spec["profile"]]["tempo"],
            ppq=spec.get("ppq", 480), sample_rate=sample_rate)
        self._preview_buf, self._preview_sr = buf, sample_rate
        self._preview_offset = 0.0                 # auditions have no count-in
        return buf

    def context_snapshot(self, *, sample_rate=44100):
        """An immutable snapshot of the mix state, taken on the UI thread and
        handed to `render_variation` on a worker thread. Nothing a worker touches
        may live on `self` — see `render_variation`'s purity contract.

        Any re-decode for a differing sample rate happens HERE (on the caller's
        thread), so the worker never triggers one.
        """
        if self._context_audio is None:
            return None
        from . import playback
        bed = self._context_bed(playback, sample_rate)
        return {"bed": bed, "offset_s": self.context_offset_s,
                "drums_gain": self._drums_gain, "bed_gain": self._bed_gain,
                "sample_rate": sample_rate}

    def render_variation(self, seed, *, sample_rate=44100, with_context=False,
                         context=None):
        """Render the CURRENT spec at an explicit `seed` to a standalone buffer,
        WITHOUT touching held spec/seed/preview (batch-variations / A-B compare).
        Pure (build_song + render_events) so it is safe to call off a worker
        thread — as long as no held-state render runs concurrently. Returns the
        stereo float32 buffer."""
        from . import playback
        spec = self._require_spec()
        events = engine.build_song(spec, seed=int(seed),
                                   output_map=engine.GENERAL_MIDI)
        buf = playback.render_events(
            events, tempo=spec.get("tempo") or engine.PROFILES[spec["profile"]]["tempo"],
            ppq=spec.get("ppq", 480), sample_rate=sample_rate)
        if with_context:
            snap = context if context is not None else \
                self.context_snapshot(sample_rate=sample_rate)
            if snap is not None:
                buf = self._mix_variation(playback, buf, snap)
        return buf

    @staticmethod
    def _mix_variation(playback, drums, snap):
        """Mix ONE variation over only the span of the track the drums cover.

        Mixing the full track into every variation would hold a complete copy of
        the audio per seed (~84MB per 4-minute track, times N seeds). The
        audition only ever plays the drums' own span, so the bed is sliced to it.

        Static and snapshot-driven ON PURPOSE: it runs on the variations worker
        thread, so it must not read (or write) any controller attribute.
        """
        sr = snap["sample_rate"]
        o = snap["offset_s"]
        start = int(round(max(0.0, o) * sr))
        bed_slice = snap["bed"][start:start + len(drums)]
        return playback.mix(drums, bed_slice,
                            drums_gain=snap["drums_gain"], bed_gain=snap["bed_gain"],
                            bed_pad_frames=int(round(max(0.0, -o) * sr)))

    def play_buffer(self, buf, sample_rate=44100):
        """Play an arbitrary pre-rendered buffer (a batch/A-B variation) through the
        shared transport. Does not disturb the held preview buffer/offset used by
        the main play()."""
        from . import playback
        self._play_base = 0.0
        self._play_head_s = 0.0
        if self._player is None:
            self._player = playback.Player()
        self._player.load(buf, sample_rate)
        self._player.play()

    @property
    def playhead_offset(self):
        """Seconds of the CURRENTLY PLAYING buffer that sit before musical tick 0.
        The playhead subtracts this. Distinct from `preview_offset`, which
        describes the held preview buffer: a section slice has its head cut off
        (0) while the held buffer keeps its own."""
        return self._play_head_s

    @property
    def play_base(self):
        """Musical seconds at which the currently-playing buffer starts (0 for the
        full song; the section start when auditioning a single section). The
        playhead adds this to the transport position to map back to the grid."""
        return self._play_base

    def play_section(self, section_index):
        """Play ONLY the selected section, sliced out of the held full-song preview
        buffer so it matches exactly what plays in context (same seed-resolved
        groove/fill). Requires a current preview (render first)."""
        from . import playback
        if self._preview_buf is None:
            raise ValueError("no rendered preview; render before play_section")
        spec = self._require_spec()
        markers = engine.compute_section_markers(spec)
        if not 0 <= section_index < len(markers):
            raise IndexError(f"section {section_index} out of range")
        tempo = spec.get("tempo") or engine.PROFILES[spec["profile"]]["tempo"]
        ppq = spec.get("ppq", 480)
        sec_per_tick = 60.0 / (tempo * ppq)
        sr = self._preview_sr
        head = int(round(self._preview_offset * sr))     # count-in prepended to buf
        start_tick = markers[section_index][0]
        start_s = head + int(round(start_tick * sec_per_tick * sr))
        if section_index + 1 < len(markers):
            end_s = head + int(round(markers[section_index + 1][0] * sec_per_tick * sr))
        else:
            # Last section: run to the END OF THE DRUMS plus the render tail, NOT
            # to the end of the buffer — a context mix leaves the rest of the
            # track sitting in the buffer, which would audition minutes of bare
            # backing track.
            # The tail is part of EVERY render (render_events(tail=...)), mixed or
            # dry — the min() below handles a buffer that is shorter.
            end_ticks = engine.song_ticks(spec)
            end_s = head + int(round(
                (end_ticks * sec_per_tick + playback.RENDER_TAIL_S) * sr))
        end_s = min(end_s, self._preview_buf.shape[0])
        clip = self._preview_buf[start_s:end_s]
        # The SLICE has no head — but `_preview_offset` describes the held preview
        # buffer, which is unchanged, so it must not be zeroed here (a second
        # play_section on the same buffer would then slice from the wrong frame).
        self._play_head_s = 0.0
        self._play_base = start_tick * sec_per_tick      # playhead offset back to grid
        if self._player is None:
            self._player = playback.Player()
        self._player.load(clip, sr)
        self._player.play()

    def play(self, *, with_context=False):
        """Play the held preview (rendering on demand from the current spec if
        none is held). Raises if there is neither a preview nor a spec."""
        from . import playback
        if self._preview_buf is None:
            if self._spec is None:
                raise ValueError("nothing to play: no rendered preview and no spec")
            self.render_preview(with_context=with_context)
        self._play_base = 0.0                        # full song starts at musical 0
        self._play_head_s = self._preview_offset     # head of the buffer being played
        if self._player is None:
            self._player = playback.Player()
        self._player.load(self._preview_buf, self._preview_sr)
        self._player.play()

    def stop(self):
        if self._player is not None:
            self._player.stop()

    def seek(self, seconds):
        if self._player is not None:
            self._player.seek(seconds)

    @property
    def playback_position(self):
        return self._player.position if self._player is not None else 0.0
