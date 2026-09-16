"""Tests for hot in-memory graph patching and instant re-indexing daemon."""
from __future__ import annotations

import json
import sqlite3
import sys
import types
from pathlib import Path

import networkx as nx
import pytest

from graph_fy.build import build_from_json
from graph_fy.extract import extract
from graph_fy.watch import patch_graph_in_memory, watch, watch_hot


def test_patch_graph_in_memory_add_function(tmp_path: Path):
    """Test that adding a new function to an existing file updates the in-memory graph."""
    app_py = tmp_path / "app.py"
    app_py.write_text("def hello():\n    return 'hello'\n", encoding="utf-8")

    initial_ext = extract([app_py], root=tmp_path)
    G = build_from_json(initial_ext, root=tmp_path)

    initial_nodes = set(G.nodes())
    assert any("hello" in nid for nid in initial_nodes)

    # Edit app.py: add a new function world()
    app_py.write_text(
        "def hello():\n    return 'hello'\n\ndef world():\n    return 'world'\n",
        encoding="utf-8",
    )

    G, stats = patch_graph_in_memory(G, [app_py], root=tmp_path)

    new_nodes = set(G.nodes())
    assert len(new_nodes) == len(initial_nodes) + 1
    assert any("world" in nid for nid in new_nodes)
    assert any("hello" in nid for nid in new_nodes)

    # Check that graph.json and index.db were exported
    out = tmp_path / "graph_fy_out"
    graph_json = out / "graph.json"
    index_db = out / "index.db"
    assert graph_json.exists()
    assert index_db.exists()

    # Verify graph.json contents
    exported = json.loads(graph_json.read_text(encoding="utf-8"))
    exported_node_ids = {n["id"] for n in exported.get("nodes", [])}
    assert exported_node_ids == new_nodes

    # Verify FTS5 index contains the newly added function
    conn = sqlite3.connect(index_db)
    cur = conn.cursor()
    cur.execute("SELECT node_id FROM nodes_fts WHERE nodes_fts MATCH 'world'")
    rows = cur.fetchall()
    conn.close()
    assert len(rows) >= 1


def test_patch_graph_in_memory_remove_function(tmp_path: Path):
    """Test that removing a function from an existing file evicts its node and edges."""
    app_py = tmp_path / "app.py"
    app_py.write_text(
        "def hello():\n    return 'hello'\n\ndef to_remove():\n    return 'bye'\n",
        encoding="utf-8",
    )

    initial_ext = extract([app_py], root=tmp_path)
    G = build_from_json(initial_ext, root=tmp_path)
    assert any("to_remove" in nid for nid in G.nodes())

    # Edit app.py: remove to_remove()
    app_py.write_text("def hello():\n    return 'hello'\n", encoding="utf-8")

    G, stats = patch_graph_in_memory(G, [app_py], root=tmp_path)

    nodes = set(G.nodes())
    assert not any("to_remove" in nid for nid in nodes)
    assert any("hello" in nid for nid in nodes)
    assert any("to_remove" in str(nid) for nid in stats["removed_nodes"])


def test_patch_graph_in_memory_consecutive_patches_preserves_integrity(tmp_path: Path):
    """Test that multiple consecutive patches on one file preserve graph integrity (node/edge counts)."""
    a_py = tmp_path / "a.py"
    b_py = tmp_path / "b.py"

    a_py.write_text("def calc(x):\n    return x * 2\n", encoding="utf-8")
    b_py.write_text(
        "from a import calc\n\ndef run(n):\n    return calc(n)\n",
        encoding="utf-8",
    )

    initial_ext = extract([a_py, b_py], root=tmp_path)
    G = build_from_json(initial_ext, root=tmp_path)

    initial_node_count = G.number_of_nodes()
    initial_edge_count = G.number_of_edges()

    # Verify cross-file edges exist
    assert initial_edge_count > 0
    cross_edges = [
        (u, v) for u, v, d in G.edges(data=True)
        if "calc" in str(u) or "calc" in str(v)
    ]
    assert len(cross_edges) > 0

    # Patch a.py consecutively 5 times without modifying functions
    for i in range(5):
        a_py.write_text(f"def calc(x):\n    # iteration {i}\n    return x * 2\n", encoding="utf-8")
        G, stats = patch_graph_in_memory(G, [a_py], root=tmp_path)
        assert G.number_of_nodes() == initial_node_count, f"Node count diverged on patch {i}"
        assert G.number_of_edges() == initial_edge_count, f"Edge count diverged on patch {i}"

    # Now add a new function to a.py
    a_py.write_text(
        "def calc(x):\n    return x * 2\n\ndef helper():\n    return 0\n",
        encoding="utf-8",
    )
    G, stats = patch_graph_in_memory(G, [a_py], root=tmp_path)
    assert G.number_of_nodes() == initial_node_count + 1
    new_edge_count = G.number_of_edges()
    assert new_edge_count > initial_edge_count

    # Another 3 consecutive patches preserving the new structure
    for j in range(3):
        a_py.write_text(
            f"def calc(x):\n    return x * 2\n\ndef helper():\n    # pass {j}\n    return 0\n",
            encoding="utf-8",
        )
        G, stats = patch_graph_in_memory(G, [a_py], root=tmp_path)
        assert G.number_of_nodes() == initial_node_count + 1
        assert G.number_of_edges() == new_edge_count


