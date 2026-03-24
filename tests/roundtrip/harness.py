"""Round-trip TUI testing harness.

Core engine: capture compositor VT100 output → reconstruct via fresh pyte → compare.
Also includes formatters and artifact output.

LIMITATION: This harness verifies the compositor pipeline's logical correctness
by round-tripping through pyte. It CANNOT catch differences between pyte's
interpretation and real terminal emulators (Windows Terminal, xterm.js, etc.).
Final visual verification requires manual testing or screenshot comparison.
"""

from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pyte
from pyte.screens import Char

from terminalist.core.pane import Pane, Rect
from terminalist.frontend.compositor import Compositor
from terminalist.frontend.screen_sync import EMPTY_CHAR, extract_grid
from terminalist.frontend.split_tree import SplitNode, all_panes
from terminalist.pyte_patch import apply as patch_pyte

# ═══════════════════════════════════════════
#  Data types
# ═══════════════════════════════════════════


@dataclass
class CellMismatch:
    x: int
    y: int
    field: str  # "data", "fg", "bg", "bold", etc.
    original: object
    reconstructed: object


@dataclass
class RoundTripResult:
    passed: bool
    width: int
    height: int
    total_cells: int
    mismatches: list[CellMismatch] = field(default_factory=list)
    skipped_stubs: int = 0
    original_frame: list[list[Char]] | None = None
    reconstructed_frame: list[list[Char]] | None = None
    vt100_output: str = ""

    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        lines = [
            f"{status}: {self.width}x{self.height} ({self.total_cells} cells)",
            f"  mismatches: {len(self.mismatches)}, stubs skipped: {self.skipped_stubs}",
        ]
        for m in self.mismatches[:10]:
            lines.append(
                f"  ({m.x},{m.y}) {m.field}: {m.original!r} → {m.reconstructed!r}"
            )
        if len(self.mismatches) > 10:
            lines.append(f"  ... and {len(self.mismatches) - 10} more")
        return "\n".join(lines)


# ═══════════════════════════════════════════
#  Core: reconstruct + compare + verify
# ═══════════════════════════════════════════

_COMPARE_FIELDS = ("data", "fg", "bg", "bold", "italics",
                   "underscore", "strikethrough", "reverse", "blink")


def reconstruct_frame(vt100_output: str, w: int, h: int) -> list[list[Char]]:
    """Feed VT100 output into a fresh pyte Screen and extract the grid.

    pyte_patch must have been applied before calling this.
    """
    screen = pyte.Screen(w, h)
    stream = pyte.Stream(screen)
    stream.feed(vt100_output)
    lock = threading.Lock()
    return extract_grid(screen, lock)


def compare_frames(
    original: list[list[Char]],
    reconstructed: list[list[Char]],
    w: int,
    h: int,
) -> RoundTripResult:
    """Cell-by-cell comparison of two frames.

    CJK stub cells (data=""): only checks that both sides are stubs.
    Stub attributes (fg/bg/bold...) are NOT compared — pyte's stub
    attribute values are implementation-dependent and never rendered.
    """
    mismatches: list[CellMismatch] = []
    skipped_stubs = 0

    for y in range(h):
        for x in range(w):
            orig = original[y][x]
            recon = reconstructed[y][x]

            # CJK stub cell
            if orig.data == "":
                skipped_stubs += 1
                if recon.data != "":
                    mismatches.append(
                        CellMismatch(x, y, "data", "", recon.data)
                    )
                continue

            # Normal cell: compare all fields
            for f in _COMPARE_FIELDS:
                ov = getattr(orig, f)
                rv = getattr(recon, f)
                if ov != rv:
                    mismatches.append(CellMismatch(x, y, f, ov, rv))

    total = w * h
    return RoundTripResult(
        passed=len(mismatches) == 0,
        width=w,
        height=h,
        total_cells=total,
        mismatches=mismatches,
        skipped_stubs=skipped_stubs,
        original_frame=original,
        reconstructed_frame=reconstructed,
    )


def roundtrip_verify(
    compositor: Compositor,
    root: SplitNode,
    rect: Rect,
    output_list: list[str],
    focused_pane: Pane | None = None,
) -> RoundTripResult:
    """One-stop round-trip verification.

    1. Render via compositor (captures VT100 to output_list)
    2. Reconstruct from captured VT100
    3. Compare original frame vs reconstructed
    """
    # Render — compositor appends VT100 to output_list via patched flush
    compositor.render(root, rect, focused_pane)
    vt100 = output_list[-1] if output_list else ""

    # Get the composed frame (what compositor thinks it rendered)
    original = compositor.compose(root, rect, focused_pane)

    # Reconstruct from VT100
    reconstructed = reconstruct_frame(vt100, rect.w, rect.h)

    result = compare_frames(original, reconstructed, rect.w, rect.h)
    result.vt100_output = vt100
    return result


# ═══════════════════════════════════════════
#  Formatters
# ═══════════════════════════════════════════


