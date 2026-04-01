"""Pyte escape sequence fuzzer.

Feeds sequences to a fresh pyte Screen and detects:
1. Phantom characters: visible text that shouldn't be there
2. Attribute contamination: unexpected fg/bg/bold/underscore after sequence
3. Cursor displacement: cursor moved when it shouldn't have

Usage:
    python Test/TestVS/fuzzer.py                          # test cataloged sequences
    python Test/TestVS/fuzzer.py --log path/to/debug.log  # extract + test from log
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pyte

# Apply pyte patches (same as Terminalist does at startup)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from terminalist.pyte_patch import apply as patch_pyte, filter_private_modes

patch_pyte()


@dataclass
class FuzzResult:
    sequence: str
    description: str
    phantom_chars: list[str] = field(default_factory=list)
    attr_contamination: dict[str, object] = field(default_factory=dict)
    cursor_moved: bool = False
    passed: bool = True

    def summary(self) -> str:
        if self.passed:
            return f"  PASS  {self.description}: {self.sequence!r}"
        parts = [f"  FAIL  {self.description}: {self.sequence!r}"]
        if self.phantom_chars:
            parts.append(f"         phantom chars: {self.phantom_chars}")
        if self.attr_contamination:
            parts.append(f"         attr contamination: {self.attr_contamination}")
        if self.cursor_moved:
            parts.append(f"         cursor moved unexpectedly")
        return "\n".join(parts)


def fuzz_sequence(seq: str, description: str = "") -> FuzzResult:
    """Feed a single escape sequence to fresh pyte and check for side effects."""
    result = FuzzResult(sequence=seq, description=description or repr(seq))

    screen = pyte.Screen(40, 5)
    stream = pyte.Stream(screen)

    # Record initial state
    initial_cursor = (screen.cursor.x, screen.cursor.y)

    # Feed the sequence
    stream.feed(seq)

    # Check for phantom characters
    for y in range(screen.lines):
        for x in range(screen.columns):
            ch = screen.buffer[y][x]
            if ch.data != " ":
                result.phantom_chars.append(f"({x},{y})={ch.data!r}")
                result.passed = False

    # Check for attribute contamination on default cells
    # Feed a test character after the sequence to see if attributes leaked
    screen2 = pyte.Screen(40, 5)
    stream2 = pyte.Stream(screen2)
    stream2.feed(seq)
    stream2.feed("X")  # test char

    x_char = screen2.buffer[screen2.cursor.y][screen2.cursor.x - 1 if screen2.cursor.x > 0 else 0]
    contamination = {}
    if x_char.fg != "default":
        contamination["fg"] = x_char.fg
    if x_char.bg != "default":
        contamination["bg"] = x_char.bg
    if x_char.bold:
        contamination["bold"] = True
    if x_char.underscore:
        contamination["underscore"] = True
    if x_char.italics:
        contamination["italics"] = True
    if x_char.reverse:
        contamination["reverse"] = True
    if x_char.strikethrough:
        contamination["strikethrough"] = True
    if x_char.blink:
        contamination["blink"] = True

    if contamination:
        result.attr_contamination = contamination
        result.passed = False

    return result


def fuzz_with_filter(seq: str, description: str = "") -> FuzzResult:
    """Same as fuzz_sequence but applies filter_private_modes first."""
    filtered = filter_private_modes(seq)
    result = fuzz_sequence(filtered, description)
    result.sequence = seq  # report original sequence
    return result


def extract_sequences_from_log(log_path: str) -> list[tuple[str, str]]:
    """Extract unique escape sequences from a Terminalist debug log."""
    with open(log_path, "r", encoding="utf-8") as f:
        content = f.read()

    feeds = re.findall(r"data='(.*?)'", content)
    esc_seqs: dict[str, str] = {}

    for feed in feeds:
        try:
            data = feed.encode("utf-8").decode("unicode_escape")
        except Exception:
            data = feed

        for m in re.finditer(r"\x1b[\[\]()][^\x1b]*", data):
            seq = m.group()
            # Trim trailing content (non-escape text after the sequence)
            # CSI sequences end with a letter in 0x40-0x7E range
            csi_match = re.match(r"(\x1b\[[?>=!]*[\d;]*[A-Za-z~])", seq)
            if csi_match:
                clean = csi_match.group(1)
                if clean not in esc_seqs:
                    esc_seqs[clean] = f"from log: {clean!r}"
            # OSC sequences end with BEL or ST
            osc_match = re.match(r"(\x1b\][^\x07\x1b]*[\x07])", seq)
            if osc_match:
                clean = osc_match.group(1)
                if clean not in esc_seqs:
                    esc_seqs[clean] = f"from log: {clean!r}"

    return list(esc_seqs.items())


def main():
    from Test.TestVS.sequences import SHOULD_IGNORE, NORMAL

    log_path = None
    if "--log" in sys.argv:
        idx = sys.argv.index("--log")
        if idx + 1 < len(sys.argv):
            log_path = sys.argv[idx + 1]

    print("=" * 70)
    print("TestVS: Pyte Escape Sequence Fuzzer")
    print("=" * 70)

    # Phase 1: Test cataloged SHOULD_IGNORE sequences (without filter)
    print("\n── Phase 1: SHOULD_IGNORE sequences (raw, no filter) ──")
    raw_fails = []
    for seq, source, desc in SHOULD_IGNORE:
        result = fuzz_sequence(seq, f"[{source}] {desc}")
        print(result.summary())
        if not result.passed:
            raw_fails.append(result)

    # Phase 2: Test with filter_private_modes applied
    print("\n── Phase 2: SHOULD_IGNORE sequences (with filter) ──")
    filtered_fails = []
    for seq, source, desc in SHOULD_IGNORE:
        result = fuzz_with_filter(seq, f"[{source}] {desc}")
        print(result.summary())
        if not result.passed:
            filtered_fails.append(result)

    # Phase 3: Test NORMAL sequences (should work correctly)
    print("\n── Phase 3: NORMAL sequences (must not break) ──")
    normal_fails = []
    for seq, desc in NORMAL:
        filtered = filter_private_modes(seq)
        if filtered != seq:
            print(f"  FAIL  filter_private_modes stripped normal sequence: {seq!r}")
            normal_fails.append(seq)
        else:
            print(f"  PASS  {desc}: {seq!r}")

    # Phase 4: Log-extracted sequences (if provided)
    log_results = []
    if log_path:
        print(f"\n── Phase 4: Sequences from {log_path} ──")
        log_seqs = extract_sequences_from_log(log_path)
        for seq, desc in log_seqs:
            result = fuzz_with_filter(seq, desc)
            if not result.passed:
                print(result.summary())
                log_results.append(result)
            # else: silent pass for log sequences

        print(f"  Tested {len(log_seqs)} unique sequences, {len(log_results)} failures after filter")

    # Summary
    print(f"\n{'=' * 70}")
    print("Summary:")
    print(f"  SHOULD_IGNORE raw:      {len(raw_fails)} failures (expected — these are what we need to filter)")
    print(f"  SHOULD_IGNORE filtered: {len(filtered_fails)} failures (these need filter expansion)")
    print(f"  NORMAL preserved:       {len(normal_fails)} false strips (filter too aggressive)")
    if log_path:
        print(f"  Log sequences:          {len(log_results)} failures after filter")

    # Output the specific sequences that need filter expansion
    if filtered_fails:
        print(f"\n{'=' * 70}")
        print("FILTER GAPS — these sequences pass through filter_private_modes:")
        for r in filtered_fails:
            print(f"  {r.sequence!r}  →  {r.description}")
            if r.phantom_chars:
                print(f"    phantom: {r.phantom_chars}")
            if r.attr_contamination:
                print(f"    contamination: {r.attr_contamination}")

    sys.exit(1 if filtered_fails or normal_fails else 0)


if __name__ == "__main__":
    main()
