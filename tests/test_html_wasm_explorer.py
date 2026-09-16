"""test_html_wasm_explorer.py — Tests for zero-server in-browser WASM/SQL explorer,

predictive blast radius calculator, and neighborhood slicing.
"""

from __future__ import annotations

import json
from pathlib import Path
import networkx as nx
import pytest

from graphify.exporters.html import to_html


def _build_test_graph() -> tuple[nx.Graph, dict[int, list[str]], dict[int, str]]:
    """Build a rich test graph with functions, classes, APIs, tests, and IaC resources."""
    G = nx.Graph()

    nodes = [
        ("auth_service", {"label": "auth_service", "file_type": "py", "source_file": "src/auth.py"}),
        ("jwt_helper", {"label": "jwt_helper", "file_type": "py", "source_file": "src/jwt.py"}),
        ("user_db", {"label": "user_db", "file_type": "py", "source_file": "src/db.py"}),
        ("api_login", {"label": "POST /api/login", "file_type": "api", "source_file": "src/routes.py"}),
        ("api_logout", {"label": "POST /api/logout", "file_type": "api", "source_file": "src/routes.py"}),
        ("test_auth", {"label": "test_auth_service", "file_type": "py", "source_file": "tests/test_auth.py"}),
        ("k8s_auth", {"label": "k8s_auth_deployment", "file_type": "k8s", "source_file": "deploy/auth.yaml"}),
    ]
    for nid, attrs in nodes:
        G.add_node(nid, **attrs)

    edges = [
        ("auth_service", "jwt_helper", {"relation": "calls", "confidence": "EXTRACTED", "_src": "auth_service", "_tgt": "jwt_helper"}),
        ("auth_service", "user_db", {"relation": "calls", "confidence": "EXTRACTED", "_src": "auth_service", "_tgt": "user_db"}),
        ("api_login", "auth_service", {"relation": "calls", "confidence": "EXTRACTED", "_src": "api_login", "_tgt": "auth_service"}),
        ("api_logout", "auth_service", {"relation": "calls", "confidence": "EXTRACTED", "_src": "api_logout", "_tgt": "auth_service"}),
        ("test_auth", "auth_service", {"relation": "calls", "confidence": "EXTRACTED", "_src": "test_auth", "_tgt": "auth_service"}),
        ("k8s_auth", "auth_service", {"relation": "references", "confidence": "EXTRACTED", "_src": "k8s_auth", "_tgt": "auth_service"}),
    ]
    for u, v, attrs in edges:
        G.add_edge(u, v, **attrs)

    communities = {
        0: ["auth_service", "jwt_helper", "user_db"],
        1: ["api_login", "api_logout"],
        2: ["test_auth", "k8s_auth"],
    }
    labels = {0: "Core Auth", 1: "HTTP Endpoints", 2: "Tests & Deploy"}
    return G, communities, labels


def test_html_wasm_explorer_embedded_schema_and_query_panel(tmp_path: Path):
    """Verify HTML contains embedded SQL/WASM explorer panel, schema card, and query engine."""
    G, communities, labels = _build_test_graph()
    out = tmp_path / "graph.html"
    assert to_html(G, communities, str(out), community_labels=labels) is True

    content = out.read_text(encoding="utf-8")

    # Verify query panel UI elements
    assert 'id="tab-sql"' in content
    assert 'id="sql-input"' in content
    assert 'id="btn-run-sql"' in content
    assert 'id="btn-clear-sql"' in content
    assert 'id="query-results"' in content
    assert 'id="sql-presets"' in content
    assert 'id="toggle-schema-btn"' in content
    assert 'id="db-schema-card"' in content

    # Verify embedded table schema definitions
    assert "TABLE nodes (" in content
    assert "TABLE edges (" in content
    assert "id TEXT PRIMARY KEY" in content
    assert "label TEXT" in content
    assert "file_type TEXT" in content
    assert "community INTEGER" in content
    assert "DB_SCHEMA" in content

    # Verify ad-hoc filter form
    assert 'id="filter-label"' in content
    assert 'id="filter-type"' in content
    assert 'id="filter-comm-select"' in content
    assert 'id="btn-apply-filter"' in content

    # Verify SQL engine JS functions
    assert "function executeSqlQuery(sql)" in content
    assert "function evaluateWhere(row, clause)" in content
    assert "function renderQueryResults(res)" in content


def test_html_wasm_explorer_blast_radius_calculator(tmp_path: Path):
    """Verify HTML contains embedded blast radius calculator, impact traversal, and risk tiers."""
    G, communities, labels = _build_test_graph()
    out = tmp_path / "graph.html"
    to_html(G, communities, str(out), community_labels=labels)
    content = out.read_text(encoding="utf-8")

    # Blast radius panel UI elements
    assert 'id="tab-blast"' in content
    assert 'id="blast-target-select"' in content
    assert 'id="btn-calc-blast"' in content
    assert 'id="btn-clear-blast"' in content
    assert 'id="blast-results-panel"' in content
    assert 'id="blast-risk-badge"' in content
    assert 'id="blast-score-bar"' in content
    assert 'id="blast-apis-list"' in content
    assert 'id="blast-tests-list"' in content
    assert 'id="blast-closure-list"' in content

    # Traversal and classification logic
    assert "function computeBlastRadius(" in content
    assert "function runBlastRadius(" in content
    assert "function clearBlastRadius(" in content
    assert "IMPACT_RELATIONS" in content
    assert "isTestNode(" in content
    assert "isApiNode(" in content
    assert "isIacNode(" in content

    # Risk tiers
    assert "'CRITICAL'" in content
    assert "'HIGH'" in content
    assert "'MEDIUM'" in content
    assert "'LOW'" in content
    assert "risk-CRITICAL" in content
    assert "risk-LOW" in content


