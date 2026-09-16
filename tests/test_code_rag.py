"""Unit and integration tests for Code Repository GraphRAG.

Tests:
1. Code-Aware Lexical Sub-Token Tokenizer for SQLite FTS5 (split_subtokens, expand_subtokens, FTS5 matching).
2. Adaptive Multi-Tier Elision Ladder (compact_signature, Tier 1/2/3 greedy budget packing).
3. Bidirectional Execution Slicing (immediate caller/callee bundling for callable nodes).
4. Prompt-Cache Friendly Context Ordering (deterministic path/line ordering, stable prompt prefix).
"""
from pathlib import Path
import networkx as nx
import pytest

from graph_fy.retrieval import (
    build_index,
    format_rag_prompt,
    query,
    split_subtokens,
    expand_subtokens,
    _find_callers_and_callees,
    _prepare_node_document,
)
from graph_fy.skeleton import (
    compact_signature,
    get_parser_for_path,
)


def test_split_subtokens():
    """Verify sub-token splitting handles camelCase, PascalCase, snake_case, and acronyms."""
    # camelCase
    res = split_subtokens("getUserById")
    assert res == ["getUserById", "get", "user", "by", "id"]
    assert expand_subtokens("getUserById") == "getUserById get user by id"

    # PascalCase
    res = split_subtokens("AuthManager")
    assert res == ["AuthManager", "auth", "manager"]
    assert expand_subtokens("AuthManager") == "AuthManager auth manager"

    # snake_case
    res = split_subtokens("parse_query")
    assert res == ["parse_query", "parse", "query"]
    assert expand_subtokens("parse_query") == "parse_query parse query"

    # Acronyms & mixed
    res = split_subtokens("AuthMgr")
    assert res == ["AuthMgr", "auth", "mgr"]

    res_empty = split_subtokens("")
    assert res_empty == []


def test_prepare_node_document_subtokens():
    """Verify _prepare_node_document enriches title and body with sub-tokens."""
    data = {
        "label": "getUserById",
        "name": "getUserById",
        "source_file": "user_service.py",
        "source_location": "L42",
        "text": "Fetch user by unique identifier",
    }
    fts_row, meta_row = _prepare_node_document("node_user", data)
    nid, title, headings, tags, body, src = fts_row
    assert "get" in title
    assert "user" in title
    assert "by" in title
    assert "id" in title
    assert src == "user_service.py"


def test_fts5_indexing_and_matching_with_subtokens(tmp_path: Path):
    """Verify FTS5 indexes code sub-tokens and matches developer acronyms/casing variants."""
    db_file = tmp_path / "test_fts5.db"

    src_file = tmp_path / "auth_service.py"
    src_file.write_text(
        "class AuthManager:\n"
        "    def getUserById(self, user_id: str):\n"
        "        pass\n",
        encoding="utf-8",
    )

    G = nx.DiGraph()
    G.add_node(
        "auth_mgr",
        label="AuthManager",
        name="AuthManager",
        source_file=str(src_file),
        source_location="L1",
        file_type="code",
        text="Authentication and token management service",
    )
    G.add_node(
        "user_fetch",
        label="getUserById",
        name="getUserById",
        source_file=str(src_file),
        source_location="L2",
        file_type="code",
        text="Retrieve user record by ID",
    )

    build_index(G, db_file)

    # 1. Query 'getUser' should match 'getUserById' via sub-tokens
    res1 = query("getUser", graph=G, db_path=db_file, limit=5)
    assert isinstance(res1, list)
    assert len(res1) >= 1
    assert any(it["node_id"] == "user_fetch" for it in res1)

    # 2. Query 'AuthMgr' should match 'AuthManager' via sub-token 'auth'
    res2 = query("AuthMgr", graph=G, db_path=db_file, limit=5)
    assert isinstance(res2, list)
    assert len(res2) >= 1
    assert any(it["node_id"] == "auth_mgr" for it in res2)

    # 3. Query 'manager' should match 'AuthManager'
    res3 = query("manager", graph=G, db_path=db_file, limit=5)
    assert isinstance(res3, list)
    assert len(res3) >= 1
    assert any(it["node_id"] == "auth_mgr" for it in res3)


