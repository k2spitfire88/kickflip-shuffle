"""List helpers expose every key with a description parsed from grooves.md."""
import engine

AXES = {"ghost", "ornament", "double_bass", "syncopation",
        "breakdown", "fill_prob", "humanize"}


def test_list_profiles_complete():
    rows = engine.list_profiles()
    assert {r["name"] for r in rows} == set(engine.PROFILES)
    for r in rows:
        assert r["era"] and isinstance(r["tempo"], int)
        assert AXES <= set(r["axes"])


def test_list_grooves_all_described():
    rows = engine.list_grooves()
    assert {r["name"] for r in rows} == set(engine.GROOVES)
    missing = [r["name"] for r in rows if not r["description"]]
    assert not missing, f"undocumented grooves in grooves.md: {missing}"


def test_list_fills_all_described():
    rows = engine.list_fills()
    assert {r["name"] for r in rows} == set(engine.FILLS)
    missing = [r["name"] for r in rows if not r["description"]]
    assert not missing, f"undocumented fills in grooves.md: {missing}"
