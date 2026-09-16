"""Monorepo workspace & task pipeline extractor (pnpm, Turbo, Nx, Lerna).

Extracts:
1. pnpm-workspace.yaml: packages globs, workspace root definition
2. turbo.json: pipeline & tasks, task dependencies (^build, etc.), cache outputs
3. nx.json & project.json: Nx projects, projectType (app/lib), targets, dependsOn
4. lerna.json: package directories, versioning model
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


def _make_id(*parts: str) -> str:
    clean = [re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(p)).strip("_") for p in parts if p]
    return "_".join(clean)


def is_monorepo_file(path: Path) -> bool:
    """Return True if path is a monorepo configuration file."""
    name = path.name.lower()
    return name in (
        "pnpm-workspace.yaml",
        "pnpm-workspace.yml",
        "turbo.json",
        "nx.json",
        "project.json",
        "lerna.json",
    )


def extract_monorepo(path: Path) -> dict[str, Any]:
    """Extract monorepo workspace configuration into graph nodes and edges."""
    str_path = str(path.resolve())
    file_nid = _make_id(str_path)
    file_name = path.name.lower()

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"nodes": nodes, "edges": edges, "error": str(exc)}

    if file_name in ("pnpm-workspace.yaml", "pnpm-workspace.yml"):
        _extract_pnpm_workspace(path, str_path, file_nid, content, nodes, edges)
    elif file_name == "turbo.json":
        _extract_turborepo(path, str_path, file_nid, content, nodes, edges)
    elif file_name == "nx.json":
        _extract_nx_root(path, str_path, file_nid, content, nodes, edges)
    elif file_name == "project.json":
        _extract_nx_project(path, str_path, file_nid, content, nodes, edges)
    elif file_name == "lerna.json":
        _extract_lerna(path, str_path, file_nid, content, nodes, edges)

    return {"nodes": nodes, "edges": edges}


def _extract_pnpm_workspace(
    path: Path,
    str_path: str,
    file_nid: str,
    content: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    data = yaml.safe_load(content) or {}
    packages = data.get("packages") or []

    ws_node = {
        "id": file_nid,
        "label": "Monorepo:pnpm-workspace",
        "type": "pnpm_workspace",
        "file_type": "code",
        "package_patterns": packages,
        "source_file": str_path,
        "source_location": "L1",
        "text": f"pnpm workspace with {len(packages)} package pattern(s)",
    }
    nodes.append(ws_node)

    for pattern in packages:
        pat_nid = _make_id("workspace_pkg_pattern", str(pattern))
        nodes.append({
            "id": pat_nid,
            "label": f"Workspace:Pattern:{pattern}",
            "type": "workspace_pattern",
            "file_type": "code",
            "pattern": str(pattern),
            "source_file": str_path,
            "source_location": "L1",
            "text": f"Workspace package glob pattern {pattern}",
        })
        edges.append({
            "source": file_nid,
            "target": pat_nid,
            "relation": "includes_pattern",
            "confidence": "EXTRACTED",
            "weight": 1.0,
            "source_file": str_path,
            "source_location": "L1",
        })


def _extract_turborepo(
    path: Path,
    str_path: str,
    file_nid: str,
    content: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    try:
        data = json.loads(content)
    except Exception:
        return

    turbo_node = {
        "id": file_nid,
        "label": "Monorepo:Turborepo",
        "type": "turborepo_config",
        "file_type": "code",
        "source_file": str_path,
        "source_location": "L1",
        "text": "Turborepo configuration",
    }
    nodes.append(turbo_node)

    # In Turbo, tasks can be in "tasks" (v2) or "pipeline" (v1)
    tasks = data.get("tasks") or data.get("pipeline") or {}
    if isinstance(tasks, dict):
        for task_name, task_cfg in tasks.items():
            if not isinstance(task_cfg, dict):
                continue
            task_nid = _make_id("turbo_task", task_name)
            depends_on = task_cfg.get("dependsOn") or []
            outputs = task_cfg.get("outputs") or []

            nodes.append({
                "id": task_nid,
                "label": f"Turbo:Task:{task_name}",
                "type": "turborepo_task",
                "file_type": "code",
                "task_name": task_name,
                "depends_on": depends_on,
                "outputs": outputs,
                "source_file": str_path,
                "source_location": "L1",
                "text": f"Turborepo pipeline task {task_name}",
            })
            edges.append({
                "source": file_nid,
                "target": task_nid,
                "relation": "defines_task",
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": "L1",
            })

            # Task dependencies
            for dep in depends_on:
                clean_dep = str(dep).lstrip("^")
                dep_task_nid = _make_id("turbo_task", clean_dep)
                edges.append({
                    "source": task_nid,
                    "target": dep_task_nid,
                    "relation": "depends_on",
                    "confidence": "EXTRACTED",
                    "weight": 1.0,
                    "source_file": str_path,
                    "source_location": "L1",
                })


def _extract_nx_root(
    path: Path,
    str_path: str,
    file_nid: str,
    content: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    try:
        data = json.loads(content)
    except Exception:
        return

    nx_node = {
        "id": file_nid,
        "label": "Monorepo:Nx",
        "type": "nx_workspace",
        "file_type": "code",
        "source_file": str_path,
        "source_location": "L1",
        "text": "Nx workspace configuration",
    }
    nodes.append(nx_node)

    target_defaults = data.get("targetDefaults") or {}
    if isinstance(target_defaults, dict):
        for target_name, target_cfg in target_defaults.items():
            t_nid = _make_id("nx_target_default", target_name)
            nodes.append({
                "id": t_nid,
                "label": f"Nx:TargetDefault:{target_name}",
                "type": "nx_target_default",
                "file_type": "code",
                "target_name": target_name,
                "source_file": str_path,
                "source_location": "L1",
                "text": f"Nx target default {target_name}",
            })
            edges.append({
                "source": file_nid,
                "target": t_nid,
                "relation": "defines_target_default",
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": "L1",
            })


def _extract_nx_project(
    path: Path,
    str_path: str,
    file_nid: str,
    content: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    try:
        data = json.loads(content)
    except Exception:
        return

    proj_name = data.get("name") or path.parent.name
    proj_type = data.get("projectType") or "project"
    targets = data.get("targets") or {}

    proj_node = {
        "id": file_nid,
        "label": f"Nx:Project:{proj_name}",
        "type": f"nx_{proj_type}",
        "file_type": "code",
        "project_name": str(proj_name),
        "project_type": str(proj_type),
        "source_file": str_path,
        "source_location": "L1",
        "text": f"Nx {proj_type} {proj_name}",
    }
    nodes.append(proj_node)

    if isinstance(targets, dict):
        for target_name, target_data in targets.items():
            if not isinstance(target_data, dict):
                continue
            target_nid = _make_id("nx_target", str_path, target_name)
            executor = target_data.get("executor") or ""
            depends_on = target_data.get("dependsOn") or []

            nodes.append({
                "id": target_nid,
                "label": f"Nx:Target:{proj_name}:{target_name}",
                "type": "nx_target",
                "file_type": "code",
                "target_name": target_name,
                "executor": executor,
                "source_file": str_path,
                "source_location": "L1",
                "text": f"Nx target {target_name} for {proj_name} ({executor})",
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


def _extract_lerna(
    path: Path,
    str_path: str,
    file_nid: str,
    content: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    try:
        data = json.loads(content)
    except Exception:
        return

    packages = data.get("packages") or ["packages/*"]
    lerna_node = {
        "id": file_nid,
        "label": "Monorepo:Lerna",
        "type": "lerna_workspace",
        "file_type": "code",
        "version": data.get("version"),
        "packages": packages,
        "source_file": str_path,
        "source_location": "L1",
        "text": f"Lerna workspace with {len(packages)} package pattern(s)",
    }
    nodes.append(lerna_node)
