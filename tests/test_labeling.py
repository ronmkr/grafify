"""Tests for Phase 8: Labeling improvements, slugs, categories, and synonym mapping."""
from __future__ import annotations

from pathlib import Path

from graphify.build import build_from_json
from graphify.extract import extract_markdown
from graphify.labeling import apply_labeling_improvements, derive_category, load_aliases_config, make_slug


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_make_slug():
    assert make_slug("K8s:Deployment:prod/api-server") == "k8s-deployment-prod-api-server"
    assert make_slug("AWS:DynamoDB::Table:MainTable") == "aws-dynamodb-table-maintable"
    assert make_slug("Note:Architecture Guide & Design") == "note-architecture-guide-design"
    assert make_slug("user_id_field_123") == "user-id-field-123"
    assert make_slug("") == "unnamed"


def test_derive_category():
    assert derive_category("src/api/routes.py") == "api"
    assert derive_category("docs/architecture/overview.md") == "documentation"
    assert derive_category("charts/mychart/templates/deploy.yaml") == "helm"
    assert derive_category("k8s/prod/deployment.yaml") == "kubernetes"
    assert derive_category("tests/test_foo.py") == "testing"
    assert derive_category("main.tf") == "infrastructure"
    assert derive_category("README.md") == "documentation"


def test_load_aliases_config(tmp_path):
    aliases_content = """\
synonyms:
  authentication:
    - auth
    - authn
  database:
    - db
    - datastore
"""
    _write(tmp_path, "aliases.yaml", aliases_content)
    mapping = load_aliases_config(tmp_path)
    assert mapping.get("auth") == "authentication"
    assert mapping.get("authn") == "authentication"
    assert mapping.get("db") == "database"
    assert mapping.get("datastore") == "database"


def test_frontmatter_authoritative_metadata(tmp_path):
    md_content = """\
---
title: System Overview
type: architecture_guide
category: core_docs
aliases:
  - sys-overview
  - Architecture Overview
tags:
  - architecture
  - backend
---

# Introduction
This is the system overview. See [[deployment#setup]].
"""
    doc_path = _write(tmp_path, "overview.md", md_content)
    res = extract_markdown(doc_path)
    assert res.get("error") is None

    page_node = next(n for n in res["nodes"] if n.get("node_kind") == "page")
    assert page_node.get("title") == "System Overview"
    assert page_node.get("doc_type") == "architecture_guide"
    assert page_node.get("category") == "core_docs"
    assert "sys-overview" in page_node.get("aliases", [])

    # Tags
    tag_nodes = [n for n in res["nodes"] if n.get("node_kind") == "tag"]
    tag_labels = [n.get("label") for n in tag_nodes]
    assert "Tag:#architecture" in tag_labels
    assert "Tag:#backend" in tag_labels

    # Typed edge: tagged_as
    edges = res["edges"]
    assert any(e.get("relation") == "tagged_as" for e in edges)

    # Build and verify labeling pipeline attaches slugs and categories
    G = build_from_json(res, directed=False)
    for _, data in G.nodes(data=True):
        assert "slug" in data
        assert len(data["slug"]) > 0
        assert "category" in data
