"""Indexing module for graphify.

Provides build_index and index path resolution for SQLite FTS5 index.
"""
from __future__ import annotations

from graphify.retrieval import (
    build_index,
    get_default_index_path,
    get_indexed_terms,
)

__all__ = [
    "build_index",
    "get_default_index_path",
    "get_indexed_terms",
]