def test_compact_signature():
    """Verify compact_signature produces single-line signatures without bodies or docstrings."""
    # Python function
    code_fn = (
        "def login(user: str, pwd: str) -> bool:\n"
        '    """Authenticate user with credentials."""\n'
        "    if not user:\n"
        "        return False\n"
        "    return True\n"
    )
    sig_fn = compact_signature(code_fn, lang="python")
    assert sig_fn == "def login(user: str, pwd: str) -> bool: ..."
    assert "Authenticate user" not in sig_fn
    assert "return True" not in sig_fn

    # Python class
    code_cls = (
        "class Auth:\n"
        '    """Authentication namespace."""\n'
        "    def __init__(self):\n"
        "        pass\n"
    )
    sig_cls = compact_signature(code_cls, lang="python")
    assert sig_cls == "class Auth: ..."
    assert "Authentication namespace" not in sig_cls

    # Multiline python signature
    code_multi = (
        "def process_data(\n"
        "    items: list[str],\n"
        "    timeout: float = 5.0,\n"
        ") -> dict[str, int]:\n"
        "    return {}\n"
    )
    sig_multi = compact_signature(code_multi, lang="python")
    assert sig_multi == "def process_data(items: list[str], timeout: float = 5.0) -> dict[str, int]: ..."

    # Empty string
    assert compact_signature("") == ""


def test_bidirectional_execution_slicing(tmp_path: Path):
    """Verify immediate callers and callees are bundled for callable nodes."""
    src_file = tmp_path / "app.py"
    src_file.write_text(
        "def caller_a(): target_fn()\n"
        "def target_fn(): callee_b()\n"
        "def callee_b(): pass\n",
        encoding="utf-8",
    )

    G = nx.DiGraph()
    G.add_node("caller_a", label="caller_a()", source_file=str(src_file), source_location="L1", node_kind="function")
    G.add_node("target_fn", label="target_fn()", source_file=str(src_file), source_location="L2", node_kind="function")
    G.add_node("callee_b", label="callee_b()", source_file=str(src_file), source_location="L3", node_kind="function")

    # Inbound call: caller_a calls target_fn
    G.add_edge("caller_a", "target_fn", relation="calls")
    # Outbound call: target_fn calls callee_b
    G.add_edge("target_fn", "callee_b", relation="calls")

    callers, callees = _find_callers_and_callees(G, "target_fn")
    assert "caller_a()" in callers
    assert "callee_b()" in callees

    # Test query with skeleton=True attaches callers and callees
    db_file = tmp_path / "slice_index.db"
    build_index(G, db_file)

    res = query("target_fn", graph=G, db_path=db_file, skeleton=True, limit=5)
    assert isinstance(res, list)
    target_item = next(it for it in res if it["node_id"] == "target_fn")
    assert "callers" in target_item
    assert "callees" in target_item
    assert "caller_a()" in target_item["callers"]
    assert "callee_b()" in target_item["callees"]


