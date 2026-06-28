"""Regression guard: build_song with the default (GENERAL_MIDI) map must
reproduce the frozen pre-refactor events byte-for-byte."""
import glob
import json
import os

import pytest

import engine

GOLDEN = os.path.join(os.path.dirname(__file__), "golden")
CASES = sorted(glob.glob(os.path.join(GOLDEN, "*.json")))


@pytest.mark.parametrize("path", CASES, ids=[os.path.basename(p) for p in CASES])
def test_golden_byte_identical(path):
    with open(path) as f:
        g = json.load(f)
    events = [list(e) for e in engine.build_song(g["spec"], seed=g["seed"])]
    assert events == g["events"], f"{g['name']} diverged from golden baseline"


def test_have_golden_cases():
    assert CASES, "no golden fixtures found"
