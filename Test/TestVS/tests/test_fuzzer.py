from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from terminalist.pyte_patch import filter_private_modes
from Test.TestVS.fuzzer import fuzz_sequence, fuzz_with_filter
from Test.TestVS.sequences import NORMAL, SHOULD_IGNORE


def test_known_problem_sequences_fail_raw():
    raw_results = {
        seq: fuzz_sequence(seq, desc)
        for seq, _source, desc in SHOULD_IGNORE
        if seq in ("\x1b[<u", "\x1b[>4;2m")
    }

    assert raw_results["\x1b[<u"].passed is False
    assert raw_results["\x1b[>4;2m"].passed is False


def test_should_ignore_sequences_pass_after_filter():
    failures = [
        result.summary()
        for seq, source, desc in SHOULD_IGNORE
        if not (result := fuzz_with_filter(seq, f"[{source}] {desc}")).passed
    ]
    assert failures == []


def test_normal_sequences_are_not_stripped():
    changed = [seq for seq, _desc in NORMAL if filter_private_modes(seq) != seq]
    assert changed == []
