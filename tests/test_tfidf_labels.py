"""Unit tests for pure-Python deterministic TF-IDF per-node keyword labeling."""
from __future__ import annotations

import math
from typing import Any

from graph_fy.labeling import apply_labeling_improvements
from graph_fy.tfidf import (
    ENGLISH_STOPWORDS,
    PROGRAMMING_STOPWORDS,
    STOPWORDS,
    compute_idf,
    compute_node_keywords,
    compute_tf,
    extract_node_text,
    tokenize,
)


class TestTokenize:
    """Tests for text normalization, splitting, and stopword filtering."""

    def test_tokenize_basic(self):
        text = "The quick brown fox jumps over the lazy dog"
        tokens = tokenize(text)
        assert "quick" in tokens
        assert "brown" in tokens
        assert "fox" in tokens
        assert "jumps" in tokens
        assert "lazy" in tokens
        assert "dog" in tokens
        # Stopwords 'the' and 'over' should be excluded
        assert "the" not in tokens
        assert "over" not in tokens

    def test_tokenize_camel_and_pascal_case(self):
        text = "handleHTTPRequest parseJsonPayload ASTVisitor"
        tokens = tokenize(text)
        assert "handle" in tokens
        assert "http" in tokens
        assert "request" in tokens
        assert "parse" in tokens
        assert "json" in tokens
        assert "payload" in tokens
        assert "ast" in tokens
        assert "visitor" in tokens

    def test_tokenize_filters_programming_stopwords(self):
        text = "def authenticate_user(token: str) -> bool: return True"
        tokens = tokenize(text)
        assert "authenticate" in tokens
        assert "user" in tokens
        assert "token" in tokens
        # Programming keywords filtered
        assert "def" not in tokens
        assert "str" not in tokens
        assert "bool" not in tokens
        assert "return" not in tokens
        assert "true" not in tokens

    def test_tokenize_filters_digits_and_short_tokens(self):
        text = "a b 1 42 999 cluster1 oauth2"
        tokens = tokenize(text)
        # Single letters and pure digits excluded
        assert "a" not in tokens
        assert "b" not in tokens
        assert "1" not in tokens
        assert "42" not in tokens
        assert "999" not in tokens
        # Mixed alphanumeric retained
        assert "cluster1" in tokens
        assert "oauth2" in tokens

    def test_tokenize_custom_stopwords(self):
        text = "alpha beta gamma delta"
        tokens = tokenize(text, stopwords={"alpha", "gamma"})
        assert tokens == ["beta", "delta"]

    def test_tokenize_empty_and_whitespace(self):
        assert tokenize("") == []
        assert tokenize("   \n\t  ") == []


class TestTFandIDF:
    """Tests for term frequency and inverse document frequency calculations."""

    def test_compute_tf_raw(self):
        tokens = ["apple", "banana", "apple", "cherry", "apple", "banana"]
        tf = compute_tf(tokens, normalize=False)
        assert tf["apple"] == 3.0
        assert tf["banana"] == 2.0
        assert tf["cherry"] == 1.0

    def test_compute_tf_normalized(self):
        tokens = ["apple", "banana", "apple", "banana"]
        tf = compute_tf(tokens, normalize=True)
        assert math.isclose(tf["apple"], 0.5)
        assert math.isclose(tf["banana"], 0.5)

    def test_compute_tf_empty(self):
        assert compute_tf([]) == {}

    def test_compute_idf_smooth_formula(self):
        # Formula: log((N + 1) / (df + 1)) + 1
        n_docs = 10
        df = 2
        expected = math.log((10 + 1) / (2 + 1)) + 1.0
        actual = compute_idf(n_docs, df, smooth=True)
        assert math.isclose(actual, expected)

    def test_compute_idf_all_documents(self):
        # When term appears in all documents, df == n_docs
        n_docs = 5
        df = 5
        # (5 + 1) / (5 + 1) == 1, log(1) == 0, 0 + 1 == 1.0
        assert math.isclose(compute_idf(n_docs, df, smooth=True), 1.0)

    def test_compute_idf_zero_docs(self):
        assert compute_idf(0, 0, smooth=True) == 1.0
        assert compute_idf(0, 0, smooth=False) == 0.0

    def test_compute_idf_unsmoothed(self):
        n_docs = 10
        df = 1
        expected = math.log(10 / (1 + 1))
        assert math.isclose(compute_idf(n_docs, df, smooth=False), expected)


class TestExtractNodeText:
    """Tests for extracting textual content from diverse node formats."""

    def test_extract_node_text_priority_fields(self):
        node = {
            "id": "node-1",
            "label": "AuthenticationManager",
            "title": "Auth Manager Component",
            "docstring": "Handles JWT authentication and token validation.",
            "headings": ["Overview", "Configuration"],
            "comments": ["TODO: Add OAuth2 support"],
            "tags": ["#security", "#auth"],
        }
        text = extract_node_text(node)
        assert "AuthenticationManager" in text
        assert "Auth Manager Component" in text
        assert "Handles JWT authentication" in text
        assert "Overview" in text
        assert "Configuration" in text
        assert "Add OAuth2 support" in text
        assert "#security" in text
        # Structural keys skipped
        assert "node-1" not in text

    def test_extract_node_text_nested_metadata(self):
        node = {
            "id": "node-2",
            "metadata": {
                "author": "SecurityTeam",
                "details": {
                    "encryption": "AES-256-GCM",
                    "ciphers": ["ECDHE", "RSA"],
                },
            },
        }
        text = extract_node_text(node)
        assert "SecurityTeam" in text
        assert "AES-256-GCM" in text
        assert "ECDHE" in text
        assert "RSA" in text

    def test_extract_node_text_empty(self):
        assert extract_node_text({}) == ""
        assert extract_node_text(None) == ""  # type: ignore