def test_patch_graph_in_memory_empty_and_deleted_files(tmp_path: Path):
    """Test patch handling when changed_files is empty or a file is deleted."""
    mod_py = tmp_path / "mod.py"
    mod_py.write_text("def test_fn(): pass\n", encoding="utf-8")

    initial_ext = extract([mod_py], root=tmp_path)
    G = build_from_json(initial_ext, root=tmp_path)
    init_nodes = G.number_of_nodes()

    # Empty changed_files returns G unchanged
    G, stats = patch_graph_in_memory(G, [], root=tmp_path)
    assert G.number_of_nodes() == init_nodes
    assert stats["added_nodes"] == []

    # Deleting mod.py and calling patch
    mod_py.unlink()
    G, stats = patch_graph_in_memory(G, [mod_py], root=tmp_path)
    assert G.number_of_nodes() == 0
    assert len(stats["removed_nodes"]) == init_nodes


def test_watch_hot_raises_without_watchdog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test that watch_hot raises ImportError if watchdog is not available."""
    real_import = __import__

    def mock_import(name, *args, **kwargs):
        if name.startswith("watchdog"):
            raise ImportError("mocked missing watchdog")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", mock_import)
    with pytest.raises(ImportError, match="watchdog not installed"):
        watch_hot(tmp_path)


def test_watch_hot_daemon_execution_with_mock_watchdog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test that watch_hot daemon loop processes file changes in hot mode."""
    src = tmp_path / "math_mod.py"
    src.write_text("def add(a, b): return a + b\n", encoding="utf-8")

    initial_ext = extract([src], root=tmp_path)
    G = build_from_json(initial_ext, root=tmp_path)

    recorded_patches: list[dict] = []

    class MockObserver:
        def __init__(self):
            self.handler = None

        def schedule(self, handler, path, recursive=False):
            self.handler = handler

        def start(self):
            pass

        def stop(self):
            pass

        def join(self):
            pass

    class MockEventHandler:
        pass

    class MockEvent:
        is_directory = False
        event_type = "modified"

        def __init__(self, path):
            self.src_path = str(path)

    mock_obs_instance = MockObserver()

    # Create dummy watchdog modules
    obs_mod = types.ModuleType("watchdog.observers")
    obs_mod.Observer = lambda: mock_obs_instance  # type: ignore[attr-defined]
    polling_mod = types.ModuleType("watchdog.observers.polling")
    polling_mod.PollingObserver = lambda: mock_obs_instance  # type: ignore[attr-defined]
    events_mod = types.ModuleType("watchdog.events")
    events_mod.FileSystemEventHandler = MockEventHandler  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "watchdog", types.ModuleType("watchdog"))
    monkeypatch.setitem(sys.modules, "watchdog.observers", obs_mod)
    monkeypatch.setitem(sys.modules, "watchdog.observers.polling", polling_mod)
    monkeypatch.setitem(sys.modules, "watchdog.events", events_mod)

    # Modify the file
    src.write_text("def add(a, b): return a + b\n\ndef sub(a, b): return a - b\n", encoding="utf-8")

    def on_patched(graph, stats):
        recorded_patches.append(stats)

    # Trigger mock event once observer is scheduled
    def trigger_event():
        if mock_obs_instance.handler:
            mock_obs_instance.handler.on_any_event(MockEvent(src))

    import threading
    timer = threading.Timer(0.05, trigger_event)
    timer.start()

    patched_graph = watch_hot(
        tmp_path,
        debounce=0.1,
        initial_graph=G,
        max_iterations=1,
        on_patched=on_patched,
    )
    timer.join()

    assert len(recorded_patches) == 1
    assert any("sub" in nid for nid in patched_graph.nodes())
    assert any("sub" in str(nid) for nid in recorded_patches[0]["added_nodes"])


def test_watch_hot_flag_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test that watch(..., hot=True) delegates to watch_hot."""
    called: dict[str, bool] = {"hot": False}

    def mock_watch_hot(watch_path, debounce=0.5, **kwargs):
        called["hot"] = True
        return nx.Graph()

    monkeypatch.setattr("graph_fy.watch.watch_hot", mock_watch_hot)
    watch(tmp_path, hot=True)
    assert called["hot"] is True