def format_frame_simple(frame: list[list[Char]], w: int, h: int) -> str:
    """Render frame as plain text. CJK stubs shown as nothing (skip)."""
    lines: list[str] = []
    for y in range(min(h, len(frame))):
        row_chars: list[str] = []
        for x in range(min(w, len(frame[y]))):
            ch = frame[y][x]
            if ch.data == "":
                continue  # CJK stub
            row_chars.append(ch.data)
        lines.append("".join(row_chars))
    return "\n".join(lines)


def format_frame_detail(frame: list[list[Char]], w: int, h: int) -> str:
    """Render frame with attribute annotations."""
    lines: list[str] = []
    for y in range(min(h, len(frame))):
        data_parts: list[str] = []
        attr_parts: list[str] = []
        for x in range(min(w, len(frame[y]))):
            ch = frame[y][x]
            data_parts.append(ch.data if ch.data else "_")
            # Compact attr: first letter of fg + bold marker
            fg_code = ch.fg[0] if ch.fg != "default" else "."
            bold_mark = "B" if ch.bold else "."
            attr_parts.append(f"{bold_mark}{fg_code}")
        lines.append(f"Row {y:3d}: {''.join(data_parts)}")
        lines.append(f"  Attr: {' '.join(attr_parts)}")
    return "\n".join(lines)


def format_mismatches(mismatches: list[CellMismatch]) -> str:
    """Format mismatches as a readable table."""
    if not mismatches:
        return "No mismatches."
    lines = [f"{'(x,y)':>10s}  {'field':>15s}  {'original':>20s}  {'reconstructed':>20s}"]
    lines.append("-" * 70)
    for m in mismatches:
        lines.append(
            f"({m.x:3d},{m.y:3d})  {m.field:>15s}  {str(m.original):>20s}  {str(m.reconstructed):>20s}"
        )
    return "\n".join(lines)


# ═══════════════════════════════════════════
#  Artifacts
# ═══════════════════════════════════════════

_OUTPUT_BASE = Path(__file__).parent.parent / "output"


def create_run_dir(base: Path | None = None) -> Path:
    """Create a timestamped output directory for this test run."""
    base = base or _OUTPUT_BASE
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = base / stamp
    # Handle sub-second collision
    suffix = 0
    while run_dir.exists():
        suffix += 1
        run_dir = base / f"{stamp}_{suffix}"
    run_dir.mkdir(parents=True)
    return run_dir


def cleanup_old_runs(base: Path | None = None, keep: int = 5) -> None:
    """Remove old test run directories, keeping the most recent `keep`."""
    base = base or _OUTPUT_BASE
    if not base.exists():
        return
    dirs = sorted(
        [d for d in base.iterdir() if d.is_dir() and d.name != "__pycache__"],
        key=lambda d: d.name,
    )
    for old_dir in dirs[:-keep] if len(dirs) > keep else []:
        shutil.rmtree(old_dir, ignore_errors=True)


def write_artifacts(
    run_dir: Path,
    scenario_name: str,
    panes: list[Pane],
    result: RoundTripResult,
) -> Path:
    """Write all artifacts for one test scenario.

    Returns the scenario directory path.
    """
    scenario_dir = run_dir / scenario_name
    scenario_dir.mkdir(parents=True, exist_ok=True)

    # Per-pane grids
    for pane in panes:
        grid = extract_grid(pane.session._screen, pane.session._lock)
        text = format_frame_simple(grid, pane.rect.w, pane.rect.h)
        (scenario_dir / f"pane_{pane.pane_id}_grid.txt").write_text(
            f"=== Pane: {pane.pane_id} ({pane.rect.w}x{pane.rect.h}) ===\n{text}\n",
            encoding="utf-8",
        )

    # Composed frame
    if result.original_frame:
        text = format_frame_detail(result.original_frame, result.width, result.height)
        (scenario_dir / "frame_composed.txt").write_text(
            f"=== Composed Frame ({result.width}x{result.height}) ===\n{text}\n",
            encoding="utf-8",
        )

    # Roundtrip frame
    if result.reconstructed_frame:
        text = format_frame_detail(result.reconstructed_frame, result.width, result.height)
        (scenario_dir / "frame_roundtrip.txt").write_text(
            f"=== Roundtrip Frame ({result.width}x{result.height}) ===\n{text}\n",
            encoding="utf-8",
        )

    # Raw VT100
    if result.vt100_output:
        # Write both raw and escaped versions
        (scenario_dir / "vt100_raw.bin").write_bytes(
            result.vt100_output.encode("utf-8")
        )
        escaped = result.vt100_output.replace("\x1b", "ESC")
        (scenario_dir / "vt100_raw.txt").write_text(escaped, encoding="utf-8")

    # Diff report
    status = "PASS" if result.passed else "FAIL"
    report_lines = [
        "Round-Trip Verification Report",
        "=" * 40,
        f"Dimensions: {result.width} x {result.height}",
        f"Total cells: {result.total_cells}",
        f"CJK stubs skipped: {result.skipped_stubs}",
        f"Mismatches: {len(result.mismatches)}",
        f"Result: {status}",
    ]
    if result.mismatches:
        report_lines.append("")
        report_lines.append("Mismatch Details:")
        report_lines.append(format_mismatches(result.mismatches))

    (scenario_dir / "diff_report.txt").write_text(
        "\n".join(report_lines) + "\n", encoding="utf-8"
    )

    return scenario_dir
