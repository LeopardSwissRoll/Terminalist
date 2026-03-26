"""Round-trip TUI tests — verify compositor VT100 output reconstructs correctly.

Tests the full pipeline: pyte Screen → compositor → VT100 → fresh pyte → compare.
Artifacts are ALWAYS generated to tests/output/{timestamp}/ for independent human review.

LIMITATION: Round-trip through pyte only verifies logical correctness.
Real terminal rendering differences (Windows Terminal, xterm.js) are not caught.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from terminalist.core.pane import Rect
from terminalist.frontend.split_tree import Direction, Leaf, Split, all_panes, layout

from conftest import make_pane, feed_pane, capture_compositor
from roundtrip.harness import (
    RoundTripResult,
    compare_frames,
    cleanup_old_runs,
    create_run_dir,
    reconstruct_frame,
    roundtrip_verify,
    write_artifacts,
)

# ── Shared run directory (created once per session) ──

_run_dir: Path | None = None


def _get_run_dir() -> Path:
    global _run_dir
    if _run_dir is None:
        _run_dir = create_run_dir()
        cleanup_old_runs(keep=5)
    return _run_dir


def _verify_and_save(
    scenario: str,
    comp,
    root,
    rect: Rect,
    output_list: list[str],
    panes: list,
    focused=None,
) -> RoundTripResult:
    """Run round-trip verification and save artifacts."""
    result = roundtrip_verify(comp, root, rect, output_list, focused)
    write_artifacts(_get_run_dir(), scenario, panes, result)
    return result


# ═══════════════════════════════════════════
#  Scenario 1: Single pane ASCII
# ═══════════════════════════════════════════


def test_roundtrip_single_ascii():
    pane = make_pane("a", 20, 5, "hello world")
    root = Leaf(pane)
    layout(root, Rect(0, 0, 20, 5))
    comp, output = capture_compositor(20, 5)

    result = _verify_and_save("01_single_ascii", comp, root, Rect(0, 0, 20, 5), output, [pane])
    assert result.passed, result.summary()


# ═══════════════════════════════════════════
#  Scenario 2: Colored + bold text
# ═══════════════════════════════════════════


def test_roundtrip_colored_bold():
    pane = make_pane("a", 30, 3)
    feed_pane(pane, "\x1b[1;31mBold Red\x1b[0m \x1b[32mGreen\x1b[0m")
    root = Leaf(pane)
    layout(root, Rect(0, 0, 30, 3))
    comp, output = capture_compositor(30, 3)

    result = _verify_and_save("02_colored_bold", comp, root, Rect(0, 0, 30, 3), output, [pane])
    assert result.passed, result.summary()


# ═══════════════════════════════════════════
#  Scenario 3: Vertical split (2 panes + border)
# ═══════════════════════════════════════════


def test_roundtrip_vsplit():
    a = make_pane("left", 39, 5, "LEFT")
    b = make_pane("right", 40, 5, "RIGHT")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 80, 5))
    comp, output = capture_compositor(80, 5)

    result = _verify_and_save("03_vsplit", comp, root, Rect(0, 0, 80, 5), output, [a, b])
    assert result.passed, result.summary()


# ═══════════════════════════════════════════
#  Scenario 4: Horizontal split
# ═══════════════════════════════════════════


def test_roundtrip_hsplit():
    a = make_pane("top", 20, 11, "TOP")
    b = make_pane("bottom", 20, 12, "BOT")
    root = Split(Direction.HORIZONTAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 20, 24))
    comp, output = capture_compositor(20, 24)

    result = _verify_and_save("04_hsplit", comp, root, Rect(0, 0, 20, 24), output, [a, b])
    assert result.passed, result.summary()


# ═══════════════════════════════════════════
#  Scenario 5: CJK wide characters
# ═══════════════════════════════════════════


def test_roundtrip_cjk():
    pane = make_pane("cjk", 20, 3)
    feed_pane(pane, "한글 test 日本語")
    root = Leaf(pane)
    layout(root, Rect(0, 0, 20, 3))
    comp, output = capture_compositor(20, 3)

    result = _verify_and_save("05_cjk", comp, root, Rect(0, 0, 20, 3), output, [pane])
    assert result.passed, result.summary()
    assert result.skipped_stubs > 0, "Should have CJK stubs"


# ═══════════════════════════════════════════
#  Scenario 6: Nested 3-pane layout
# ═══════════════════════════════════════════


def test_roundtrip_nested_3pane():
    main = make_pane("main", 47, 10, "Main pane content")
    tr = make_pane("top-right", 32, 4, "Top right")
    br = make_pane("bot-right", 32, 5, "Bottom right")
    root = Split(
        Direction.VERTICAL, 0.6,
        Leaf(main),
        Split(Direction.HORIZONTAL, 0.5, Leaf(tr), Leaf(br)),
    )
    layout(root, Rect(0, 0, 80, 10))
    comp, output = capture_compositor(80, 10)

    result = _verify_and_save(
        "06_nested_3pane", comp, root, Rect(0, 0, 80, 10), output, [main, tr, br]
    )
    assert result.passed, result.summary()


# ═══════════════════════════════════════════
#  Scenario 7: Diff render (MOST IMPORTANT)
# ═══════════════════════════════════════════


def test_roundtrip_diff_render():
    """Initial render + modify + diff render. Sequential VT100 feed must match."""
    pane = make_pane("a", 10, 3, "ABCDE")
    root = Leaf(pane)
    layout(root, Rect(0, 0, 10, 3))
    comp, output = capture_compositor(10, 3)

    # Initial render
    comp.render(root, Rect(0, 0, 10, 3))
    initial_vt100 = output[-1]

    # Modify one cell: overwrite position (col=2, row=0) with X
    feed_pane(pane, "\x1b[1;3HX")
    comp._dirty = True

    # Diff render
    comp.render(root, Rect(0, 0, 10, 3))
    diff_vt100 = output[-1]

    # Reconstruct: feed initial then diff into fresh screen
    reconstructed = reconstruct_frame(initial_vt100 + diff_vt100, 10, 3)

    # Compare against current composed frame
    current_frame = comp.compose(root, Rect(0, 0, 10, 3))
    result = compare_frames(current_frame, reconstructed, 10, 3)
    result.vt100_output = initial_vt100 + diff_vt100

    write_artifacts(_get_run_dir(), "07_diff_render", [pane], result)
    assert result.passed, result.summary()


# ═══════════════════════════════════════════
#  Scenario 8: Resize + full redraw
# ═══════════════════════════════════════════


def test_roundtrip_resize():
    pane = make_pane("a", 10, 5, "Hello")
    root = Leaf(pane)
    layout(root, Rect(0, 0, 10, 5))
    comp, output = capture_compositor(10, 5)

    # Initial render
    comp.render(root, Rect(0, 0, 10, 5))

    # Resize
    comp.resize(20, 8)
    pane.session.resize(20, 8)
    pane.rect = Rect(0, 0, 20, 8)
    layout(root, Rect(0, 0, 20, 8))

    # Full redraw after resize (prev_frame is invalidated)
    result = _verify_and_save(
        "08_resize", comp, root, Rect(0, 0, 20, 8), output, [pane]
    )
    assert result.passed, result.summary()


# ═══════════════════════════════════════════
#  Scenario 9: All SGR attributes
# ═══════════════════════════════════════════


def test_roundtrip_all_attrs():
    pane = make_pane("attrs", 40, 3)
    feed_pane(pane, "\x1b[1mBold\x1b[0m ")
    feed_pane(pane, "\x1b[3mItalic\x1b[0m ")
    feed_pane(pane, "\x1b[4mUnder\x1b[0m ")
    feed_pane(pane, "\x1b[7mReverse\x1b[0m ")
    feed_pane(pane, "\x1b[9mStrike\x1b[0m")
    root = Leaf(pane)
    layout(root, Rect(0, 0, 40, 3))
    comp, output = capture_compositor(40, 3)

    result = _verify_and_save("09_all_attrs", comp, root, Rect(0, 0, 40, 3), output, [pane])
    assert result.passed, result.summary()


# ═══════════════════════════════════════════
#  Scenario 10: Active border highlight
# ═══════════════════════════════════════════


def test_roundtrip_active_border():
    """Focused pane's adjacent borders should be green + bold."""
    from terminalist.frontend.compositor import BORDER_V_ACTIVE

    a = make_pane("left", 39, 5, "LEFT")
    b = make_pane("right", 40, 5, "RIGHT")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 80, 5))
    comp, output = capture_compositor(80, 5)

    # Render with "left" focused
    result = _verify_and_save(
        "10_active_border", comp, root, Rect(0, 0, 80, 5), output, [a, b],
        focused=a,
    )
    assert result.passed, result.summary()

    # Verify border cells have active style (green + bold)
    frame = result.original_frame
    border_char = frame[0][39]  # vertical border at x=39
    assert border_char.data == "│", f"Expected │, got {border_char.data!r}"
    assert border_char.fg == "green", f"Expected green fg, got {border_char.fg!r}"
    assert border_char.bold is True, "Active border should be bold"


