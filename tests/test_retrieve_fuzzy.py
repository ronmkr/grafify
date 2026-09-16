"""Comprehensive unit tests for typo-tolerant fuzzy search in retrieval (Phase 11)."""
from pathlib import Path
import networkx as nx
import pytest

from graphify.retrieve import (
    _clean_fts_query,
    build_index,
    explain,
    fuzzy_match_term,
    fuzzy_match_tokens,
    get_indexed_terms,
    max_allowed_distance,
    query,
)


def test_max_allowed_distance():
    """Verify Levenshtein distance constraints based on word length."""
    # Length >= 5: distance <= 2
    assert max_allowed_distance("kubernetes") == 2
    assert max_allowed_distance("kbernetes") == 2
    assert max_allowed_distance("authentication") == 2
    assert max_allowed_distance("docker") == 2
    assert max_allowed_distance("nodes") == 2

    # Length 4: distance <= 1
    assert max_allowed_distance("node") == 1
    assert max_allowed_distance("helm") == 1
    assert max_allowed_distance("pod1") == 1

    # Length < 4: distance 0 (exact match only)
    assert max_allowed_distance("k8s") == 0
    assert max_allowed_distance("api") == 0
    assert max_allowed_distance("db") == 0
    assert max_allowed_distance("a") == 0
    assert max_allowed_distance("") == 0


def test_fuzzy_match_term_unit():
    """Verify fuzzy_match_term matching against vocabulary."""
    vocab = {"kubernetes", "authentication", "docker", "postgres", "node", "helm", "k8s", "api"}

    # Word length >= 5: allows distance <= 2
    assert fuzzy_match_term("kbernetes", vocab) == ["kubernetes"]
    assert fuzzy_match_term("authntication", vocab) == ["authentication"]
    assert fuzzy_match_term("dockr", vocab) == ["docker"]
    assert fuzzy_match_term("postgre", vocab) == ["postgres"]

    # Word length >= 5: distance > 2 rejected
    assert fuzzy_match_term("kxxxernetes", vocab) == []  # distance 3

    # Word length 4: allows distance <= 1
    assert fuzzy_match_term("nodz", vocab) == ["node"]
    assert fuzzy_match_term("helx", vocab) == ["helm"]  # distance 1, 4-letter word
    assert fuzzy_match_term("nozz", vocab) == []  # distance 2 rejected for 4-letter word

    # Word length < 4: exact match only
    assert fuzzy_match_term("k8s", vocab) == ["k8s"]
    assert fuzzy_match_term("k8", vocab) == []  # distance 1, rejected
    assert fuzzy_match_term("api", vocab) == ["api"]
    assert fuzzy_match_term("apx", vocab) == []

    # Whitespace and empty strings
    assert fuzzy_match_term("", vocab) == []
    assert fuzzy_match_term("   ", vocab) == []


def test_fuzzy_match_tokens():
    """Verify batch token matching and expansion."""
    vocab = {"kubernetes", "cluster", "deployment", "service"}

    # Mixed known and misspelled tokens
    tokens = ["deploy", "kbernetes", "clustr"]
    expansions = fuzzy_match_tokens(tokens, vocab)
    assert "kbernetes" in expansions
    assert expansions["kbernetes"] == ["kubernetes"]
    assert "clustr" in expansions
    assert expansions["clustr"] == ["cluster"]

    # Already known tokens should not be in expansions
    known_tokens = ["kubernetes", "cluster"]
    assert fuzzy_match_tokens(known_tokens, vocab) == {}


def test_clean_fts_query_with_fuzzy_expansions():
    """Verify query expansion in FTS5 MATCH expressions."""
    # Single typo
    expansions = {"kbernetes": ["kubernetes"]}
    q1 = _clean_fts_query("kbernetes", fuzzy_expansions=expansions)
    assert '"kbernetes"' in q1
    assert '"kubernetes"' in q1

    # Multi-term with proximity NEAR correction
    expansions_multi = {"kbernetes": ["kubernetes"], "clustr": ["cluster"]}
    q2 = _clean_fts_query("deploy kbernetes clustr", fuzzy_expansions=expansions_multi)
    assert '"deploy"' in q2
    assert '"kubernetes"' in q2
    assert '"cluster"' in q2
    assert "NEAR(deploy kubernetes cluster, 10)" in q2

    # Quoted phrase with typo
    q3 = _clean_fts_query('"kbernetes deployment"', fuzzy_expansions=expansions)
    assert '"kbernetes deployment"' in q3
    assert '"kubernetes deployment"' in q3


