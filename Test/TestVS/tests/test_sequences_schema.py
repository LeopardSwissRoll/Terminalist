from __future__ import annotations

from Test.TestVS.sequences import NORMAL, SHOULD_IGNORE


def test_should_ignore_entries_are_triplets():
    assert all(len(entry) == 3 for entry in SHOULD_IGNORE)


def test_normal_entries_are_pairs():
    assert all(len(entry) == 2 for entry in NORMAL)
