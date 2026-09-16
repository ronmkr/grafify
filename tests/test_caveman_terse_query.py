"""Tests for --terse and --caveman token conservation output."""
from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
from networkx.readwrite import json_graph

import graphify.__main__ as mainmod
from graphify.retrieval import (
    build_index,
    format_compact_path,
    format_query_results,
    query,
    retrieve,
)


def _setup_test_graph(tmp_path: Path):
    G = nx.DiGraph()
    G.add_node(
        "auth.py::login",
        label="login",
        file_type="code",
        node_kind="function",
        source_file="auth.py",
        source_location="L12",
        text="def login(username, password): authenticates user session",
    )
    G.add_node(
        "server.py::app",
        label="app",
        file_type="code",
        node_kind="function",
        source_file="server.py",
        source_location="L45",
        text="def app(): routes incoming requests and calls login",
    )
    G.add_node(
        "db.py::UserTable",
        label="UserTable",
        file_type="code",
        node_kind="class",
        source_file="db.py",
        source_location="L3",
        text="class UserTable: stores user credentials and roles",
    )
    G.add_node(
        "crypto.py::verify_hash",
        label="verify_hash",
        file_type="code",
        node_kind="function",
        source_file="crypto.py",
        source_location="L20",
        text="def verify_hash(pwd, hash): verifies password hash",
    )
    G.add_node(
        "audit.py::log_event",
        label="log_event",
        file_type="code",
        node_kind="function",
        source_file="audit.py",
        source_location="L55",
        text="def log_event(action): logs authentication event",
    )
    G.add_node(
        "session.py::create_session",
        label="create_session",
        file_type="code",
        node_kind="function",
        source_file="session.py",
        source_location="L8",
        text="def create_session(user_id): creates user session",
    )
    G.add_edge("server.py::app", "auth.py::login", relation="calls", confidence="EXTRACTED", _src="server.py::app", _tgt="auth.py::login")
    G.add_edge("auth.py::login", "db.py::UserTable", relation="queries", confidence="EXTRACTED", _src="auth.py::login", _tgt="db.py::UserTable")
    G.add_edge("auth.py::login", "crypto.py::verify_hash", relation="calls", confidence="EXTRACTED", _src="auth.py::login", _tgt="crypto.py::verify_hash")
    G.add_edge("auth.py::login", "audit.py::log_event", relation="calls", confidence="EXTRACTED", _src="auth.py::login", _tgt="audit.py::log_event")
    G.add_edge("auth.py::login", "session.py::create_session", relation="calls", confidence="EXTRACTED", _src="auth.py::login", _tgt="session.py::create_session")

    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(json_graph.node_link_data(G, edges="links")), encoding="utf-8")
    db_path = tmp_path / "index.db"
    build_index(G, db_path)
    return G, graph_path, db_path


def test_format_compact_path():
    path = [
        {"from": "service_a", "relation": "calls", "to": "service_b"},
        {"from": "service_b", "relation": "imports", "to": "service_c"},
        {"from": "service_c", "relation": "uses", "to": "db"},
    ]
    formatted = format_compact_path(path)
    assert formatted == "[service_a] -(calls)-> [service_b] -(imports)-> [service_c] -(uses)-> [db]"

    # Empty path
    assert format_compact_path([]) == ""


def test_format_query_results_precision_and_conservation():
    raw_results = [
        {
            "node_id": "auth.py::login",
            "label": "login",
            "score": 9.5123,
            "text": "def login(username, password): authenticates user session and validates credentials.",
            "source_path": "auth.py",
            "source_location": "L12",
            "connected_via": [],
        },
        {
            "node_id": "db.py::UserTable",
            "label": "UserTable",
            "score": 4.2109,
            "text": "class UserTable: stores user credentials and roles in database.",
            "source_path": "db.py",
            "source_location": "L3",
            "connected_via": [
                {"from": "auth.py::login", "relation": "queries", "to": "db.py::UserTable"},
            ],
        },
    ]

    # Non-terse output should be standard JSON
    json_out = format_query_results(raw_results, terse=False, caveman=False)
    assert '"node_id": "auth.py::login"' in json_out
    parsed = json.loads(json_out)
    assert len(parsed) == 2

    # Terse / caveman output
    for flag in ({"terse": True}, {"caveman": True}):
        terse_out = format_query_results(raw_results, **flag)

        # 100% technical fidelity checks
        assert "[auth.py::login]" in terse_out
        assert "login" in terse_out
        assert "auth.py:L12" in terse_out
        assert "[db.py::UserTable]" in terse_out
        assert "UserTable" in terse_out
        assert "db.py:L3" in terse_out

        # Edge relationship and compact path
        assert "queries -> db.py::UserTable" in terse_out
        assert "[auth.py::login] -(queries)-> [db.py::UserTable]" in terse_out

        # Strip unnecessary conversational text and decorative headers
        assert "Traversal:" not in terse_out
        assert "Score:" not in terse_out
        assert "Preview:" not in terse_out
        assert '"node_id":' not in terse_out

        # Token conservation: character count should be cut by >= 65%
        token_reduction = (len(json_out) - len(terse_out)) / len(json_out)
        assert token_reduction >= 0.65, f"Expected >= 65% reduction, got {token_reduction:.2%}"


