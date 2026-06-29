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
import random

import engine
from . import analyze

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
        return self._seed

    def new_seed(self):
        """Draw, store, and return a fresh seed (UI 'reroll')."""
        self._seed = random.randrange(_SEED_BOUND)
        return self._seed

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

    # ------------------------------------------------------------------
    # Spec construction
    # ------------------------------------------------------------------
    def song_from_profile(self, profile_name, overrides=None):
        """Build a default-arrangement spec for a profile; store as current."""
        self._spec = engine.song_from_profile(profile_name, overrides)
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
        spec_tempo = tempo if tempo is not None else engine.PROFILES[profile]["tempo"]
        if sections is None:
            sections = engine.song_from_profile(profile, overrides or None)["sections"]
        self._spec = {
            "ppq": ppq,
            "profile": profile,
            "tempo": spec_tempo,
            "overrides": overrides,
            "sections": sections,
        }
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
        return engine.write_midi(events, out_path, tempo=tempo, ppq=ppq)

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

    def analyze_audio(self, path, *, alignment="fixed_grid", known_tempo=None):
        """Analyse an audio file into an editable AnalysisResult; hold it."""
        self._analysis = analyze.analyze_audio(
            path, alignment=alignment, known_tempo=known_tempo)
        return self._analysis

    def spec_from_analysis(self, profile, *, result=None, overrides=None):
        """Build (and hold as current) an engine spec from an analysis result and
        a chosen profile. `result` defaults to the held analysis."""
        result = result if result is not None else self._analysis
        if result is None:
            raise ValueError("no analysis; call analyze_audio or pass result=")
        self._spec = analyze.spec_from_analysis(result, profile, overrides=overrides)
        return self._spec

    # ------------------------------------------------------------------
    # Future-phase capabilities — surface locked now, bodies land later.
    # ------------------------------------------------------------------
    def render_preview(self, spec=None):
        raise NotImplementedError("Phase 4: F4 playback render (render_preview)")

    def play(self, *args, **kwargs):
        raise NotImplementedError("Phase 4: F4 transport (play)")

    def stop(self):
        raise NotImplementedError("Phase 4: F4 transport (stop)")
