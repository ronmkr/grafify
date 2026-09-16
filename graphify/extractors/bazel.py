"""Bazel build graph extractor.

Extracts Bazel build graph components:
- Rules: cc_library, py_binary, java_test, go_image, etc.
- Target labels: //path/to/pkg:target, :target, @repo//pkg:target
- Dependencies (deps), sources (srcs/hdrs), and visibility
- External repos: http_archive, git_repository, bazel_dep (in WORKSPACE/MODULE.bazel)
- Starlark loads: load("@rules_...", "...")
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any


def _make_id(*parts: str) -> str:
    clean = [re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(p)).strip("_") for p in parts if p]
    return "_".join(clean)


def is_bazel_file(path: Path) -> bool:
    """Return True if path is a Bazel BUILD, WORKSPACE, MODULE.bazel, or .bzl file."""
    name = path.name.lower()
    if name in ("build", "build.bazel", "workspace", "workspace.bazel", "module.bazel"):
        return True
    if path.suffix.lower() == ".bzl":
        return True
    return False


def _extract_string_or_list(node: ast.AST) -> list[str]:
    """Extract string values from an AST node (Constant or List of Constants)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        result = []
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                result.append(elt.value)
        return result
    return []


def _resolve_target_label(raw_dep: str, current_pkg: str) -> str:
    """Normalize a Bazel target dependency into a canonical label string."""
    dep = raw_dep.strip()
    # Relative target e.g. ":lib" -> "//current/pkg:lib"
    if dep.startswith(":"):
        return f"//{current_pkg}:{dep[1:]}" if current_pkg else f"//:{dep[1:]}"
    # Target in same package without colon e.g. "lib" -> "//current/pkg:lib"
    if not dep.startswith("//") and not dep.startswith("@"):
        return f"//{current_pkg}:{dep}" if current_pkg else f"//:{dep}"
    return dep


