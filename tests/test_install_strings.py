"""Regression tests for install-time instruction strings.

These strings live in graph_fy/__main__.py and are written into project-local
files (CLAUDE.md) or into in-process hook payloads. Earlier versions of graph_fy told every
assistant to "ALWAYS read graph_fy_out/GRAPH_REPORT.md before answering" —
which silently increased per-question token usage in Claude Code sessions
(issue #580). This file locks in the query-first policy so a future revert
or partial change is caught by CI.
"""
from __future__ import annotations
import json

from graph_fy.__main__ import (
    _SEARCH_NUDGE,
    _READ_NUDGE,
    _skill_registration,
    _CLAUDE_MD_SECTION,
)


_INSTALL_TEXTS: dict[str, str] = {
    "_SEARCH_NUDGE": _SEARCH_NUDGE,
    "_READ_NUDGE": _READ_NUDGE,
    "_CLAUDE_MD_SECTION": _CLAUDE_MD_SECTION,
}


def test_every_install_surface_recommends_graph_fy_query():
    """All install surfaces must point the assistant at `graph_fy query`
    as the first action for codebase questions. This is the load-bearing
    fix for issue #580."""
    missing: list[str] = []
    for name, text in _INSTALL_TEXTS.items():
        if "graph_fy query" not in text and "graph_fy query" not in text:
            missing.append(name)
    assert not missing, (
        f"these install surfaces no longer mention `graph_fy query`: {missing}."
    )


def test_no_install_surface_demands_reading_the_full_report_first():
    """Any phrasing that puts reading the report BEFORE
    other actions for codebase questions is a regression of issue #580."""
    import re
    banned = [
        re.compile(r"read[^.\n]{0,80}GRAPH_REPORT\.md[^.\n]{0,80}before", re.IGNORECASE),
        re.compile(r"first\s+tool\s+call[^.\n]{0,80}GRAPH_REPORT", re.IGNORECASE),
        re.compile(r"always\s+read[^.\n]{0,80}GRAPH_REPORT", re.IGNORECASE),
    ]
    hits: list[tuple[str, str]] = []
    for name, text in _INSTALL_TEXTS.items():
        for pattern in banned:
            m = pattern.search(text)
            if m:
                hits.append((name, m.group(0)))
    assert not hits, (
        f"banned report-first phrasing reappeared: {hits}. "
        f"This regresses issue #580."
    )


def test_report_is_still_referenced_as_fallback():
    md_section_texts = {
        "_CLAUDE_MD_SECTION": _CLAUDE_MD_SECTION,
    }
    missing: list[str] = []
    for name, text in md_section_texts.items():
        if "GRAPH_REPORT.md" not in text:
            missing.append(name)
    assert not missing, (
        f"these install sections no longer mention GRAPH_REPORT.md at all: {missing}."
    )


def test_skill_registration_uses_host_generic_instruction():
    reg = _skill_registration()
    assert 'skill: "graph_fy"' not in reg
    assert "Skill tool" not in reg
    assert "use the installed graph_fy skill or instructions" in reg
