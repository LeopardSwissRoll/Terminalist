"""Fake scrollback fixtures for TestCopy."""

from __future__ import annotations


def build_sample_lines(total: int = 220) -> list[str]:
    lines: list[str] = []
    for index in range(total):
        if index % 23 == 0:
            lines.append("")
        elif index % 19 == 0:
            lines.append(
                f"{index:03d} long-line lorem ipsum dolor sit amet, consectetur adipiscing elit, copy-mode playground"
            )
        elif index % 17 == 0:
            lines.append(f"{index:03d} mixed CJK line 한글 日本語 search-target needle")
        elif index % 13 == 0:
            lines.append(f"{index:03d} repeated needle needle marker")
        elif index % 11 == 0:
            lines.append(f"{index:03d} trailing spaces demo      ")
        else:
            lines.append(f"{index:03d} sample output line for copy mode")
    return lines