def extract_bazel(path: Path) -> dict[str, Any]:
    """Extract Bazel BUILD, WORKSPACE, or MODULE file into graph nodes and edges."""
    str_path = str(path.resolve())
    file_nid = _make_id(str_path)
    file_name = path.name.lower()

    # Determine package path (directory containing BUILD file relative to root)
    pkg_dir = path.parent.name if path.parent.name not in (".", "/", "") else ""

    nodes: list[dict[str, Any]] = [{
        "id": file_nid,
        "label": f"Bazel:{path.name}",
        "type": "bazel_file",
        "file_type": "code",
        "source_file": str_path,
        "source_location": "L1",
        "text": f"Bazel file {path.name}",
    }]
    edges: list[dict[str, Any]] = []

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"nodes": nodes, "edges": edges, "error": str(exc)}

    # Parse AST
    parsed = False
    try:
        tree = ast.parse(content, filename=str(path))
        parsed = True
    except SyntaxError:
        tree = None

    if parsed and tree is not None:
        for stmt in tree.body:
            # Handle function call statements (rule invocations, load statements, etc.)
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                call = stmt.value
                line = getattr(stmt, "lineno", 1)
                loc = f"L{line}"

                # 1. load statements: load("@repo//pkg:defs.bzl", "symbol1", ...)
                if isinstance(call.func, ast.Name) and call.func.id == "load":
                    if call.args and isinstance(call.args[0], ast.Constant):
                        bzl_path = str(call.args[0].value)
                        load_nid = _make_id("bazel_load", bzl_path)
                        nodes.append({
                            "id": load_nid,
                            "label": f"Bazel:Load:{bzl_path}",
                            "type": "bazel_load",
                            "file_type": "code",
                            "bzl_path": bzl_path,
                            "source_file": str_path,
                            "source_location": loc,
                            "text": f"Loaded Bazel definition {bzl_path}",
                        })
                        edges.append({
                            "source": file_nid,
                            "target": load_nid,
                            "relation": "loads",
                            "confidence": "EXTRACTED",
                            "weight": 1.0,
                            "source_file": str_path,
                            "source_location": loc,
                        })
                    continue

                # 2. External repo declarations: http_archive, git_repository, bazel_dep
                func_name = ""
                if isinstance(call.func, ast.Name):
                    func_name = call.func.id
                elif isinstance(call.func, ast.Attribute):
                    func_name = call.func.attr

                kwargs: dict[str, ast.AST] = {kw.arg: kw.value for kw in call.keywords if kw.arg}

                if func_name in ("http_archive", "git_repository", "bazel_dep", "local_repository"):
                    # Target name of the repo
                    repo_name = ""
                    if "name" in kwargs and isinstance(kwargs["name"], ast.Constant):
                        repo_name = str(kwargs["name"].value)
                    elif call.args and isinstance(call.args[0], ast.Constant):
                        repo_name = str(call.args[0].value)

                    if repo_name:
                        repo_nid = _make_id("bazel_repo", repo_name)
                        nodes.append({
                            "id": repo_nid,
                            "label": f"Bazel:Repo:{repo_name}",
                            "type": "bazel_external_repo",
                            "file_type": "code",
                            "repo_name": repo_name,
                            "rule": func_name,
                            "source_file": str_path,
                            "source_location": loc,
                            "text": f"External Bazel repository {repo_name} ({func_name})",
                        })
                        edges.append({
                            "source": file_nid,
                            "target": repo_nid,
                            "relation": "declares_external_repo",
                            "confidence": "EXTRACTED",
                            "weight": 1.0,
                            "source_file": str_path,
                            "source_location": loc,
                        })
                    continue

                # 3. Target rule declarations: cc_library, py_binary, go_image, etc.
                target_name = ""
                if "name" in kwargs and isinstance(kwargs["name"], ast.Constant):
                    target_name = str(kwargs["name"].value)

                if target_name:
                    canonical_label = _resolve_target_label(f":{target_name}", pkg_dir)
                    target_nid = _make_id("bazel_target", canonical_label)

                    srcs = _extract_string_or_list(kwargs["srcs"]) if "srcs" in kwargs else []
                    hdrs = _extract_string_or_list(kwargs["hdrs"]) if "hdrs" in kwargs else []
                    deps = _extract_string_or_list(kwargs["deps"]) if "deps" in kwargs else []
                    visibility = _extract_string_or_list(kwargs["visibility"]) if "visibility" in kwargs else []

                    rule_type = f"bazel_{func_name}" if func_name else "bazel_target"
                    nodes.append({
                        "id": target_nid,
                        "label": f"Bazel:{target_name}",
                        "canonical_label": canonical_label,
                        "type": rule_type,
                        "file_type": "code",
                        "rule": func_name,
                        "target_name": target_name,
                        "package": pkg_dir,
                        "srcs": srcs,
                        "hdrs": hdrs,
                        "deps": deps,
                        "visibility": visibility,
                        "source_file": str_path,
                        "source_location": loc,
                        "text": f"Bazel target {canonical_label} ({func_name})",
                    })
                    edges.append({
                        "source": file_nid,
                        "target": target_nid,
                        "relation": "defines_target",
                        "confidence": "EXTRACTED",
                        "weight": 1.0,
                        "source_file": str_path,
                        "source_location": loc,
                    })

                    # Dependency edges
                    for dep in deps:
                        dep_canonical = _resolve_target_label(dep, pkg_dir)
                        dep_nid = _make_id("bazel_target", dep_canonical)
                        edges.append({
                            "source": target_nid,
                            "target": dep_nid,
                            "relation": "depends_on",
                            "confidence": "EXTRACTED",
                            "weight": 1.0,
                            "source_file": str_path,
                            "source_location": loc,
                        })

                    # Source file edges
                    for src in srcs + hdrs:
                        src_nid = _make_id("source_file", pkg_dir, src)
                        edges.append({
                            "source": target_nid,
                            "target": src_nid,
                            "relation": "contains_source",
                            "confidence": "EXTRACTED",
                            "weight": 1.0,
                            "source_file": str_path,
                            "source_location": loc,
                        })

    else:
        # Fallback regex parser for non-standard or malformed Starlark
        for match in re.finditer(r'([a-zA-Z0-9_]+)\s*\(\s*name\s*=\s*["\']([^"\']+)["\']', content):
            func_name = match.group(1)
            target_name = match.group(2)
            canonical_label = _resolve_target_label(f":{target_name}", pkg_dir)
            target_nid = _make_id("bazel_target", canonical_label)
            nodes.append({
                "id": target_nid,
                "label": f"Bazel:{target_name}",
                "canonical_label": canonical_label,
                "type": f"bazel_{func_name}",
                "file_type": "code",
                "target_name": target_name,
                "package": pkg_dir,
                "source_file": str_path,
                "source_location": "L1",
                "text": f"Bazel target {canonical_label} ({func_name})",
            })
            edges.append({
                "source": file_nid,
                "target": target_nid,
                "relation": "defines_target",
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": "L1",
            })

    return {"nodes": nodes, "edges": edges}
