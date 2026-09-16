"""Tests for the tools/skillgen generator for Claude Code and Copilot.

skillgen renders graph_fy's committed skill artifacts from human-edited
fragments. These tests lock in the anti-drift guards (--check),
render idempotency, and the lean-core invariant: the
core runs a default extraction with zero reference reads, on-demand content
lives only in the references, and no reference duplicates core content.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.skillgen import gen


def test_check_passes():
    """The committed artifacts and the expected/ snapshot match a fresh render."""
    platforms = gen.load_platforms()
    artifacts = gen.render_all(platforms)
    problems = gen.check(artifacts)
    assert problems == [], "\n".join(problems)


def test_render_is_idempotent():
    """Rendering twice yields byte-identical output (no timestamps/versions)."""
    platforms = gen.load_platforms()
    first = gen.render_all(platforms)
    second = gen.render_all(platforms)
    assert [(a.path, a.content) for a in first] == [(a.path, a.content) for a in second]


def test_render_output_is_lf_only():
    """Generated artifacts use LF newlines and end in exactly one newline."""
    platforms = gen.load_platforms()
    for art in gen.render_all(platforms):
        assert "\r" not in art.content, art.path
        assert art.content.endswith("\n"), art.path
        assert not art.content.endswith("\n\n"), art.path


def test_no_version_or_timestamp_in_output():
    """No generated artifact carries the package version string."""
    from graph_fy.__main__ import __version__

    platforms = gen.load_platforms()
    for art in gen.render_all(platforms):
        assert __version__ not in art.content, f"{art.path} leaked a version string"


def _claude_artifacts():
    platforms = gen.load_platforms()
    arts = gen.render_all(platforms, only="claude")
    core = next(a for a in arts if a.path == "graph_fy/skill.md")
    refs = {a.path.rsplit("/", 1)[-1]: a.content for a in arts if a.path != "graph_fy/skill.md"}
    return core.content, refs


def test_lean_core_has_no_reference_only_content():
    """The core must not inline the execution detail of an on-demand reference."""
    core, _ = _claude_artifacts()
    assert '"file_type":"code|document|paper|image|rationale|concept"' not in core
    assert "from graph_fy.build import build_merge" not in core
    assert "graph_fy cluster-only ." not in core
    assert "Constrained query expansion" not in core
    assert "save-result --question" not in core
    assert "graph_fy export wiki" not in core
    assert "graph_fy export neo4j" not in core
    assert "from graph_fy.ingest import ingest" not in core
    assert "graph_fy hook install" not in core
    assert "python3 -m graph_fy.watch" not in core


def test_lean_core_runs_default_pipeline_with_zero_references():
    """The default code-corpus run must be fully described inside the core."""
    core, _ = _claude_artifacts()
    for needed in (
        "### Step 1 - Ensure graph_fy is installed",
        "### Step 2 - Detect files",
        "### Step 3 - Extract entities and relationships",
        "#### Part A - Structural extraction for code files",
        "#### Part C - Merge AST + semantic into final extraction",
        "### Step 4 - Build graph, cluster, analyze, generate outputs",
        "### Step 5 - Label communities",
        "### Step 6 - Generate Obsidian vault (opt-in) + HTML",
        "### Step 9 - Save manifest, update cost tracker, clean up, and report",
        "## Honesty Rules",
        "graph_fy export html",
    ):
        assert needed in core, f"lean core is missing default-pipeline content: {needed!r}"


def test_extraction_states_no_api_key_required_for_every_host():
    """Every skill body that describes Step 3 extraction must state no API key is required."""
    platforms = gen.load_platforms()
    arts = gen.render_all(platforms)
    bodies = [a for a in arts if "### Step 3 - Extract entities and relationships" in a.content]
    assert bodies, "no rendered skill body contains the Step 3 extraction section"
    for a in bodies:
        assert "graph_fy needs no API key" in a.content, a.path
        assert "Never ask the user for one, and never block on one." in a.content, a.path


def test_references_contain_no_core_pipeline_content():
    """No reference fragment may duplicate the core build pipeline."""
    _, refs = _claude_artifacts()
    core_only_markers = (
        "from graph_fy.cluster import cluster, score_all",
        "### Step 4 - Build graph, cluster, analyze, generate outputs",
        "### Step 5 - Label communities",
        "## Honesty Rules",
    )
    for name, body in refs.items():
        for marker in core_only_markers:
            assert marker not in body, f"reference {name} leaked core content: {marker!r}"


def test_reference_pointers_in_core_resolve_to_real_fragments():
    """Every references/<name>.md the core points at is actually rendered."""
    import re

    core, refs = _claude_artifacts()
    pointed = set(re.findall(r"references/([\w-]+)\.md", core))
    rendered = {name[: -len(".md")] for name in refs}
    missing = pointed - rendered
    assert not missing, f"core points at references that were not rendered: {missing}"


def test_query_heading_is_homed_in_core_stub_only():
    """The query section heading is the lean-core stub; query.md re-homes the rest."""
    core, refs = _claude_artifacts()
    core_headings = set(gen.headings(core))
    query_headings = set(gen.headings(refs["query.md"]))
    assert "## For /graph_fy query" in core_headings or "## For /graph_fy query" in core_headings
    assert "## For /graph_fy query" not in query_headings and "## For /graph_fy query" not in query_headings
    assert "## For /graph_fy path" in query_headings or "## For /graph_fy path" in query_headings
    assert "## For /graph_fy explain" in query_headings or "## For /graph_fy explain" in query_headings


def test_references_render_for_claude():
    """claude renders exactly the seven on-demand fragments."""
    _, refs = _claude_artifacts()
    assert sorted(refs) == [
        "add-watch.md",
        "exports.md",
        "extraction-spec.md",
        "github-and-merge.md",
        "hooks.md",
        "query.md",
        "update.md",
    ]


def test_headings_helper_ignores_code_fence_comments():
    """The fence-aware heading scanner must skip '#' lines inside code fences."""
    md = (
        "# Real Heading\n"
        "\n"
        "```bash\n"
        "# not a heading, a shell comment\n"
        "echo hi\n"
        "```\n"
        "\n"
        "## Another Real One\n"
    )
    assert gen.headings(md) == ["# Real Heading", "## Another Real One"]


def test_enum_is_full_six_value_superset_in_extraction_spec():
    """The file_type enum is the full six-value superset."""
    _, refs = _claude_artifacts()
    spec = refs["extraction-spec.md"]
    assert "`code`, `document`, `paper`, `image`, `rationale`, `concept`" in spec
    assert '"file_type":"code|document|paper|image|rationale|concept"' in spec


def test_copilot_platform_rendered():
    """Copilot skill renders correctly with its references."""
    platforms = gen.load_platforms()
    assert "copilot" in platforms
    arts = gen.render_all(platforms, only="copilot")
    assert any(a.path == "graph_fy/skill-copilot.md" for a in arts)
    copilot_refs = {a.path.rsplit("/", 1)[-1] for a in arts if a.path != "graph_fy/skill-copilot.md"}
    assert "query.md" in copilot_refs
    assert "update.md" in copilot_refs


def test_always_on_renders_claude_md():
    """Always-on rendering produces only claude-md.md."""
    platforms = gen.load_platforms()
    arts = gen.render_all(platforms)
    always_on = [a for a in arts if "always_on" in a.path]
    assert len(always_on) == 1
    assert always_on[0].path == "graph_fy/always_on/claude-md.md"
