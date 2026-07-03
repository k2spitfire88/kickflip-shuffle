# Phase 7 — Packaging: unsigned `.app` (DRAFT for Plan-gate)

Build `Kickflip Shuffle.app` with py2app, bundling every runtime dep (native
`libfluidsynth` + transitive dylibs, librosa/numba stack, `.sf2`, fonts, art,
icon) so it double-click-launches on a clean Mac with no dev environment.

> **Supervised build.** Unlike phases 1–6, the core of Phase 7 (the py2app build +
> second-machine launch verification + native-dylib debugging) is iterative and
> environment-bound — it cannot be validated by the offscreen pytest suite. Land
> `setup.py` + the import shim, then run the build/verify loop WITH the owner. Do
> not treat a green pytest run as "Phase 7 done".

## Owner decisions (LOCKED 2026-07-03)

- **Bundle identifier** = `com.kickflipshuffle.app` (`CFBundleIdentifier`).
- **Version** = `0.9.0` (beta) — `CFBundleShortVersionString` +
  `CFBundleVersion`; bump on each rebuild.
- **Bundle the 148 MB `FluidR3_GM.sf2`** into the app (offline, self-contained;
  `.app` ~300 MB).
- **Unsigned** — no Developer ID / notarization this phase; document right-click →
  Open for Gatekeeper.

## Facts (verified 2026-07-03)

- `py2app` 0.28.10 in `.venv`. `python@3.11` (Homebrew) — matches the app runtime.
- **`import fluidsynth` resolves the dylib AT IMPORT TIME** (`fluidsynth.py`:
  module-level `lib = find_libfluidsynth()`; then `CDLL(lib)`). Resolution order:
  `ctypes.util.find_library("fluidsynth"…)` → then `$HOMEBREW_PREFIX/lib/
  libfluidsynth.dylib`. On a machine without Homebrew BOTH fail → `ImportError`.
  `app/playback.py:20` does `import fluidsynth` at module import.
- Native dylib present at `/opt/homebrew/lib/libfluidsynth.3.dylib` (+ `.dylib`,
  `.3.5.4.dylib`). It links a DEEP tree of Homebrew dylibs (glib, gthread,
  libsndfile, libomp, readline, …) — all must be bundled + `install_name`-fixed.
- Other native deps: `sounddevice` → PortAudio dylib; `numba`/`llvmlite` ship
  their own native libs and need hidden-import/data handling under py2app; scipy.
- Assets on disk: `assets/icon/KickflipShuffle.icns`,
  `assets/soundfonts/FluidR3_GM.sf2` (gitignored, 148 MB),
  `assets/fonts/*.ttf` (4, licenses beside them), `assets/textures/grit.png`,
  `assets/art/keyart.png`. `theme.asset_path()` is how the app locates these at
  runtime — must resolve under the bundle (see step 4).

## Steps

1. **`setup.py`** (py2app): `APP=["main.py"]`, `OPTIONS` with `iconfile`,
   `plist` (CFBundleIdentifier/Name/ShortVersionString, `NSHighResolutionCapable`,
   `LSMinimumSystemVersion`), `packages=[librosa, numba, llvmlite, scipy, soundfile,
   sounddevice, PySide6, engine, app]`, `includes` for hidden imports,
   `resources=[assets/soundfonts, assets/fonts, assets/textures, assets/art]`,
   and `frameworks=[the libfluidsynth dylib chain]`.
   - **Qt bundling (plan-gate 🔴):** py2app does NOT auto-bundle the Qt frameworks
     or the **`libqcocoa.dylib` platform plugin** — without them the GUI won't
     initialize on a clean Mac. Ensure the PySide6 recipe pulls Qt frameworks +
     `platforms/libqcocoa.dylib` (and any needed `styles`/`imageformats` plugins);
     verify they exist under `Contents/Resources/.../PySide6/Qt/plugins/platforms/`
     in the built bundle. This is a first-launch blocker, not an optional polish.
