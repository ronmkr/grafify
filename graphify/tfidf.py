"""Per-node TF-IDF top-terms keyword extractor.

Implements Phase 8 requirement:
Deterministic, pure-Python TF-IDF keyword labeling for nodes in the knowledge graph.
Extracts text from labels, docstrings, headings, comments, metadata, etc.,
tokenizes, filters English and programming stopwords, computes TF and IDF
(log((N + 1) / (df + 1)) + 1), and attaches the top-K highest-scoring terms to each node
under 'keywords' and 'top_terms'.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

# Standard English stopwords
ENGLISH_STOPWORDS: frozenset[str] = frozenset({
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "can't", "cannot", "could",
    "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down",
    "during", "each", "few", "for", "from", "further", "had", "hadn't", "has",
    "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's",
    "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it",
    "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other",
    "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "shan't",
    "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "than", "that", "that's", "the", "their", "theirs", "them", "themselves",
    "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves",
    # Additional common functional words
    "also", "etc", "eg", "ie", "will", "shall", "just", "well",
})

# Standard programming language keywords and syntax stopwords
PROGRAMMING_STOPWORDS: frozenset[str] = frozenset({
    "def", "class", "fn", "func", "function", "var", "let", "const", "val",
    "import", "export", "from", "return", "yield", "async", "await", "try",
    "catch", "finally", "except", "throw", "raise", "if", "else", "elif",
    "for", "while", "loop", "break", "continue", "switch", "case", "default",
    "match", "true", "false", "null", "none", "nil", "undefined", "self",
    "this", "super", "new", "delete", "struct", "interface", "type", "enum",
    "impl", "pub", "public", "private", "protected", "static", "final",
    "void", "int", "float", "double", "bool", "boolean", "string", "str",
    "list", "dict", "set", "tuple", "map", "array", "object", "package",
    "namespace", "module", "use", "using", "include", "require", "echo",
    "print", "println", "log", "error", "info", "debug", "warn", "test",
    "assert", "todo", "fixme", "note", "pass", "lambda", "mut", "ref",
    "extern", "auto", "goto", "typedef", "sizeof", "override", "virtual",
    "implements", "extends", "throws", "transient", "volatile", "synchronized",
    "native", "strictfp", "operator", "template", "typename", "constexpr",
    "decltype", "noexcept", "friend", "explicit",
})

# Combined stopwords set
STOPWORDS: frozenset[str] = ENGLISH_STOPWORDS | PROGRAMMING_STOPWORDS


def tokenize(text: str, stopwords: set[str] | frozenset[str] | None = None) -> list[str]:
    """Clean, lowercase, strip punctuation, split identifiers, and remove stopwords.

    Args:
        text: Raw text string to tokenize.
        stopwords: Optional custom set of stopwords. Defaults to STOPWORDS.

    Returns:
        List of filtered, normalized term tokens.
    """
    if not text:
        return []
    sw = STOPWORDS if stopwords is None else stopwords

    # Split camelCase and PascalCase identifiers
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    s = s.lower()

    # Extract word tokens: alphanumeric characters, excluding pure numbers
    raw_tokens = re.findall(r"[a-z0-9]+", s)
    tokens: list[str] = []
    for tok in raw_tokens:
        if len(tok) < 2:
            continue
        if tok.isdigit():
            continue
        if tok in sw:
            continue
        tokens.append(tok)
    return tokens


def _collect_strings(val: Any, out: list[str]) -> None:
    """Recursively collect non-empty strings from nested dicts/lists/tuples."""
    if isinstance(val, str):
        cleaned = val.strip()
        if cleaned:
            out.append(cleaned)
    elif isinstance(val, (list, tuple, set)):
        for item in val:
            _collect_strings(item, out)
    elif isinstance(val, dict):
        for k, v in val.items():
            if isinstance(k, str) and not k.startswith("_"):
                out.append(k)
            _collect_strings(v, out)


def extract_node_text(node: dict[str, Any]) -> str:
    """Extract and combine all textual content from a node dictionary.

    Inspects node labels, docstrings, headings, comments, metadata, etc.
    """
    if not isinstance(node, dict):
        return ""

    parts: list[str] = []

    # Text fields in order of priority
    priority_fields = [
        "label", "display_label", "canonical_label", "title", "name",
        "docstring", "doc", "documentation",
        "heading", "headings",
        "comment", "comments",
        "description", "summary", "text", "body", "content", "rationale",
        "tags", "aliases",
        "metadata", "meta", "attributes",
    ]

    seen_fields = set()
    for field in priority_fields:
        seen_fields.add(field)
        if field in node:
            _collect_strings(node[field], parts)

    # Inspect other string or collection fields, skipping structural keys
    skip_keys = {
        "id", "slug", "source_file", "source_files", "node_kind", "file_type",
        "type", "degree", "community", "confidence", "relation", "weight",
    }
    for k, v in node.items():
        if k not in seen_fields and k not in skip_keys and not k.startswith("_"):
            if isinstance(v, (str, list, tuple, set, dict)):
                _collect_strings(v, parts)

    return " ".join(parts)


def compute_tf(tokens: list[str], *, normalize: bool = False) -> dict[str, float]:
    """Compute term frequency (TF) for a list of tokens.

    Args:
        tokens: Sequence of term tokens.
        normalize: If True, returns relative frequency (count / len(tokens)).
                   If False, returns raw frequency (count as float).
    """
    if not tokens:
        return {}
    counts = Counter(tokens)
    total = float(len(tokens)) if normalize else 1.0
    return {term: count / total for term, count in counts.items()}


def compute_idf(n_docs: int, df: int, *, smooth: bool = True) -> float:
    """Compute inverse document frequency: log((N + 1) / (df + 1)) + 1.

    Args:
        n_docs: Total number of documents (nodes) in the corpus.
        df: Document frequency (number of documents containing the term).
        smooth: If True (default), computes smooth IDF: log((N + 1) / (df + 1)) + 1.
                If False, computes unsmoothed IDF: log(N / (df + 1)).
    """
    if n_docs <= 0:
        return 1.0 if smooth else 0.0
    if smooth:
        return math.log((n_docs + 1) / (df + 1)) + 1.0
    ratio = n_docs / (df + 1)
    if ratio <= 0.0:
        return 0.0
    return math.log(ratio)


def compute_node_keywords(
    nodes: list[dict[str, Any]],
    top_k: int = 5,
    *,
    stopwords: set[str] | frozenset[str] | None = None,
    normalize_tf: bool = False,
) -> list[dict[str, Any]]:
    """Compute per-node TF-IDF top terms and attach them under 'keywords' and 'top_terms'.

    Args:
        nodes: List of node dictionaries.
        top_k: Number of top terms to attach per node (default 5).
        stopwords: Optional custom set of stopwords.
        normalize_tf: Whether to normalize TF by document length.

    Returns:
        The mutated list of node dictionaries with 'keywords' and 'top_terms' attached.
    """
    if not nodes:
        return nodes

    n_docs = len(nodes)

    # 1. Extract tokens per node
    node_tokens: list[list[str]] = []
    for node in nodes:
        text = extract_node_text(node)
        tokens = tokenize(text, stopwords=stopwords)
        node_tokens.append(tokens)

    # 2. Compute document frequencies across all nodes
    df: Counter[str] = Counter()
    for tokens in node_tokens:
        for term in set(tokens):
            df[term] += 1

    # 3. Compute TF-IDF scores and rank terms for each node
    for node, tokens in zip(nodes, node_tokens):
        if not tokens:
            node["keywords"] = []
            node["top_terms"] = []
            continue

        tf = compute_tf(tokens, normalize=normalize_tf)
        term_counts = Counter(tokens)

        scores: dict[str, float] = {}
        for term in set(tokens):
            idf = compute_idf(n_docs, df[term])
            scores[term] = tf[term] * idf

        # Rank terms:
        # 1. Higher TF-IDF score first (-scores[t])
        # 2. Higher raw term frequency first (-term_counts[t])
        # 3. Deterministic alphabetical order (t)
        unique_terms = sorted(
            set(tokens),
            key=lambda t: (-scores[t], -term_counts[t], t),
        )

        top_terms = unique_terms[:max(0, top_k)]
        node["keywords"] = top_terms
        node["top_terms"] = top_terms

    return nodes