def test_html_wasm_explorer_neighborhood_and_community_slicing(tmp_path: Path):
    """Verify HTML contains neighborhood hop slicing and community isolation controls."""
    G, communities, labels = _build_test_graph()
    out = tmp_path / "graph.html"
    to_html(G, communities, str(out), community_labels=labels)
    content = out.read_text(encoding="utf-8")

    # Slicing UI elements
    assert 'id="tab-slice"' in content
    assert "slice-hop-btn" in content
    assert 'data-hops="1"' in content
    assert 'data-hops="2"' in content
    assert 'data-hops="3"' in content
    assert 'id="slice-comm-select"' in content
    assert 'id="btn-isolate-comm"' in content
    assert 'id="btn-reset-slice"' in content

    # Slicing JS functions
    assert "function sliceNeighborhood(nodeId, hops)" in content
    assert "function isolateCommunity(cid)" in content
    assert "function resetSlicing()" in content


def test_html_wasm_explorer_full_graph_clean_export(tmp_path: Path):
    """Verify clean HTML5 export with valid JSON data and tabs."""
    G, communities, labels = _build_test_graph()
    out = tmp_path / "graph.html"
    written = to_html(G, communities, str(out), community_labels=labels)
    assert written is True
    assert out.is_file()

    content = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert '<html lang="en">' in content
    assert 'vis-network' in content
    assert 'id="graph"' in content
    assert 'id="sidebar"' in content
    assert "RAW_NODES" in content
    assert "RAW_EDGES" in content

    # Extract and parse embedded JSON to ensure well-formed data
    nodes_line = [line for line in content.splitlines() if line.startswith("const RAW_NODES = ")][0]
    raw_nodes_str = nodes_line.replace("const RAW_NODES = ", "").rstrip(";")
    nodes_data = json.loads(raw_nodes_str)
    assert len(nodes_data) == 7

    edges_line = [line for line in content.splitlines() if line.startswith("const RAW_EDGES = ")][0]
    raw_edges_str = edges_line.replace("const RAW_EDGES = ", "").rstrip(";")
    edges_data = json.loads(raw_edges_str)
    assert len(edges_data) == 6


def test_html_wasm_explorer_aggregated_community_meta_graph(tmp_path: Path):
    """Verify aggregated community meta-graph exports cleanly with query explorer & blast radius."""
    # Build graph with 25 nodes across 3 communities to trigger node_limit aggregation
    G = nx.Graph()
    communities: dict[int, list[str]] = {0: [], 1: [], 2: []}
    labels = {0: "CommZero", 1: "CommOne", 2: "CommTwo"}

    for i in range(25):
        nid = f"node_{i}"
        cid = i % 3
        communities[cid].append(nid)
        G.add_node(nid, label=f"Symbol {i}", file_type="py")

    # Connect nodes across communities
    for i in range(24):
        G.add_edge(f"node_{i}", f"node_{i+1}", relation="calls", confidence="EXTRACTED")

    out = tmp_path / "graph_meta.html"
    written = to_html(G, communities, str(out), community_labels=labels, node_limit=10)
    assert written is True
    assert out.is_file()

    content = out.read_text(encoding="utf-8")
    # Verify embedded query engine and blast radius are preserved in aggregated meta view
    assert 'id="tab-sql"' in content
    assert 'id="tab-blast"' in content
    assert 'id="tab-slice"' in content
    assert "DB_SCHEMA" in content
    assert "executeSqlQuery" in content
    assert "computeBlastRadius" in content
    assert "sliceNeighborhood" in content

    # Verify RAW_NODES contains the 3 community meta-nodes
    nodes_line = [line for line in content.splitlines() if line.startswith("const RAW_NODES = ")][0]
    raw_nodes_str = nodes_line.replace("const RAW_NODES = ", "").rstrip(";")
    meta_nodes = json.loads(raw_nodes_str)
    assert len(meta_nodes) == 3


def test_html_wasm_explorer_self_contained_offline(tmp_path: Path):
    """Verify generated HTML is 100% self-contained and does not make network calls to local backend."""
    G, communities, labels = _build_test_graph()
    out = tmp_path / "graph.html"
    to_html(G, communities, str(out), community_labels=labels)
    content = out.read_text(encoding="utf-8")

    # Must not contain server localhost, fetch APIs, or ws connections
    assert "localhost" not in content
    assert "http://127.0.0.1" not in content
    assert "fetch('/" not in content
    assert "WebSocket" not in content


def test_html_wasm_explorer_xss_sanitization(tmp_path: Path):
    """Verify node labels with quotes and special characters are safely escaped."""
    G = nx.Graph()
    G.add_node('xss"onclick="alert(1)', label='Attack <script> "quote"', file_type="py")
    G.add_node('normal', label='Normal Node', file_type="py")
    G.add_edge('xss"onclick="alert(1)', 'normal', relation='calls')

    communities = {0: ['xss"onclick="alert(1)', 'normal']}
    out = tmp_path / "graph_xss.html"
    to_html(G, communities, str(out))

    content = out.read_text(encoding="utf-8")
    # Ensure no raw unescaped script tag injected from label
    assert '<script> "quote"' not in content
