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
        self._preview_buf = None
        self._preview_sr = None
        self._preview_offset = 0.0      # seconds of count-in at the head of the buffer
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
        if self._spec is not None:
            profile = self._spec["profile"]
            overrides = dict(self._spec.get("overrides") or {})
            ppq = self._spec.get("ppq", 480)
            tempo = self._spec.get("tempo") or engine.PROFILES[profile]["tempo"]
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
        return {
            "ppq": ppq,
            "profile": profile,
            "tempo": float(tempo),
            "overrides": overrides,
            "sections": [section],
        }

    # ------------------------------------------------------------------
    # Spec construction
    # ------------------------------------------------------------------
    def song_from_profile(self, profile_name, overrides=None):
        """Build a default-arrangement spec for a profile; store as current."""
        self._spec = engine.song_from_profile(profile_name, overrides)
        self._reset_history()
        return self._spec

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
        prof = engine.PROFILES[spec["profile"]]
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
        (matches the pre-8e behaviour)."""
        self.new_seed()
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
    def export(self, out_path, *, spec=None, output_map=None, seed=None):
        """Render ``spec`` through the selected output map and write a ``.mid``.

        Reproduces the previewed generation: uses the held seed (an explicit
        ``seed`` is transient and does NOT overwrite the held one — export is a
        sink). Tempo is sourced from the spec (build_song's tempo param is
        inert) and applied at ``write_midi``.
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
        return {**data, "output_map": omap, "warnings": warnings}

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
                      beats_per_bar=analyze.BEATS_PER_BAR_DEFAULT):
        """Analyse an audio file into an editable AnalysisResult; hold it."""
        self._analysis = analyze.analyze_audio(
            path, alignment=alignment, known_tempo=known_tempo,
            beats_per_bar=beats_per_bar)
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
    def load_context_audio(self, path, *, sample_rate=44100):
        """Load an audio track to mix previews over ('hear it over my track')."""
        from . import playback  # lazy: keep the MIDI path usable without audio libs
        self._context_audio = playback.load_audio(path, sample_rate=sample_rate)
        self._context_sr = sample_rate
        return self._context_audio

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
        if with_context and self._context_audio is not None:
            buf = playback.mix(buf, self._context_audio)
        # Count-in is PREVIEW ONLY — prepended to the buffer here, never in export
        # (export uses build_song/write_midi, not this path).
        ci = self._count_in if count_in is None else int(count_in)
        if ci > 0:
            import numpy as np
            click = playback.click_track(ci, tempo, sample_rate=sample_rate)
            buf = np.concatenate([click, buf])
            self._preview_offset = ci * 60.0 / tempo
        else:
            self._preview_offset = 0.0
        self._preview_buf, self._preview_sr = buf, sample_rate
        return buf

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

    def render_variation(self, seed, *, sample_rate=44100):
        """Render the CURRENT spec at an explicit `seed` to a standalone buffer,
        WITHOUT touching held spec/seed/preview (batch-variations / A-B compare).
        Pure (build_song + render_events) so it is safe to call off a worker
        thread — as long as no held-state render runs concurrently. Returns the
        stereo float32 buffer."""
        from . import playback
        spec = self._require_spec()
        events = engine.build_song(spec, seed=int(seed),
                                   output_map=engine.GENERAL_MIDI)
        return playback.render_events(
            events, tempo=spec.get("tempo") or engine.PROFILES[spec["profile"]]["tempo"],
            ppq=spec.get("ppq", 480), sample_rate=sample_rate)

    def play_buffer(self, buf, sample_rate=44100):
        """Play an arbitrary pre-rendered buffer (a batch/A-B variation) through the
        shared transport. Does not disturb the held preview buffer/offset used by
        the main play()."""
        from . import playback
        self._play_base = 0.0
        if self._player is None:
            self._player = playback.Player()
        self._player.load(buf, sample_rate)
        self._player.play()

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
            end_s = self._preview_buf.shape[0]           # last section -> incl. tail
        clip = self._preview_buf[start_s:end_s]
        self._preview_offset = 0.0                       # the slice has no count-in
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