# ═══════════════════════════════════════════
#  Scenario 11: Golden snapshot
# ═══════════════════════════════════════════


def test_roundtrip_golden_snapshot():
    """Snapshot test — creates golden file on first run, compares on subsequent."""
    from roundtrip.harness import format_frame_simple

    a = make_pane("left", 39, 3, "LEFT")
    b = make_pane("right", 40, 3, "RIGHT")
    root = Split(Direction.VERTICAL, 0.5, Leaf(a), Leaf(b))
    layout(root, Rect(0, 0, 80, 3))
    comp, output = capture_compositor(80, 3)

    frame = comp.compose(root, Rect(0, 0, 80, 3))
    current = format_frame_simple(frame, 80, 3)

    golden_path = Path(__file__).parent / "golden" / "vsplit_two_panes.txt"
    if not golden_path.exists():
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(current, encoding="utf-8")
        # First run: just create the golden file
    else:
        expected = golden_path.read_text(encoding="utf-8")
        assert current == expected, (
            f"Golden snapshot mismatch.\n"
            f"Update with: UPDATE_SNAPSHOTS=1 pytest\n"
            f"--- expected ---\n{expected}\n"
            f"--- actual ---\n{current}"
        )

    # Also run round-trip verification
    result = _verify_and_save(
        "10_golden_snapshot", comp, root, Rect(0, 0, 80, 3), output, [a, b]
    )
    assert result.passed, result.summary()


