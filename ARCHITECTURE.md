# Architecture

graphify is a fully local knowledge graph builder and statistical retrieval engine backed by a Python library, integrated with Claude Code and GitHub Copilot. Zero network calls, zero LLMs, zero ML models.

## Pipeline

```
detect()  →  extract()  →  cross_resolve()  →  build()  →  labeling()  →  cluster()  →  analyze helpers  →  report.generate()  →  retrieval.build_index()
```

Each stage lives in its own module and they communicate through plain Python dicts and NetworkX graphs - no shared state, no side effects outside `graphify-out/`.

## Module responsibilities

Signatures below are the real ones - `tests/test_architecture_doc.py` imports every symbol named here, so this table cannot drift from the code.

| Module | Entry point(s) | Input → Output |
|--------|----------------|----------------|
| `detect.py` | `detect(root)` | directory → scan summary dict: `files` grouped by category, plus `total_files`, `total_words`, `warning`, `scan_root`, … |
| `extract.py` | `extract(paths, *, root=None, ...)`, `collect_files(target)` | **list** of file paths → `{nodes, edges}` dict. `collect_files` expands a directory into that list, and lives here, not in `detect.py` |
| `cross_resolve.py` | `resolve_cross_format_dependencies(nodes, edges)` | nodes + edges → cross-format linked dependency chains (Terraform, Helm, K8s, Docker, CloudFormation, Argo CD) |
| `lint.py` | `run_lint(nodes, edges)` | nodes + edges → architecture drift and lint findings (unpinned actions, environment drift, missing secrets, broken refs) |
| `tfidf.py` | `compute_node_keywords(nodes)` | nodes → per-node salient keyword labels via deterministic TF-IDF |
| `build.py` | `build(extractions)`, `build_from_json(extraction)` | extraction dict(s) → `nx.Graph` |
| `labeling.py` | `apply_labeling_improvements(G)`, `make_slug(text)`, `load_aliases_config(root)` | graph / string → slugified IDs, merged synonyms, typed namespaces |
| `cluster.py` | `cluster(G)` | graph → `{community_id: [node_id, ...]}` (the graph is not mutated) |
| `analyze.py` | `god_nodes(G)`, `surprising_connections(G)`, `suggest_questions(G, communities, community_labels)`, `find_import_cycles(G)`, `graph_diff(G_old, G_new)` | graph → one list/dict per analysis. There is no single `analyze()` entry point |
| `report.py` | `generate(G, communities, cohesion_scores, community_labels, ...)` | graph + analysis → GRAPH_REPORT.md string |
| `retrieval.py` | `build_index(G, db_path)`, `query(query_text, graph, db_path)`, `trace(G, source, target)`, `explain(query_text, graph, db_path)` | graph + SQLite FTS5 → 4-step GraphRAG retrieval (seed, expand, re-rank, return) + shortest-path trace |
| `impact.py` | `compute_impact(graph, target)`, `format_impact_report(impact_data)` | graph + target → predictive blast radius closure, affected tests/endpoints/IaC, risk score |
| `flow.py` | `trace_execution_flow(graph, entry_point)`, `format_flow_diagram(flow_data)` | graph + entry_point → entry-to-sink execution paths and ASCII flow diagram |
| `mcp.py` | `find_definitions(query)`, `get_callers(symbol)`, `get_callees(symbol)`, `find_references(symbol)`, `find_implementations(symbol)`, `estimate_token_savings(subgraph_nodes)` | graph → fine-grained code navigation, symbol declarations, call hierarchies, token savings |
| `export.py` | `to_json`, `to_html`, `to_obsidian`, `to_svg`, `to_graphml`, `to_canvas`, `to_cypher` | graph → graph.json, graph.html, Obsidian vault, graph.svg, … one function per format |
| `wiki.py` | `to_wiki(G, communities, output_dir, ...)` | graph → one markdown article per community + `index.md` |
| `callflow_html.py` | `write_callflow_html(...)` | graphify-out files → Mermaid architecture/call-flow HTML |
| `ingest.py` | `ingest(url, target_dir, ...)` | URL → file saved to corpus dir |
| `cache.py` | `check_semantic_cache(files, root)`, `save_semantic_cache(nodes, edges, ...)` | files → cached nodes / edges / hyperedges + the list of files still needing extraction |
| `security.py` | `validate_url`, `safe_fetch`, `validate_graph_path`, `sanitize_label` | URL / path / label → validated value, or raises |
| `validate.py` | `validate_extraction(data)`, `assert_valid(data)` | extraction dict → **list of schema error strings** (`validate_extraction` returns them; `assert_valid` raises) |
| `serve.py` | `serve(graph_path)`, `serve_http(graph_path, *, host, port, ...)` | graph file path → MCP stdio server / HTTP server |
| `watch.py` | `watch(watch_path, debounce=3.0)`, `check_update(watch_path)` | directory → rebuild on change; `check_update` reports whether a re-extraction is pending |
| `benchmark.py` | `run_benchmark(graph_path)` | graph file → corpus vs subgraph token comparison |