2. **Frozen-app dylib shim** — new `app/_bootstrap.py` imported at the very top of
   `main.py` (before anything imports `fluidsynth`/`playback`): when running frozen
   (`getattr(sys, "frozen", False)`).
   - **DO NOT rely on `HOMEBREW_PREFIX`** (plan-gate 🔴): `find_libfluidsynth()`
     calls `ctypes.util.find_library("fluidsynth"…)` FIRST and only falls back to
     `$HOMEBREW_PREFIX/lib` if that returns nothing. On any machine that HAS
     Homebrew's libfluidsynth, `find_library` returns the SYSTEM copy → the bundled
     dylib is never used (wrong/mismatched lib). The env fallback is unreachable
     there.
   - **Correct mechanism:** monkeypatch `ctypes.util.find_library` in `_bootstrap`
     (before `import fluidsynth` anywhere) so a request for `fluidsynth`/
     `libfluidsynth*` returns the BUNDLED absolute path; delegate all other names
     to the original. This forces resolution to the bundled copy regardless of a
     system install. (macOS SIP strips `DYLD_LIBRARY_PATH` from find_library, so
     that route is unreliable — do not use it.)
   - `app.playback` (hence `import fluidsynth`) is LAZY (imported inside controller
     methods, not at module load), so a `_bootstrap` import at the top of `main()`
     reliably runs first. Still, import `_bootstrap` as the FIRST line of `main.py`.
3. **Gather + relocate dylibs** — libfluidsynth pulls a transitive brew tree;
   py2app's `frameworks` + a `delocate`/`install_name_tool` pass to rewrite
   `@rpath`/absolute brew paths to bundle-relative. This is the iterative part.
4. **Asset resolution under the bundle** — `theme.asset_path()` uses
   `__file__`-relative `parents[2]/"assets"`; `playback` uses
   `parents[1]/"assets/soundfonts/FluidR3_GM.sf2"`. These resolve automatically IF
   py2app preserves the `app/` + `assets/` tree under `Contents/Resources/`
   (plan-gate: likely automatic). **Verify the built bundle layout first; add a
   frozen branch ONLY if the relative paths actually break** — don't pre-build one.
5. **Docs** — README/HANDOFF: right-click → Open (unsigned Gatekeeper), build
   command (`python setup.py py2app`), and the second-account verification.

## Risks / gotchas

- 🔴 **Transitive dylib hell** — libfluidsynth's brew deps must all be bundled and
  `install_name`-fixed; a missing/abs-path dylib = crash on a clean machine only
  (works on the dev box, fails on verify). This is the main time sink.
- 🔴 **Import-time failure** — because `import fluidsynth` resolves eagerly, the
  shim (step 2) MUST run before `app.playback` is imported anywhere, including via
  tests of the frozen bundle. Any early `import playback` defeats it.
- 🟡 **numba/llvmlite frozen** — commonly needs `includes`/`packages` tuning and
  can bloat/fail; may need `OPTIONS["packages"]` + excluding numba caching to temp.
  NOTE: `analyze.py` (librosa → numba/llvmlite/scipy) is imported EAGERLY —
  `controller.py` imports `analyze` at module level — so this stack loads at app
  startup (controller construction), not just on Drop-audio use. Higher-priority
  bundling risk than "lazy" would imply.
- 🟡 **sounddevice/PortAudio** dylib bundling, same class as fluidsynth (lazy —
  `playback` is imported inside controller methods).
- 🟡 **soundfile → libsndfile** native dylib — same relocation class as
  fluidsynth/PortAudio; confirm py2app framework discovery pulls it or add it
  explicitly.
- 🟡 **sf2 size** — 148 MB gitignored asset must be present at build; CI/build
  scripts need it staged. App ~300 MB.
- 🔵 **Fonts at runtime** — `register_fonts()` reads `assets/fonts`; ensure the
  frozen path resolves (offscreen tests already fall back to system fonts).

## Verify (manual, supervised)

- `python setup.py py2app`; launch `dist/Kickflip Shuffle.app` locally.
- Copy to a **second user account / Mac with no dev env**; right-click → Open;
  confirm: window renders, fonts load, Generate → play (fluidsynth), export writes,
  Drop-audio analyse (librosa), save/load `.ppd`, undo/redo. No console dylib
  errors.

## Test plan (what CAN be automated)

- Unit test the shim in isolation (`tests/test_bootstrap.py`): with a faked
  `sys.frozen` + a temp bundle dir containing a stub `libfluidsynth.dylib`, assert
  the patched `ctypes.util.find_library("fluidsynth")` returns the BUNDLED path
  (not a system path) AND that other names still delegate to the original — i.e.
  a machine WITH Homebrew still resolves to the bundled copy (the 🔴 failure mode).
- Assert `_bootstrap` is a no-op when NOT frozen (dev box unaffected).
- Keep the offscreen suite green (setup.py/shim must not break normal `python
  main.py` / imports on the dev box).

## Files

- `setup.py` (new — py2app config)
- `app/_bootstrap.py` (new — frozen dylib shim) + `main.py` (import it first)
- `app/ui/theme.py` / `app/playback.py` (frozen asset-path branch if needed)
- `docs/HANDOFF.md` or `README` (build + Gatekeeper + verify notes)
- `tests/test_bootstrap.py` (new — shim unit test)
