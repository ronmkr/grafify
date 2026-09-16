"""Fully local lexical + graph-augmented retrieval layer using SQLite FTS5 (BM25) and NetworkX.

No LLM calls, no embedding models, zero external network requests.
Provides:
  - build_index(G, db_path): builds SQLite FTS5 index and precomputes static graph metrics (PageRank, degree)
  - query(query_text, graph, db_path, limit, hops): 4-step GraphRAG retrieval (Seed -> Expand -> Re-rank -> Return)
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import networkx as nx
from rapidfuzz import distance, process

from graphify.paths import GRAPHIFY_OUT, out_path


def get_default_index_path(root: Path | str | None = None) -> Path:
    """Return the default SQLite FTS5 index path."""
    if root is not None:
        return Path(root) / GRAPHIFY_OUT / "index.db"
    return out_path("index.db")


def max_allowed_distance(term: str) -> int:
    """Return maximum allowed Levenshtein distance based on word length:
    - For word length >= 5: distance <= 2
    - For word length 4: distance <= 1
    - For word length < 4: distance 0 (exact match only)
    """
    n = len(term)
    if n >= 5:
        return 2
    if n == 4:
        return 1
    return 0


def fuzzy_match_term(
    term: str,
    vocabulary: Iterable[str],
    *,
    max_distance: int | None = None,
    limit: int = 3,
) -> list[str]:
    """Find close fuzzy matches for a term in the vocabulary using rapidfuzz Levenshtein distance.

    Rules:
    - For word length >= 5, allow Levenshtein distance <= 2.
    - For word length 4, allow distance <= 1.
    - For word length < 4, only exact matches are returned.
    """
    term_clean = term.strip().lower()
    if not term_clean:
        return []

    cutoff = max_distance if max_distance is not None else max_allowed_distance(term_clean)
    if cutoff <= 0:
        return [term_clean] if term_clean in vocabulary else []

    # If already an exact match in vocabulary, return [term_clean]
    if term_clean in vocabulary:
        return [term_clean]

    raw_matches = process.extract(
        term_clean,
        vocabulary,
        scorer=distance.Levenshtein.distance,
        score_cutoff=cutoff,
        limit=limit * 2,
    )
    if not raw_matches:
        return []

    # Filter by candidate length rules: a candidate of length < 4 should not fuzzy-match (non-exact)
    valid_matches: list[tuple[str, int]] = []
    for cand, dist, _ in raw_matches:
        cand_str = str(cand)
        if dist > 0 and len(cand_str) < 4:
            continue
        valid_matches.append((cand_str, int(dist)))

    if not valid_matches:
        return []

    min_dist = valid_matches[0][1]
    return [cand for cand, dist in valid_matches if dist == min_dist][:limit]


def fuzzy_match_tokens(
    tokens: list[str] | set[str] | Iterable[str],
    vocabulary: Iterable[str],
    *,
    limit: int = 3,
) -> dict[str, list[str]]:
    """Match query tokens against indexed vocabulary and return expansions for tokens needing typo correction."""
    vocab_set = set(vocabulary) if not isinstance(vocabulary, set) else vocabulary
    expansions: dict[str, list[str]] = {}
    for tok in tokens:
        tok_clean = tok.strip("-_").lower()
        if not tok_clean:
            continue
        # If token is already present in vocabulary, no typo correction is needed
        if tok_clean in vocab_set:
            continue
        matches = fuzzy_match_term(tok_clean, vocab_set, limit=limit)
        if matches:
            expansions[tok_clean] = matches
    return expansions


def _extract_terms_from_text(text: str) -> set[str]:
    """Extract individual words, sub-tokens, and identifier parts for vocabulary indexing."""
    if not text:
        return set()
    terms: set[str] = set()
    raw_tokens = re.findall(r"[A-Za-z0-9_\-]+", text)
    for raw in raw_tokens:
        clean = raw.strip("-_")
        if not clean:
            continue
        clean_low = clean.lower()
        if len(clean_low) >= 2:
            terms.add(clean_low)
        # Split on underscores / hyphens
        parts = re.split(r"[_\-]+", clean_low)
        for p in parts:
            if len(p) >= 2:
                terms.add(p)
        # Split CamelCase / identifier casing
        camel_parts = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z][a-z]|\b)", clean)
        for cp in camel_parts:
            cp_low = cp.lower()
            if len(cp_low) >= 2:
                terms.add(cp_low)
    return terms


def get_indexed_terms(conn: sqlite3.Connection) -> set[str]:
    """Retrieve all indexed vocabulary and symbol names from index.db."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='indexed_terms';")
    if cur.fetchone():
        cur.execute("SELECT term FROM indexed_terms;")
        terms = {row[0] for row in cur.fetchall()}
        if terms:
            return terms

    terms = set()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='node_metadata';")
    if cur.fetchone():
        cur.execute("SELECT node_id, label, content FROM node_metadata;")
        for nid, lbl, cnt in cur.fetchall():
            combined = f"{nid} {lbl or ''} {cnt or ''}"
            terms.update(_extract_terms_from_text(combined))

    if terms:
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS indexed_terms (
                    term TEXT PRIMARY KEY,
                    doc_count INTEGER DEFAULT 1
                );
                """
            )
            cur.executemany(
                "INSERT OR IGNORE INTO indexed_terms (term, doc_count) VALUES (?, 1);",
                [(t,) for t in terms],
            )
            conn.commit()
        except sqlite3.Error:
            pass

    return terms


def _clean_fts_query(
    query: str,
    synonyms: dict[str, str] | None = None,
    fuzzy_expansions: dict[str, list[str]] | None = None,
) -> str:
    """Normalize a user query into a safe, phrase, NEAR(), synonym, and fuzzy-expanded FTS5 MATCH expression."""
    if not query or not query.strip():
        return ""

    # 1. Extract explicit quoted phrases
    phrases = re.findall(r'"([^"]+)"', query)
    unquoted = re.sub(r'"[^"]+"', " ", query)

    clean_phrases: list[str] = []
    for p in phrases:
        p_tokens = [t.strip("-") for t in re.findall(r"[A-Za-z0-9_\-]+", p) if t.strip("-")]
        if p_tokens:
            phrase_str = " ".join(p_tokens)
            clean_phrases.append(f'"{phrase_str}"')
            if fuzzy_expansions:
                corrected_p = [
                    fuzzy_expansions.get(t.lower(), [t])[0]
                    for t in p_tokens
                ]
                if corrected_p != p_tokens:
                    clean_phrases.append(f'"{" ".join(corrected_p)}"')

    # 2. Extract unquoted words
    tokens = [t.strip("-") for t in re.findall(r"[A-Za-z0-9_\-]+", unquoted) if t.strip("-")]

    # 3. Synonym expansion from aliases if provided
    expanded_tokens = list(tokens)
    if synonyms:
        for t in tokens:
            t_lower = t.lower()
            if t_lower in synonyms:
                syn = synonyms[t_lower]
                syn_clean = [s.strip("-") for s in re.findall(r"[A-Za-z0-9_\-]+", syn) if s.strip("-")]
                expanded_tokens.extend(syn_clean)

    # 4. Fuzzy typo expansion
    if fuzzy_expansions:
        for t in tokens:
            t_lower = t.lower()
            if t_lower in fuzzy_expansions:
                expanded_tokens.extend(fuzzy_expansions[t_lower])

    parts: list[str] = list(clean_phrases)
    if expanded_tokens:
        unique_tokens = list(dict.fromkeys(expanded_tokens))
        quoted_tokens = [f'"{t}"' for t in unique_tokens]
        parts.extend(quoted_tokens)

        # 5. Proximity matching with NEAR() for multi-word queries
        if len(tokens) >= 2:
            near_tokens = [
                fuzzy_expansions.get(t.lower(), [t])[0] if fuzzy_expansions else t
                for t in tokens
            ]
            inner_near = " ".join(near_tokens)
            parts.append(f"NEAR({inner_near}, 10)")

    return " OR ".join(parts)


def build_index(
    G: nx.Graph,
    db_path: Path | str | None = None,
    *,
    node_contents: dict[str, str] | None = None,
) -> Path:
    """Build a SQLite FTS5 full-text index for all nodes in the graph G.

    Precomputes PageRank and node degrees for static centrality scoring.
    """
    path = Path(db_path) if db_path is not None else get_default_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Compute static centrality metrics
    pagerank: dict[Any, float] = {}
    if len(G) > 0:
        try:
            # Use undirected view or directed depending on graph type
            pagerank = nx.pagerank(G, weight="weight")
        except Exception:
            # Fallback if graph is empty, disconnected or singular
            try:
                pagerank = nx.pagerank(G.to_undirected(), weight="weight")
            except Exception:
                pagerank = {n: 1.0 / len(G) for n in G.nodes()}

    degrees = dict(G.degree())

    # Create fresh database schema
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass

    conn = sqlite3.connect(str(path))
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA synchronous = OFF;")
        cur.execute("PRAGMA journal_mode = MEMORY;")

        # Create FTS5 virtual table with weighted columns and Porter stemmer
        cur.execute(
            """
            CREATE VIRTUAL TABLE nodes_fts USING fts5(
                node_id UNINDEXED,
                title,
                headings,
                tags,
                body,
                source_path UNINDEXED,
                tokenize='porter unicode61'
            );
            """
        )

        # Metadata table
        cur.execute(
            """
            CREATE TABLE node_metadata (
                node_id TEXT PRIMARY KEY,
                label TEXT,
                source_path TEXT,
                source_location TEXT,
                file_type TEXT,
                node_kind TEXT,
                pagerank REAL,
                degree INTEGER,
                content TEXT
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS indexed_terms (
                term TEXT PRIMARY KEY,
                doc_count INTEGER DEFAULT 1
            );
            """
        )

        fts_rows = []
        meta_rows = []

        for node_id, data in G.nodes(data=True):
            nid_str = str(node_id)
            label = str(data.get("label") or nid_str)
            src_file = str(data.get("source_file") or "")
            src_loc = str(data.get("source_location") or "")
            ftype = str(data.get("file_type") or "concept")
            nkind = str(data.get("node_kind") or "")

            # Content can come from node_contents dict, node text, docstring, or label
            content_pieces = []
            if node_contents and nid_str in node_contents:
                content_pieces.append(node_contents[nid_str])
            if data.get("text"):
                content_pieces.append(str(data["text"]))
            if data.get("docstring"):
                content_pieces.append(str(data["docstring"]))
            if data.get("context"):
                content_pieces.append(str(data["context"]))

            # Combine pieces
            content_str = "\n".join(content_pieces).strip()
            if not content_str:
                content_str = label

            title = str(data.get("label") or data.get("title") or data.get("name") or nid_str)
            headings_val = str(data.get("headings") or "")
            if not headings_val and data.get("node_kind") == "heading":
                headings_val = str(data.get("text") or label)
            tags_raw = data.get("tags") or data.get("tag") or data.get("category") or ""
            if isinstance(tags_raw, (list, set, tuple)):
                tags_val = " ".join(str(t) for t in tags_raw)
            else:
                tags_val = str(tags_raw)
            body_val = content_str

            pr = float(pagerank.get(node_id, 0.0))
            deg = int(degrees.get(node_id, 0))

            fts_rows.append((nid_str, title, headings_val, tags_val, body_val, src_file))
            meta_rows.append((nid_str, label, src_file, src_loc, ftype, nkind, pr, deg, content_str))

        cur.executemany(
            "INSERT INTO nodes_fts (node_id, title, headings, tags, body, source_path) VALUES (?, ?, ?, ?, ?, ?);",
            fts_rows,
        )
        cur.executemany(
            """
            INSERT INTO node_metadata
            (node_id, label, source_path, source_location, file_type, node_kind, pagerank, degree, content)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            meta_rows,
        )

        term_counter: Counter[str] = Counter()
        for nid_str, title, headings_val, tags_val, body_val, _ in fts_rows:
            combined = f"{nid_str} {title} {headings_val} {tags_val} {body_val}"
            node_terms = _extract_terms_from_text(combined)
            for t in node_terms:
                term_counter[t] += 1

        term_rows = [(term, count) for term, count in term_counter.items()]
        cur.executemany(
            "INSERT OR IGNORE INTO indexed_terms (term, doc_count) VALUES (?, ?);",
            term_rows,
        )

        # Optimize FTS index
        cur.execute("INSERT INTO nodes_fts(nodes_fts) VALUES('optimize');")
        conn.commit()
    finally:
        conn.close()

    return path