def test_retrieve_terse_and_caveman(tmp_path: Path):
    G, graph_path, db_path = _setup_test_graph(tmp_path)

    # Standard retrieve returns list
    standard_res = retrieve("login", graph=G, db_path=db_path, limit=5, hops=1)
    assert isinstance(standard_res, list)
    assert len(standard_res) > 0

    # Terse retrieve returns compact string
    terse_res = retrieve("login", graph=G, db_path=db_path, limit=5, hops=1, terse=True)
    assert isinstance(terse_res, str)
    assert "[auth.py::login]" in terse_res
    assert "auth.py:L12" in terse_res

    # Caveman retrieve returns compact string
    caveman_res = retrieve("login", graph=G, db_path=db_path, limit=5, hops=1, caveman=True)
    assert isinstance(caveman_res, str)
    assert terse_res == caveman_res


def test_query_function_terse_and_caveman(tmp_path: Path):
    G, graph_path, db_path = _setup_test_graph(tmp_path)

    # query with terse=True
    terse_out = query("login", graph=G, db_path=db_path, limit=5, hops=1, terse=True)
    assert isinstance(terse_out, str)
    assert "[auth.py::login]" in terse_out
    assert "auth.py:L12" in terse_out

    # query with caveman=True
    caveman_out = query("login", graph=G, db_path=db_path, limit=5, hops=1, caveman=True)
    assert isinstance(caveman_out, str)
    assert "[auth.py::login]" in caveman_out
    assert "auth.py:L12" in caveman_out


def test_cli_query_terse_and_caveman(monkeypatch, tmp_path: Path, capsys):
    _, graph_path, _ = _setup_test_graph(tmp_path)
    monkeypatch.setattr(mainmod, "_check_skill_version", lambda _: None)

    # 1. Non-terse CLI query returns JSON
    monkeypatch.setattr(
        mainmod.sys,
        "argv",
        ["graphify", "query", "login", "--graph", str(graph_path)],
    )
    mainmod.main()
    normal_out = capsys.readouterr().out
    assert '"node_id": "auth.py::login"' in normal_out

    # 2. --terse CLI query
    monkeypatch.setattr(
        mainmod.sys,
        "argv",
        ["graphify", "query", "login", "--graph", str(graph_path), "--terse"],
    )
    mainmod.main()
    terse_out = capsys.readouterr().out
    assert "[auth.py::login]" in terse_out
    assert "login" in terse_out
    assert "auth.py:L12" in terse_out
    assert '"node_id":' not in terse_out

    # Verify token reduction >= 65%
    reduction = (len(normal_out) - len(terse_out)) / len(normal_out)
    assert reduction >= 0.65, f"Expected >= 65% reduction, got {reduction:.2%}"

    # 3. --caveman CLI query
    monkeypatch.setattr(
        mainmod.sys,
        "argv",
        ["graphify", "query", "login", "--graph", str(graph_path), "--caveman"],
    )
    mainmod.main()
    caveman_out = capsys.readouterr().out
    assert "[auth.py::login]" in caveman_out
    assert "login" in caveman_out
    assert "auth.py:L12" in caveman_out
    assert caveman_out.strip() == terse_out.strip()


def test_cli_explain_terse_and_caveman(monkeypatch, tmp_path: Path, capsys):
    _, graph_path, _ = _setup_test_graph(tmp_path)
    monkeypatch.setattr(mainmod, "_check_skill_version", lambda _: None)

    # 1. Non-terse explain has verbose headers
    monkeypatch.setattr(
        mainmod.sys,
        "argv",
        ["graphify", "explain", "login", "--graph", str(graph_path)],
    )
    mainmod.main()
    normal_out = capsys.readouterr().out
    assert "Node: login" in normal_out
    assert "ID:        auth.py::login" in normal_out
    assert "Connections" in normal_out

    # 2. --terse explain strips conversational headers and outputs dense fragments
    monkeypatch.setattr(
        mainmod.sys,
        "argv",
        ["graphify", "explain", "login", "--graph", str(graph_path), "--terse"],
    )
    mainmod.main()
    terse_out = capsys.readouterr().out
    assert "Node:" not in terse_out
    assert "ID:        " not in terse_out
    assert "Connections" not in terse_out

    # 100% technical fidelity preserved
    assert "[auth.py::login]" in terse_out
    assert "login" in terse_out
    assert "auth.py:L12" in terse_out
    assert "queries -> db.py::UserTable" in terse_out
    assert "calls <- server.py::app" in terse_out

    # Token reduction vs verbose normal output
    reduction = (len(normal_out) - len(terse_out)) / len(normal_out)
    assert reduction >= 0.35, f"Expected >= 35% reduction, got {reduction:.2%}"

    # 3. --caveman explain
    monkeypatch.setattr(
        mainmod.sys,
        "argv",
        ["graphify", "explain", "login", "--graph", str(graph_path), "--caveman"],
    )
    mainmod.main()
    caveman_out = capsys.readouterr().out
    assert caveman_out.strip() == terse_out.strip()


def test_cli_query_legacy_text_terse(monkeypatch, tmp_path: Path, capsys):
    _, graph_path, _ = _setup_test_graph(tmp_path)
    monkeypatch.setattr(mainmod, "_check_skill_version", lambda _: None)

    # Legacy text mode triggered by "who calls "
    monkeypatch.setattr(
        mainmod.sys,
        "argv",
        ["graphify", "query", "who calls login", "--graph", str(graph_path)],
    )
    mainmod.main()
    normal_out = capsys.readouterr().out
    assert "Traversal:" in normal_out

    monkeypatch.setattr(
        mainmod.sys,
        "argv",
        ["graphify", "query", "who calls login", "--graph", str(graph_path), "--terse"],
    )
    mainmod.main()
    terse_out = capsys.readouterr().out
    assert "Traversal:" not in terse_out
    assert "[login]" in terse_out or "[app]" in terse_out
