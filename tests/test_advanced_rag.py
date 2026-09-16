"""Tests for Advanced Monorepo GraphRAG & Pruning.

Tests:
1. Dynamic Ego-Graph Boundary Pruning (RepoGraph ICLR 2025).
2. Fast Approximate Centrality for Large Monorepos (Fix for GitHub Issue #341).
3. Git Diff-Scoped Ego-Network Retrieval (diff_context, MCP tool, CLI).
4. Iterative Feedback Querying (refine_query, MCP tool, CLI).
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import networkx as nx
import pytest

from graph_fy.analyze import _cross_community_surprises, suggest_questions
from graph_fy.mcp import get_diff_context, refine_context
from graph_fy.retrieval import build_index, diff_context, query, refine_query


def test_boundary_pruning_filters_peripheral_noise(tmp_path: Path):
    """Verify boundary pruning removes low-weight edges during graph expansion."""
    db_path = tmp_path / "index.db"
    G = nx.Graph()

    # Seed node
    G.add_node("auth_service", label="auth_service", source_file="auth.py", source_location="L10")
    # Strong neighbor (hop 1)
    G.add_node("token_verifier", label="token_verifier", source_file="auth.py", source_location="L30")
    G.add_edge("auth_service", "token_verifier", relation="calls", weight=1.0)

    # Weak peripheral neighbor (hop 2 from seed) with weight < 0.2
    G.add_node("noise_logger", label="noise_logger", source_file="noise.py", source_location="L5")
    G.add_edge("token_verifier", "noise_logger", relation="uses", weight=0.05)

    build_index(G, db_path)

    # With boundary_pruning=True: noise_logger should be pruned
    res_pruned = query("auth_service", graph=G, db_path=db_path, limit=10, hops=2, boundary_pruning=True)
    assert isinstance(res_pruned, list)
    pruned_ids = [r["node_id"] for r in res_pruned]
    assert "auth_service" in pruned_ids
    assert "noise_logger" not in pruned_ids

    # With boundary_pruning=False: noise_logger should be retained
    res_unpruned = query("auth_service", graph=G, db_path=db_path, limit=10, hops=2, boundary_pruning=False)
    assert isinstance(res_unpruned, list)
    unpruned_ids = [r["node_id"] for r in res_unpruned]
    assert "noise_logger" in unpruned_ids


def test_fast_approximate_centrality():
    """Verify sampled betweenness centrality executes rapidly on graphs > 1000 nodes."""
    # Graph with 1200 nodes
    G = nx.erdos_renyi_graph(1200, 0.005, seed=42)
    for n in G.nodes():
        G.nodes[n]["label"] = f"node_{n}"
        G.nodes[n]["source_file"] = f"src/mod_{n % 10}.py"

    # 1. suggest_questions should succeed quickly using sampled betweenness
    questions = suggest_questions(G, communities={}, community_labels={}, top_n=5)
    assert isinstance(questions, list)

    # 2. _cross_community_surprises on > 500 node graph should sample instead of returning empty
    surprises = _cross_community_surprises(G, communities={}, top_n=5)
    assert isinstance(surprises, list)
    assert len(surprises) > 0


def test_git_diff_scoped_retrieval(tmp_path: Path):
    """Verify diff_context correctly maps git diff hunks to graph nodes and callers."""
    # Initialize a dummy git repository
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo_dir, check=True)

    src_file = repo_dir / "service.py"
    src_file.write_text("def authenticate():\n    return True\n", encoding="utf-8")
    subprocess.run(["git", "add", "service.py"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, check=True, capture_output=True)

    # Make a modification at line 2
    src_file.write_text("def authenticate():\n    # modified line\n    return False\n", encoding="utf-8")

    # Build graph
    G = nx.Graph()
    G.add_node("authenticate", label="authenticate", source_file="service.py", source_location="L1")
    G.add_node("login_handler", label="login_handler", source_file="handler.py", source_location="L10")
    G.add_node("test_auth", label="test_auth", source_file="test_auth.py", source_location="L5")

    G.add_edge("login_handler", "authenticate", relation="calls", _src="login_handler", _tgt="authenticate")
    G.add_edge("test_auth", "authenticate", relation="tests", _src="test_auth", _tgt="authenticate")

    # Run diff_context
    ctx = diff_context(graph=G, base_ref="HEAD", root_dir=repo_dir, token_budget=1000)
    assert "service.py" in ctx["modified_files"]
    assert "authenticate" in ctx["changed_nodes"]
    assert "login_handler" in ctx["callers"]
    assert "test_auth" in ctx["affected_tests"]
    assert "Diff-Scoped Ego Context" in ctx["prompt_context"]

    # Test MCP wrapper
    mcp_res = get_diff_context(base_ref="HEAD", root_dir=str(repo_dir), graph=G)
    assert "authenticate" in mcp_res["changed_nodes"]


def test_iterative_feedback_querying(tmp_path: Path):
    """Verify refine_query extracts missing identifiers from draft code and returns skeletons."""
    db_path = tmp_path / "index.db"
    repo_file = tmp_path / "security.py"
    repo_file.write_text(
        "class TokenManager:\n    def generate_token(self) -> str:\n        return 'xyz'\n\n"
        "def verify_token(token: str) -> bool:\n    return len(token) > 0\n",
        encoding="utf-8",
    )

    G = nx.Graph()
    G.add_node("TokenManager", label="TokenManager", source_file=str(repo_file), source_location="L1")
    G.add_node("verify_token", label="verify_token", source_file=str(repo_file), source_location="L5")
    build_index(G, db_path)

    # Incomplete code draft written by an agent
    code_draft = """