class TestComputeNodeKeywords:
    """Tests for end-to-end TF-IDF keyword extraction on node collections."""

    def test_compute_node_keywords_discriminates_specific_terms(self):
        nodes = [
            {
                "id": "auth-service",
                "label": "Authentication Service",
                "docstring": "Provides user login, JWT authentication, and token verification.",
            },
            {
                "id": "db-pool",
                "label": "Database Connection Pool",
                "docstring": "Manages PostgreSQL connection pool, transactions, and SQL queries.",
            },
            {
                "id": "billing-service",
                "label": "Billing Service",
                "docstring": "Processes credit card payments, Stripe invoices, and subscription billing.",
            },
        ]

        compute_node_keywords(nodes, top_k=3)

        # Each node receives 'keywords' and 'top_terms'
        for node in nodes:
            assert "keywords" in node
            assert "top_terms" in node
            assert node["keywords"] == node["top_terms"]
            assert len(node["keywords"]) <= 3

        auth_kws = nodes[0]["keywords"]
        db_kws = nodes[1]["keywords"]
        billing_kws = nodes[2]["keywords"]

        # Node-specific terms should lead the keywords
        assert any(k in auth_kws for k in ("jwt", "login", "authentication", "verification"))
        assert any(k in db_kws for k in ("postgresql", "sql", "pool", "queries", "transactions"))
        assert any(k in billing_kws for k in ("stripe", "invoices", "billing", "payments", "subscription"))

    def test_compute_node_keywords_top_k_bounds(self):
        nodes = [
            {"id": "n1", "label": "Alpha Beta Gamma Delta Epsilon Zeta Eta"},
        ]
        # top_k = 2
        compute_node_keywords(nodes, top_k=2)
        assert len(nodes[0]["keywords"]) == 2

        # top_k = 0
        compute_node_keywords(nodes, top_k=0)
        assert nodes[0]["keywords"] == []

        # top_k negative
        compute_node_keywords(nodes, top_k=-1)
        assert nodes[0]["keywords"] == []

        # top_k larger than terms count
        compute_node_keywords(nodes, top_k=100)
        assert len(nodes[0]["keywords"]) > 0
        assert len(nodes[0]["keywords"]) <= 7

    def test_compute_node_keywords_empty_nodes(self):
        assert compute_node_keywords([]) == []
        empty_nodes = [{"id": "empty1"}, {"id": "empty2", "label": ""}]
        res = compute_node_keywords(empty_nodes)
        assert res[0]["keywords"] == []
        assert res[0]["top_terms"] == []
        assert res[1]["keywords"] == []
        assert res[1]["top_terms"] == []

    def test_compute_node_keywords_deterministic_tie_breaking(self):
        # Two terms with identical TF and IDF must sort alphabetically
        nodes = [
            {"id": "n1", "label": "zebra yak"},
            {"id": "n2", "label": "fox wolf"},
        ]
        res1 = compute_node_keywords([dict(n) for n in nodes], top_k=2)
        res2 = compute_node_keywords([dict(n) for n in nodes], top_k=2)
        assert res1[0]["keywords"] == res2[0]["keywords"]
        # 'yak' comes before 'zebra' alphabetically
        assert res1[0]["keywords"] == ["yak", "zebra"]

    def test_single_node_corpus(self):
        nodes = [
            {"id": "solo", "label": "compiler parser optimizer compiler compiler"},
        ]
        compute_node_keywords(nodes, top_k=2)
        # 'compiler' has TF=3, 'optimizer' and 'parser' have TF=1
        assert nodes[0]["keywords"][0] == "compiler"
        assert len(nodes[0]["keywords"]) == 2

    def test_integration_with_apply_labeling_improvements(self):
        nodes = [
            {"id": "n1", "label": "Kafka Consumer Stream"},
            {"id": "n2", "label": "Redis Cache Cluster"},
        ]
        edges: list[dict[str, Any]] = []
        n_out, e_out = apply_labeling_improvements(nodes, edges, compute_keywords=True, top_k=3)
        assert n_out[0]["slug"] == "kafka-consumer-stream"
        assert "keywords" in n_out[0]
        assert "top_terms" in n_out[0]
        assert len(n_out[0]["keywords"]) > 0

    def test_tfidf_exports(self):
        # Ensure graph_fy.tfidf exports all key components
        assert callable(compute_node_keywords)
        assert callable(compute_tf)
        assert callable(compute_idf)
        assert callable(tokenize)
        assert callable(extract_node_text)
        assert isinstance(ENGLISH_STOPWORDS, frozenset)
        assert isinstance(PROGRAMMING_STOPWORDS, frozenset)
        assert isinstance(STOPWORDS, frozenset)
