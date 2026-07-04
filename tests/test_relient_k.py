"""Relient K profile + the 2000s-mall fingerprint spread (contrast polish)."""
import engine
from engine.generate import _AXIS_KEYS


def test_relient_k_registered_and_builds():
    profs = {p["name"] for p in engine.list_profiles()}
    assert "relient_k" in profs
    spec = engine.song_from_profile("relient_k")
    assert engine.build_song(spec, seed=1)                # renders a full song
    # Only references grooves/fills that exist (no runtime KeyError).
    for si in range(len(spec["sections"])):
        engine.resolved_bar(spec, si, 0, seed=1)


def test_relient_k_pools_valid():
    p = engine.PROFILES["relient_k"]
    grv = set(engine.GROOVES)
    for role in ("verse", "chorus", "bridge", "intro"):
        assert set(p[role]) <= grv, f"{role} has unknown groove"
    assert set(p["fills"]) <= set(engine.FILLS)


def test_melodic_2000s_fingerprints_distinct():
    # good_charlotte / simple_plan / all_time_low / relient_k used to share a flat
    # ghost/ornament fingerprint; they should now each be distinct.
    def fp(name):
        return tuple(engine.PROFILES[name][k] for k in _AXIS_KEYS)
    names = ["good_charlotte", "simple_plan", "all_time_low", "relient_k"]
    fps = [fp(n) for n in names]
    assert len(set(fps)) == len(names)                    # all unique