### Calling `extract()` from your own code

`extract()` takes a **list** of paths, and `root` is keyword-only and optional:

```python
from pathlib import Path
from graphify.extract import extract

paths = [Path("src/lib/content.ts"), Path("src/pages/index.astro")]
result = extract(paths, root=Path(".").resolve())   # pass root explicitly
```

Always pass `root`. Node ids and `source_file` values are derived relative to it; when it is omitted, `extract()` infers one from the paths you passed, which is the common parent of *that list* rather than your project root. A single-file call therefore anchors to that file's own directory, and ids can end up carrying path segments from the machine they were extracted on.

## Extraction output schema

Every extractor returns:

```json
{
  "nodes": [
    {"id": "unique_string", "label": "human name", "source_file": "path", "source_location": "L42"}
  ],
  "edges": [
    {"source": "id_a", "target": "id_b", "relation": "calls|imports|uses|...", "confidence": "EXTRACTED|INFERRED|AMBIGUOUS"}
  ]
}
```

`validate.py` enforces this schema before `build()` consumes it.

## Confidence labels

| Label | Meaning |
|-------|---------|
| `EXTRACTED` | Relationship is explicitly stated in the source (e.g., an import statement, a direct call) |
| `INFERRED` | Relationship is a reasonable deduction (e.g., call-graph second pass, co-occurrence in context) |
| `AMBIGUOUS` | Relationship is uncertain; flagged for human review in GRAPH_REPORT.md |

## Adding a new language extractor

1. Add an `extract_<lang>(path: Path) -> dict` function following the existing pattern (tree-sitter parse → walk nodes → collect `nodes` and `edges` → call-graph second pass for INFERRED `calls` edges). New languages go in their own module under `graphify/extractors/` - see `graphify/extractors/MIGRATION.md`; `extract.py` re-exports them while the existing ones are ported out of it.
2. Register the file suffix in `extract()`'s dispatch table and in `collect_files()` (both in `extract.py`).
3. Add the suffix to `CODE_EXTENSIONS` in `detect.py` and `_WATCHED_EXTENSIONS` in `watch.py`.
4. Add the tree-sitter package to `pyproject.toml` dependencies.
5. Add a fixture file to `tests/fixtures/` and tests to `tests/test_languages.py`.

## Security

All external input passes through `graphify/security.py` before use:

- URLs → `validate_url()` (http/https only) + `_NoFileRedirectHandler` (blocks file:// redirects)
- Fetched content → `safe_fetch()` / `safe_fetch_text()` (size cap, timeout)
- Graph file paths → `validate_graph_path()` (must resolve inside `graphify-out/`)
- Node labels → `sanitize_label()` (strips control chars, caps 256 chars, HTML-escapes)

See `SECURITY.md` for the full threat model.

## Testing

One test file per module under `tests/`. Run with:

```bash
pytest tests/ -q
```

All tests are pure unit tests - no network calls, no file system side effects outside `tmp_path`.
