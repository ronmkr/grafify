"""Typo-tolerant retrieval module for graphify.

Provides GraphRAG retrieval with typo-tolerant fuzzy matching using rapidfuzz.
"""
from __future__ import annotations

from graphify.retrieval import (
    _clean_fts_query,
    _extract_terms_from_text,
    build_index,
    explain,
    fuzzy_match_term,
    fuzzy_match_tokens,
    get_default_index_path,
    get_indexed_terms,
    max_allowed_distance,
    query,
    trace,
)

__all__ = [
    "_clean_fts_query",
    "_extract_terms_from_text",
    "build_index",
    "explain",
    "fuzzy_match_term",
    "fuzzy_match_tokens",
    "get_default_index_path",
    "get_indexed_terms",
    "max_allowed_distance",
    "query",
    "trace",
]