def test_adaptive_multi_tier_elision_ladder():
    """Verify format_rag_prompt multi-tier ladder degrades gracefully under budget constraints."""
    results = [
        {
            "node_id": "seed_main",
            "label": "main_handler()",
            "source_path": "server.py",
            "source_location": "L10",
            "score": 10.0,
            "skeleton": (
                "def main_handler(req: Request) -> Response:\n"
                '    """Main entrypoint handling incoming requests."""\n'
                "    ..."
            ),
            "callers": ["entrypoint()"],
            "callees": ["auth_check()", "db_query()"],
            "related_types": [
                {
                    "node_id": "req_type",
                    "relation": "references",
                    "skeleton": "class Request:\n    headers: dict[str, str]\n    body: bytes",
                }
            ],
        },
        {
            "node_id": "auth_fn",
            "label": "auth_check()",
            "source_path": "auth.py",
            "source_location": "L50",
            "score": 6.0,
            "skeleton": (
                "def auth_check(token: str) -> bool:\n"
                '    """Verify JWT authentication token."""\n'
                "    ..."
            ),
            "callers": ["main_handler()"],
            "callees": [],
        },
        {
            "node_id": "db_fn",
            "label": "db_query()",
            "source_path": "db.py",
            "source_location": "L100",
            "score": 2.0,
            "skeleton": "def db_query(sql: str) -> list[dict]:\n    ...",
        },
    ]

    # Generous budget (2000 tokens): Top seed gets Tier 1 (full skeleton + docstrings), medium get compact
    prompt_large = format_rag_prompt(results, "how does authentication work", token_budget=2000)
    assert "### Codebase Context for: how does authentication work" in prompt_large
    assert "main_handler()" in prompt_large
    assert "Main entrypoint handling incoming requests" in prompt_large  # Tier 1 full skeleton
    assert "- Callers: entrypoint()" in prompt_large
    assert "- Callees: auth_check(), db_query()" in prompt_large
    assert "auth.py:L50" in prompt_large

    # Moderate budget (100 tokens):forces Tier 2 / Tier 3 compaction
    prompt_moderate = format_rag_prompt(results, "auth query", token_budget=120)
    assert "### Codebase Context for: auth query" in prompt_moderate
    # Check that compaction or Tier 3 citations are used
    assert ("server.py:L10" in prompt_moderate) or ("auth.py:L50" in prompt_moderate)

    # Tight budget (40 tokens): Exceeding budget halts context generation gracefully
    prompt_tight = format_rag_prompt(results, "tight query", token_budget=40)
    assert (
        "// [remaining context omitted to stay within token budget]" in prompt_tight
        or "::" in prompt_tight
    )


def test_prompt_cache_friendly_context_ordering():
    """Verify deterministic candidate ordering by (source_path, line_number) and stable prefix."""
    item1 = {
        "node_id": "z_item",
        "label": "z_fn()",
        "source_path": "z_module.py",
        "source_location": "L5",
        "score": 9.5,
        "skeleton": "def z_fn(): ...",
    }
    item2 = {
        "node_id": "a_item_line20",
        "label": "a_fn_2()",
        "source_path": "a_module.py",
        "source_location": "L20",
        "score": 8.0,
        "skeleton": "def a_fn_2(): ...",
    }
    item3 = {
        "node_id": "a_item_line5",
        "label": "a_fn_1()",
        "source_path": "a_module.py",
        "source_location": "L5",
        "score": 7.0,
        "skeleton": "def a_fn_1(): ...",
    }

    # Pass in random orders
    order1 = [item1, item2, item3]
    order2 = [item3, item1, item2]

    prompt1 = format_rag_prompt(order1, "first question", token_budget=1000)
    prompt2 = format_rag_prompt(order2, "second question", token_budget=1000)

    # Both must start with the static architecture prefix
    assert prompt1.startswith("### Codebase Architecture & Context")
    assert prompt2.startswith("### Codebase Architecture & Context")

    # In both prompts, a_module.py:L5 must appear before a_module.py:L20, and both before z_module.py:L5
    idx1_a5 = prompt1.index("a_module.py:L5")
    idx1_a20 = prompt1.index("a_module.py:L20")
    idx1_z5 = prompt1.index("z_module.py:L5")
    assert idx1_a5 < idx1_a20 < idx1_z5

    idx2_a5 = prompt2.index("a_module.py:L5")
    idx2_a20 = prompt2.index("a_module.py:L20")
    idx2_z5 = prompt2.index("z_module.py:L5")
    assert idx2_a5 < idx2_a20 < idx2_z5

    # Prefix before dynamic suffix is identical byte-for-byte between prompt1 and prompt2 (when passed same input)
    prefix1 = prompt1.split("### Codebase Context for:")[0]
    prompt1_same = format_rag_prompt(order1, "different question", token_budget=1000)
    prefix1_same = prompt1_same.split("### Codebase Context for:")[0]
    assert prefix1 == prefix1_same, "Prompt prefix must be identical across turns for prompt caching"
