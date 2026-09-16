"""Labeling improvements, slug generation, synonym mapping, and category derivation.

Implements Phase 8 requirements:
1. Stable internal slug ID separate from human-facing display label.
2. Authority for aliases:/type:/category: frontmatter fields.
3. User-controlled synonym mapping via aliases.yaml or labels.yaml.
4. Namespacing labels by node type (Note:, Tag:, Heading:, Code:, K8s:, Helm:, Terraform:, AWS:, Kafka:).
5. Contextual typed edge labels (contains, tagged_as, references_heading, imports, selects, mounts, depends_on, owns).
6. Folder-path-derived category metadata.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any


def make_slug(text: str) -> str:
    """Generate a clean, deterministic, URL/anchor-safe slug.

    Lowercase, strips non-alphanumerics, replaces punctuation/whitespace with hyphens.
    """
    if not text:
        return "unnamed"
    text = unicodedata.normalize("NFKD", str(text))
    # Replace colon, slash, backslash, dots, whitespace, underscores with hyphens
    s = re.sub(r"[:/\\._\s]+", "-", text)
    # Strip any characters not ASCII alphanumeric or hyphen
    s = re.sub(r"[^a-zA-Z0-9-]+", "", s)
    # Collapse multiple hyphens
    s = re.sub(r"-+", "-", s).strip("-").lower()
    return s or "unnamed"


def derive_category(source_file: str | None) -> str:
    """Derive folder-path-derived category metadata from source_file path.

    e.g. 'src/api/routes.py' -> 'api'
         'docs/architecture/overview.md' -> 'docs'
         'charts/mychart/templates/deploy.yaml' -> 'helm'
         'k8s/prod/deployment.yaml' -> 'k8s'
         'tests/test_foo.py' -> 'tests'
    """
    if not source_file:
        return "general"

    posix_path = str(source_file).replace("\\", "/").strip("/")
    parts = posix_path.split("/")

    if len(parts) <= 1:
        # File in root directory
        ext = Path(posix_path).suffix.lower()
        if ext in (".md", ".txt", ".rst"):
            return "documentation"
        elif ext in (".tf", ".tfvars", ".hcl"):
            return "infrastructure"
        elif ext in (".yaml", ".yml", ".json"):
            return "configuration"
        return "root"

    # Known domain folder prefixes
    first = parts[0].lower()
    if first in ("charts", "helm"):
        return "helm"
    if first in ("k8s", "kubernetes", "manifests"):
        return "kubernetes"
    if first in ("terraform", "tf", "infra", "infrastructure", "iac"):
        return "infrastructure"
    if first in ("docs", "documentation", "wiki"):
        return "documentation"
    if first in ("tests", "test", "spec", "specs"):
        return "testing"
    if first in ("src", "lib", "app", "pkg", "packages") and len(parts) > 2:
        return parts[1].lower()

    return first


def load_aliases_config(root: Path | str | None) -> dict[str, str]:
    """Load optional root-level aliases.yaml or labels.yaml for user-controlled synonym mapping.

    Returns {alias_or_synonym: canonical_name}.
    """
    if not root:
        return {}

    root_path = Path(root)
    candidates = [
        root_path / "aliases.yaml",
        root_path / "aliases.yml",
        root_path / "labels.yaml",
        root_path / "labels.yml",
    ]

    for cand in candidates:
        if cand.is_file():
            try:
                import yaml
                data = yaml.safe_load(cand.read_text(encoding="utf-8", errors="replace"))
                if not isinstance(data, dict):
                    continue

                mapping: dict[str, str] = {}
                # Format 1: direct mapping {alias: canonical}
                # Format 2: {synonyms: {canonical: [alias1, alias2]}}
                synonyms = data.get("synonyms")
                if isinstance(synonyms, dict):
                    for canonical, aliases in synonyms.items():
                        if isinstance(aliases, list):
                            for a in aliases:
                                mapping[str(a).lower()] = str(canonical)
                        elif isinstance(aliases, str):
                            mapping[aliases.lower()] = str(canonical)

                aliases_dict = data.get("aliases")
                if isinstance(aliases_dict, dict):
                    for a, c in aliases_dict.items():
                        mapping[str(a).lower()] = str(c)

                for k, v in data.items():
                    if k not in ("synonyms", "aliases") and isinstance(v, str):
                        mapping[str(k).lower()] = str(v)

                return mapping
            except Exception:
                continue

    return {}


def apply_labeling_improvements(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    root: Path | str | None = None,
    *,
    compute_keywords: bool = False,
    top_k: int = 5,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Attach slug IDs, folder categories, aliases, normalize namespaces/edges, and optionally TF-IDF keywords."""
    alias_map = load_aliases_config(root)

    for node in nodes:
        # 1. Attach deterministic slug ID
        nid = node.get("id", "")
        lbl = node.get("label", nid)
        if "slug" not in node:
            node["slug"] = make_slug(lbl)

        # 2. Attach category metadata
        if not node.get("category"):
            node["category"] = derive_category(node.get("source_file"))

        # 3. User-controlled synonym mapping
        if alias_map:
            clean_lbl = lbl.lower()
            if clean_lbl in alias_map:
                node["canonical_label"] = alias_map[clean_lbl]
                # Keep original label in aliases
                aliases = node.setdefault("aliases", [])
                if isinstance(aliases, list) and lbl not in aliases:
                    aliases.append(lbl)

        # 4. Ensure node type namespacing
        ntype = node.get("type", "")
        nkind = node.get("node_kind", "")
        if nkind == "page" and not lbl.startswith("Note:") and node.get("file_type") == "document":
            node["display_label"] = f"Note:{lbl}"
        elif nkind == "heading" and not lbl.startswith("Heading:"):
            node["display_label"] = f"Heading:{lbl}"
        elif nkind == "tag" and not lbl.startswith("Tag:"):
            node["display_label"] = f"Tag:{lbl}"

    # 5. Canonicalize contextual edge relations
    relation_aliases = {
        "tags": "tagged_as",
        "tagged-as": "tagged_as",
        "references-heading": "references_heading",
        "depends-on": "depends_on",
    }
    for edge in edges:
        rel = edge.get("relation")
        if rel in relation_aliases:
            edge["relation"] = relation_aliases[rel]

    # 6. Optional TF-IDF keyword extraction
    if compute_keywords and nodes:
        from graphify.tfidf import compute_node_keywords

        compute_node_keywords(nodes, top_k=top_k)

    return nodes, edges