@pytest.fixture
def sample_graph() -> nx.Graph:
    """Create a sample knowledge graph with various resources and code symbols."""
    G = nx.Graph()

    # Node 1: Kubernetes Cluster Guide
    G.add_node(
        "k8s_guide",
        label="Kubernetes Architecture",
        file_type="document",
        node_kind="heading",
        source_file="docs/k8s.md",
        source_location="L1",
        text="Deploying containers to a production kubernetes cluster with horizontal pod autoscaling.",
    )

    # Node 2: Authentication Service
    G.add_node(
        "auth_service",
        label="AuthService",
        file_type="code",
        node_kind="class",
        source_file="services/auth.py",
        source_location="L15",
        text="Central authentication provider handling JWT validation, user login, and token verification.",
    )

    # Node 3: Docker Compose
    G.add_node(
        "docker_compose",
        label="Docker Container Setup",
        file_type="config",
        node_kind="docker",
        source_file="docker-compose.yml",
        source_location="L1",
        text="Docker compose specification defining local microservice containers and networking.",
    )

    # Node 4: Database Pool
    G.add_node(
        "db_pool",
        label="PostgreSQL Pool",
        file_type="code",
        node_kind="class",
        source_file="db/postgres.py",
        source_location="L8",
        text="PostgreSQL database connection pool and transactional session management.",
    )

    # Edges
    G.add_edge("k8s_guide", "auth_service", relation="deploys", weight=1.0)
    G.add_edge("auth_service", "db_pool", relation="queries", weight=1.0)
    G.add_edge("docker_compose", "auth_service", relation="runs", weight=1.0)

    return G


def test_get_indexed_terms(tmp_path: Path, sample_graph: nx.Graph):
    """Verify that build_index indexes vocabulary terms and symbol names into index.db."""
    db_path = tmp_path / "vocab_test.db"
    build_index(sample_graph, db_path)
    assert db_path.exists()

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    try:
        terms = get_indexed_terms(conn)
        # Check standard vocabulary
        assert "kubernetes" in terms
        assert "authentication" in terms
        assert "docker" in terms
        assert "postgresql" in terms
        assert "cluster" in terms

        # Check symbol names (CamelCase and sub-parts)
        assert "authservice" in terms
        assert "auth" in terms
        assert "service" in terms
    finally:
        conn.close()


def test_retrieval_fuzzy_misspellings(tmp_path: Path, sample_graph: nx.Graph):
    """Test retrieval typo-tolerance for key misspellings."""
    db_path = tmp_path / "retrieval_test.db"
    build_index(sample_graph, db_path)

    # 1. "kbernetes" -> should retrieve Kubernetes Architecture node
    res_k8s = query("kbernetes", graph=sample_graph, db_path=db_path, limit=5, hops=0)
    assert len(res_k8s) > 0
    assert res_k8s[0]["node_id"] == "k8s_guide"
    assert "kubernetes" in res_k8s[0]["text"].lower()

    # 2. "authntication" -> should retrieve AuthService node
    res_auth = query("authntication", graph=sample_graph, db_path=db_path, limit=5, hops=0)
    assert len(res_auth) > 0
    assert res_auth[0]["node_id"] == "auth_service"
    assert "authentication" in res_auth[0]["text"].lower()

    # 3. "dockr" -> should retrieve Docker container node
    res_docker = query("dockr", graph=sample_graph, db_path=db_path, limit=5, hops=0)
    assert len(res_docker) > 0
    assert res_docker[0]["node_id"] == "docker_compose"

    # 4. Multi-word query with typo: "kbernetes deploy"
    res_multi = query("kbernetes deploy", graph=sample_graph, db_path=db_path, limit=5, hops=0)
    assert len(res_multi) > 0
    assert res_multi[0]["node_id"] == "k8s_guide"


def test_retrieval_fuzzy_graph_expansion(tmp_path: Path, sample_graph: nx.Graph):
    """Verify that graph traversal (hops > 0) expands neighbors from fuzzy seed matches."""
    db_path = tmp_path / "expansion_test.db"
    build_index(sample_graph, db_path)

    # Querying "kbernetes" with 1 hop should retrieve k8s_guide AND connected auth_service
    results = query("kbernetes", graph=sample_graph, db_path=db_path, limit=5, hops=1)
    node_ids = [r["node_id"] for r in results]

    assert "k8s_guide" in node_ids
    assert "auth_service" in node_ids
    for r in results:
        if r["node_id"] == "auth_service":
            assert len(r["connected_via"]) == 1
            assert r["connected_via"][0]["from"] == "k8s_guide"


def test_retrieval_fuzzy_disabled(tmp_path: Path, sample_graph: nx.Graph):
    """Verify that setting fuzzy=False disables typo tolerance."""
    db_path = tmp_path / "nofuzzy_test.db"
    build_index(sample_graph, db_path)

    # With fuzzy=False, "kbernetes" should yield 0 results
    results = query("kbernetes", graph=sample_graph, db_path=db_path, limit=5, hops=0, fuzzy=False)
    assert results == []


def test_retrieval_wildly_incorrect_query(tmp_path: Path, sample_graph: nx.Graph):
    """Verify that a completely unmatched query returns an empty list without error."""
    db_path = tmp_path / "nomatch_test.db"
    build_index(sample_graph, db_path)

    results = query("xyzzy987qwerty123", graph=sample_graph, db_path=db_path, limit=5, hops=1)
    assert results == []


def test_explain_with_fuzzy(tmp_path: Path, sample_graph: nx.Graph):
    """Verify that explain() correctly supports fuzzy matching and populates hops."""
    db_path = tmp_path / "explain_test.db"
    build_index(sample_graph, db_path)

    results = explain("authntication", graph=sample_graph, db_path=db_path, limit=5, hops=1)
    assert len(results) > 0
    top = results[0]
    assert top["node_id"] == "auth_service"
    assert "hops" in top
    assert top["hops"] == 0