def handle_request(req):
    mgr = TokenManager()
    tok = mgr.generate_token()
    valid = verify_token(tok)
    return valid
"""

    res = refine_query(code_draft, graph=G, db_path=db_path, token_budget=1500)
    assert "TokenManager" in res["extracted_identifiers"]
    assert "verify_token" in res["extracted_identifiers"]
    assert "handle_request" not in res["extracted_identifiers"]  # defined in draft!

    resolved_labels = [r.get("label") for r in res["resolved_dependencies"]]
    assert any("TokenManager" in str(lbl) for lbl in resolved_labels)

    assert "TokenManager" in res["prompt_context"]

    # Test MCP wrapper
    mcp_res = refine_context(code_draft, root_dir=str(tmp_path), graph=G)
    assert "extracted_identifiers" in mcp_res


def test_cli_diff_and_refine():
    """Verify graph_fy diff and graph_fy refine CLI commands execute without error."""
    # Test diff
    diff_res = subprocess.run(
        [sys.executable, "-m", "graph_fy", "diff", "HEAD", "--budget", "500", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert diff_res.returncode == 0
    data = json.loads(diff_res.stdout)
    assert "modified_files" in data
    assert "changed_nodes" in data

    # Test refine
    draft = "def my_func(): return compute_pagerank(G)"
    refine_res = subprocess.run(
        [sys.executable, "-m", "graph_fy", "refine", "--code", draft, "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert refine_res.returncode == 0
    r_data = json.loads(refine_res.stdout)
    assert "extracted_identifiers" in r_data


def test_compact_docstrings():
    """Verify compact_docstrings truncates verbose multi-line docstrings to 1-line summaries."""
    from graph_fy.skeleton import compact_signature, get_parser_for_path, skeletonize_code

    code = '''
def calculate_score(user_id: int, weight: float = 1.0) -> float:
    """Calculate the comprehensive activity score for a user.

    Parameters:
        user_id: Unique user identifier.
        weight: Multiplier applied to score.

    Returns:
        Computed floating point score.
    """
    total = user_id * weight
    return total
'''
    parser, lang_name = get_parser_for_path(".py")
    assert parser is not None and lang_name is not None

    full_skel = skeletonize_code(code.encode("utf-8"), parser, lang_name, compact_docstrings=False)
    assert "Parameters:" in full_skel

    compact_skel = skeletonize_code(code.encode("utf-8"), parser, lang_name, compact_docstrings=True)
    assert "Calculate the comprehensive activity score for a user." in compact_skel
    assert "Parameters:" not in compact_skel
    assert "Returns:" not in compact_skel
    assert len(compact_skel) < len(full_skel)