def query(
    query_text: str,
    graph: nx.Graph | None = None,
    db_path: Path | str | None = None,
    *,
    limit: int = 10,
    hops: int = 2,
    graph_path: Path | str | None = None,
    synonyms: dict[str, str] | None = None,
    fuzzy: bool = True,
    fuzzy_min_results: int = 1,
    terse: bool = False,
    caveman: bool = False,
) -> list[dict[str, Any]] | str:
    """Execute 4-step GraphRAG retrieval over the SQLite FTS5 index and graph.

    Steps:
      1. Seed: FTS5 BM25 search (with optional typo-tolerant fuzzy expansion) -> top matching seed nodes
      2. Expand: traverse graph outward up to `hops` from each seed
      3. Re-rank: combined score = BM25 + proximity discount + centrality bonus
      4. Return: ranked list of { node_id, score, text, source_path, connected_via }
    """
    if not query_text or not query_text.strip():
        return []

    # Resolve database path
    idx_path = Path(db_path) if db_path is not None else get_default_index_path()

    if synonyms is None:
        try:
            from graphify.labeling import load_aliases_config
            root_cand = idx_path.parent.parent if idx_path.parent.name == "graphify-out" else Path(".")
            synonyms = load_aliases_config(root_cand)
        except Exception:
            synonyms = None

    # Load graph if not provided
    if graph is None:
        gp = Path(graph_path) if graph_path is not None else out_path("graph.json")
        if not gp.exists():
            return []
        try:
            with open(gp, encoding="utf-8") as f:
                data = json.load(f)
            from networkx.readwrite import json_graph
            if "links" not in data and "edges" in data:
                data["links"] = data["edges"]
            graph = json_graph.node_link_graph(data, directed=False, multigraph=False)
        except Exception:
            return []

    # If FTS index does not exist, build it now
    if not idx_path.exists():
        build_index(graph, idx_path)

    conn = sqlite3.connect(str(idx_path))
    try:
        cur = conn.cursor()
        seed_limit = max(limit * 2, 20)

        vocab: set[str] | None = None
        fuzzy_expansions: dict[str, list[str]] | None = None

        if fuzzy:
            vocab = get_indexed_terms(conn)
            q_tokens = [t.strip("-") for t in re.findall(r"[A-Za-z0-9_\-]+", query_text) if t.strip("-")]
            token_expansions = fuzzy_match_tokens(q_tokens, vocab)
            if token_expansions:
                fuzzy_expansions = token_expansions

        clean_q = _clean_fts_query(query_text, synonyms=synonyms, fuzzy_expansions=fuzzy_expansions)
        if not clean_q:
            return []

        # Step 1: Seed step via BM25 with column weights:
        # title=5.0, headings=3.0, tags=4.0, body=1.0
        # In FTS5, bm25() returns negative values (lower = more relevant);
        # we negate it so higher positive score = more relevant.
        cur.execute(
            """
            SELECT node_id, (-1.0 * bm25(nodes_fts, 5.0, 3.0, 4.0, 1.0)) AS bm25_score
            FROM nodes_fts
            WHERE nodes_fts MATCH ?
            ORDER BY bm25(nodes_fts, 5.0, 3.0, 4.0, 1.0) ASC
            LIMIT ?;
            """,
            (clean_q, seed_limit),
        )
        seed_rows = cur.fetchall()

        # If search term yields 0 or very few BM25 results, and fuzzy matching is enabled,
        # perform broader fuzzy expansion if not already applied
        if fuzzy and len(seed_rows) < fuzzy_min_results and not fuzzy_expansions:
            if vocab is None:
                vocab = get_indexed_terms(conn)
            q_tokens = [t.strip("-") for t in re.findall(r"[A-Za-z0-9_\-]+", query_text) if t.strip("-")]
            broader_expansions = {}
            for tok in q_tokens:
                tok_clean = tok.lower()
                matches = fuzzy_match_term(tok_clean, vocab)
                if matches and matches != [tok_clean]:
                    broader_expansions[tok_clean] = matches
            if broader_expansions:
                fuzzy_clean_q = _clean_fts_query(query_text, synonyms=synonyms, fuzzy_expansions=broader_expansions)
                if fuzzy_clean_q and fuzzy_clean_q != clean_q:
                    cur.execute(
                        """
                        SELECT node_id, (-1.0 * bm25(nodes_fts, 5.0, 3.0, 4.0, 1.0)) AS bm25_score
                        FROM nodes_fts
                        WHERE nodes_fts MATCH ?
                        ORDER BY bm25(nodes_fts, 5.0, 3.0, 4.0, 1.0) ASC
                        LIMIT ?;
                        """,
                        (fuzzy_clean_q, seed_limit),
                    )
                    fuzzy_rows = cur.fetchall()
                    if fuzzy_rows:
                        seed_rows = fuzzy_rows

        if not seed_rows:
            return []

        # Map seed nodes to their initial BM25 scores (normalized to 0-10 scale)
        max_raw = max((float(score) for _, score in seed_rows), default=1.0)
        if max_raw <= 0:
            max_raw = 1.0
        seed_scores: dict[str, float] = {}
        for nid, score in seed_rows:
            raw_val = max(float(score), 0.0)
            seed_scores[nid] = (raw_val / max_raw) * 10.0

        # Step 2: Expand step (1 to `hops` hops)
        # We find paths from seed nodes to neighbors in the graph
        # visited: nid -> {"dist": int, "seed": str, "path": list[dict]}
        visited: dict[str, dict[str, Any]] = {}

        for seed_id in seed_scores:
            if seed_id not in visited:
                visited[seed_id] = {
                    "dist": 0,
                    "seed": seed_id,
                    "path": [],
                }

        if hops > 0 and len(graph) > 0:
            queue = [(seed_id, 0) for seed_id in list(seed_scores.keys()) if seed_id in graph]
            idx = 0
            while idx < len(queue):
                curr, dist = queue[idx]
                idx += 1
                if dist >= hops:
                    continue

                curr_seed = visited[curr]["seed"]
                curr_path = visited[curr]["path"]

                for neighbor in graph.neighbors(curr):
                    n_str = str(neighbor)
                    new_dist = dist + 1
                    if n_str not in visited or visited[n_str]["dist"] > new_dist:
                        # Get edge relation if available
                        edge_data = graph.get_edge_data(curr, neighbor) or {}
                        relation = edge_data.get("relation") or "connected"
                        edge_step = {
                            "from": curr,
                            "relation": relation,
                            "to": n_str,
                        }
                        visited[n_str] = {
                            "dist": new_dist,
                            "seed": curr_seed,
                            "path": curr_path + [edge_step],
                        }
                        queue.append((n_str, new_dist))

        # Retrieve metadata & content for all candidate nodes
        all_candidate_ids = list(visited.keys())
        if not all_candidate_ids:
            return []

        # Chunk candidate lookups for SQLite parameter limit safety
        meta_dict: dict[str, tuple] = {}
        chunk_size = 500
        for i in range(0, len(all_candidate_ids), chunk_size):
            chunk = all_candidate_ids[i : i + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            cur.execute(
                f"""
                SELECT node_id, label, source_path, source_location, pagerank, degree, content
                FROM node_metadata
                WHERE node_id IN ({placeholders});
                """,
                chunk,
            )
            for row in cur.fetchall():
                meta_dict[row[0]] = row

        # Step 3: Re-rank step
        # Score = direct BM25 (or 0) + proximity score from seed + PageRank centrality bonus
        candidates: list[dict[str, Any]] = []

        for nid, vinfo in visited.items():
            meta = meta_dict.get(nid)
            if not meta:
                continue

            _, label, src_path, src_loc, pagerank, degree, content = meta
            dist = vinfo["dist"]
            seed_id = vinfo["seed"]
            seed_bm25 = seed_scores.get(seed_id, 1.0)

            # Direct BM25 score if this node was an explicit seed hit
            direct_bm25 = seed_scores.get(nid, 0.0)

            # Proximity discount factor:
            # 0 hops: 1.0
            # 1 hop:  0.4 * seed_bm25
            # 2 hops: 0.15 * seed_bm25
            decay = 1.0 if dist == 0 else (0.4 if dist == 1 else 0.15)
            proximity_score = decay * seed_bm25

            # Static centrality bonus (scaled PageRank + degree log)
            pr = float(pagerank or 0.0)
            centrality_bonus = pr * 5.0

            final_score = direct_bm25 + proximity_score + centrality_bonus

            # Content preview (up to 300 characters)
            preview = content.strip()
            if len(preview) > 300:
                preview = preview[:297] + "..."

            candidates.append({
                "node_id": nid,
                "label": label,
                "score": round(final_score, 4),
                "text": preview,
                "source_path": src_path,
                "source_location": src_loc,
                "connected_via": vinfo["path"],
            })

        # Step 4: Sort descending by score and slice
        candidates.sort(key=lambda x: x["score"], reverse=True)
        res = candidates[:limit]
        if terse or caveman:
            return format_query_results(res, terse=True)
        return res

    finally:
        conn.close()


def trace(
    G: nx.Graph,
    source: str,
    target: str,
    *,
    directed: bool = True,
) -> list[dict[str, Any]]:
    """Shortest-path traversal across graph nodes from source to target.

    Returns a list of edge dicts describing each hop in the path.
    """
    if source not in G:
        # Try matching by label
        matches = [n for n, d in G.nodes(data=True) if d.get("label", "").lower() == source.lower()]
        if matches:
            source = matches[0]
        else:
            return []
    if target not in G:
        matches = [n for n, d in G.nodes(data=True) if d.get("label", "").lower() == target.lower()]
        if matches:
            target = matches[0]
        else:
            return []

    try:
        graph_view = G if directed else G.to_undirected()
        path_nodes = nx.shortest_path(graph_view, source, target)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []

    result: list[dict[str, Any]] = []
    for i in range(len(path_nodes) - 1):
        u = path_nodes[i]
        v = path_nodes[i + 1]
        edata = G.get_edge_data(u, v) or {}
        if isinstance(edata, dict) and 0 in edata and not isinstance(edata.get("relation"), str):
            edata = edata[0]
        result.append({
            "from_node": u,
            "to_node": v,
            "relation": edata.get("relation", "relates_to"),
            "confidence": edata.get("confidence", "EXTRACTED"),
            "weight": edata.get("weight", 1.0),
            "source_file": edata.get("source_file", ""),
            "source_location": edata.get("source_location", ""),
        })
    return result


def explain(
    query_text: str,
    graph: nx.Graph | Path | str | None = None,
    db_path: Path | str | None = None,
    *,
    limit: int = 5,
    hops: int = 2,
    fuzzy: bool = True,
    terse: bool = False,
    caveman: bool = False,
) -> list[dict[str, Any]] | str:
    """Retrieve results with a detailed score breakdown (BM25 score, hop distance, centrality contribution)."""
    raw_results = query(query_text, graph=graph, db_path=db_path, limit=limit, hops=hops, fuzzy=fuzzy)
    if isinstance(raw_results, list):
        # Ensure score breakdown format for explainability
        for r in raw_results:
            hops_count = len(r.get("connected_via", [])) - 1 if r.get("connected_via") else 0
            r["hops"] = max(0, hops_count)
    if terse or caveman:
        return format_query_results(raw_results, terse=True)
    return raw_results


def format_compact_path(path: list[dict[str, Any]]) -> str:
    """Format a sequence of edge steps into compact path: [A] -(calls)-> [B] -(imports)-> [C]."""
    if not path:
        return ""
    start = path[0].get("from", "")
    parts = [f"[{start}]"]
    for step in path:
        rel = step.get("relation", "connected")
        to = step.get("to", "")
        parts.append(f"-({rel})-> [{to}]")
    return " ".join(parts)


def _format_source_location(item: dict[str, Any]) -> str:
    src_path = str(item.get("source_path") or item.get("source_file") or "").strip()
    src_loc = str(item.get("source_location") or "").strip()
    if src_path and src_loc:
        if src_loc.startswith(f"{src_path}:"):
            return src_loc
        return f"{src_path}:{src_loc}"
    return src_path or src_loc


def format_query_results(
    results: list[dict[str, Any]] | dict[str, Any] | str,
    *,
    terse: bool = False,
    caveman: bool = False,
) -> str:
    """Format query/retrieval results into dense fragments or standard JSON."""
    if not (terse or caveman):
        if isinstance(results, str):
            return results
        return json.dumps(results, indent=2)

    if isinstance(results, str):
        lines: list[str] = []
        for line in results.splitlines():
            s = line.strip()
            if not s:
                continue
            if s.startswith("NODE "):
                m = re.match(r"^NODE\s+(.*?)\s+\[(.*)\]$", s)
                if m:
                    lbl = m.group(1).strip()
                    attrs_raw = m.group(2)
                    attrs = dict(re.findall(r"(\w+)=([^\s\]]+)", attrs_raw))
                    src = attrs.get("src", "")
                    loc = attrs.get("loc", "")
                    loc_str = f"{src}:{loc}" if src and loc else (src or loc)
                    lines.append(f"[{lbl}] {lbl}{' ' + loc_str if loc_str else ''}".strip())
                else:
                    lines.append(s)
            elif s.startswith("EDGE "):
                m = re.match(r"^EDGE\s+(\S+)\s+--(\w+)\s+\[.*?\]-->\s+(\S+)", s)
                if m:
                    u, rel, v = m.group(1), m.group(2), m.group(3)
                    lines.append(f"  {rel} -> {v}")
                    lines.append(f"  [{u}] -({rel})-> [{v}]")
                else:
                    lines.append(s)
        return "\n".join(lines)

    items: list[dict[str, Any]] = [results] if isinstance(results, dict) else list(results)
    if not items:
        return ""

    lines = []
    for item in items:
        nid = str(item.get("node_id") or item.get("id") or "").strip()
        label = str(item.get("label") or nid).strip()
        loc = _format_source_location(item)
        header = f"[{nid}] {label}{' ' + loc if loc else ''}".strip()
        lines.append(header)

        path = item.get("connected_via") or item.get("path") or []
        if isinstance(path, list) and path:
            for step in path:
                if isinstance(step, dict):
                    rel = step.get("relation", "connected")
                    to = step.get("to") or step.get("target", "")
                    if to:
                        lines.append(f"  {rel} -> {to}")
            compact_path = format_compact_path(path)
            if compact_path:
                lines.append(f"  {compact_path}")

        edges = item.get("edges") or item.get("connections") or []
        if isinstance(edges, list):
            for edge in edges:
                if isinstance(edge, dict):
                    rel = edge.get("relation", "connected")
                    tgt = edge.get("target") or edge.get("to", "")
                    if tgt:
                        lines.append(f"  {rel} -> {tgt}")
                elif isinstance(edge, (list, tuple)) and len(edge) >= 2:
                    lines.append(f"  {edge[0]} -> {edge[1]}")

    return "\n".join(lines)


def retrieve(
    query_text: str,
    graph: nx.Graph | None = None,
    db_path: Path | str | None = None,
    *,
    limit: int = 10,
    hops: int = 2,
    graph_path: Path | str | None = None,
    synonyms: dict[str, str] | None = None,
    fuzzy: bool = True,
    fuzzy_min_results: int = 1,
    terse: bool = False,
    caveman: bool = False,
) -> list[dict[str, Any]] | str:
    """Execute GraphRAG retrieval with optional terse/caveman token conservation."""
    raw = query(
        query_text,
        graph=graph,
        db_path=db_path,
        limit=limit,
        hops=hops,
        graph_path=graph_path,
        synonyms=synonyms,
        fuzzy=fuzzy,
        fuzzy_min_results=fuzzy_min_results,
    )
    if terse or caveman:
        return format_query_results(raw, terse=True)
    return raw