# ═══════════════════════════════════════════
#  Standalone runner
# ═══════════════════════════════════════════

results: list[tuple[str, bool, str]] = []


def run_test(name, fn):
    try:
        fn()
        print(f"  PASS  {name}")
        results.append((name, True, ""))
    except AssertionError as e:
        print(f"  FAIL  {name}: {e}")
        results.append((name, False, str(e)))
    except Exception as e:
        print(f"  FAIL  {name}: {type(e).__name__}: {e}")
        results.append((name, False, str(e)))


def main():
    print("=" * 60)
    print("Round-Trip TUI Tests")
    print("=" * 60)

    run_test("single_ascii", test_roundtrip_single_ascii)
    run_test("colored_bold", test_roundtrip_colored_bold)
    run_test("vsplit", test_roundtrip_vsplit)
    run_test("hsplit", test_roundtrip_hsplit)
    run_test("cjk", test_roundtrip_cjk)
    run_test("nested_3pane", test_roundtrip_nested_3pane)
    run_test("diff_render", test_roundtrip_diff_render)
    run_test("resize", test_roundtrip_resize)
    run_test("all_attrs", test_roundtrip_all_attrs)
    run_test("active_border", test_roundtrip_active_border)
    run_test("golden_snapshot", test_roundtrip_golden_snapshot)

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed, {len(results)} total")
    print(f"Artifacts: {_get_run_dir()}")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
