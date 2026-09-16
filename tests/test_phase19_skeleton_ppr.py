"""Tests for Phase 19: AST Code Skeletonization and Personalized PageRank (PPR)."""
from pathlib import Path
import networkx as nx
import pytest

from graph_fy.skeleton import (
    skeletonize_code,
    skeletonize_file,
    get_symbol_code_from_file,
    get_parser_for_path,
)
from graph_fy.retrieval import compute_pagerank, query, retrieve, format_query_results
from graph_fy.mcp import get_code_skeleton, get_symbol_implementation, find_definitions


def test_python_skeletonization():
    code = b'''
def calculate_metrics(data: list[int], factor: float = 1.0) -> float:
    """Calculate aggregated metrics from list of integers."""
    total = sum(data) * factor
    return total

class MetricProcessor:
    """Processor class for metric streams."""
    factor: float = 1.0

    def __init__(self, factor: float):
        self.factor = factor

    def process(self, items: list[int]) -> float:
        return calculate_metrics(items, self.factor)
'''
    parser, lang = get_parser_for_path("test.py")
    assert parser is not None
    assert lang == "python"

    skeleton = skeletonize_code(code, parser, lang)
    assert 'def calculate_metrics(data: list[int], factor: float = 1.0) -> float:' in skeleton
    assert '"""Calculate aggregated metrics from list of integers."""' in skeleton
    assert 'total = sum(data) * factor' not in skeleton
    assert '...' in skeleton
    assert 'class MetricProcessor:' in skeleton
    assert 'def process(self, items: list[int]) -> float:' in skeleton
    assert 'return calculate_metrics' not in skeleton


def test_typescript_skeletonization():
    code = b'''
export interface MetricData {
    value: number;
}

export class MetricService {
    private scale: number;

    constructor(scale: number) {
        this.scale = scale;
    }

    public compute(data: MetricData): number {
        const res = data.value * this.scale;
        return res;
    }
}
'''
    parser, lang = get_parser_for_path("service.ts")
    assert parser is not None
    assert lang == "typescript"

    skeleton = skeletonize_code(code, parser, lang)
    assert 'export interface MetricData' in skeleton
    assert 'export class MetricService' in skeleton
    assert 'public compute(data: MetricData): number' in skeleton
    assert 'const res = data.value' not in skeleton
    assert '{ ... }' in skeleton


def test_skeletonize_file_and_get_symbol(tmp_path: Path):
    py_file = tmp_path / "sample.py"
    py_file.write_text(
        'def add(a: int, b: int) -> int:\n'
        '    """Add docstring."""\n'
        '    val = a + b\n'
        '    return val\n\n'
        'class Calc:\n'
        '    def multiply(self, x: int, y: int) -> int:\n'
        '        return x * y\n',
        encoding="utf-8",
    )

    skel = skeletonize_file(py_file)
    assert "def add(a: int, b: int) -> int:" in skel
    assert '"""Add docstring."""' in skel
    assert "val = a + b" not in skel
    assert "..." in skel

    # Test get_symbol_code_from_file
    sym_code = get_symbol_code_from_file(py_file, line_number=1)
    assert "def add(a: int, b: int) -> int:" in sym_code
    assert "val = a + b" in sym_code

    # Test skeletonized symbol code
    sym_skel = get_symbol_code_from_file(py_file, line_number=6, skeletonize=True)
    assert "class Calc:" in sym_skel
    assert "def multiply(self, x: int, y: int) -> int:" in sym_skel
    assert "return x * y" not in sym_skel


def test_pure_python_pagerank_and_ppr():
    G = nx.Graph()
    G.add_edge("A", "B")
    G.add_edge("B", "C")
    G.add_edge("C", "D")

    # Uniform PageRank
    pr_uniform = compute_pagerank(G)
    assert len(pr_uniform) == 4
    # Central nodes B and C should have higher rank than endpoints A and D
    assert pr_uniform["B"] > pr_uniform["A"]
    assert pr_uniform["C"] > pr_uniform["D"]

    # Personalized PageRank biased toward A
    ppr_a = compute_pagerank(G, personalization={"A": 10.0, "D": 0.0})
    assert ppr_a["A"] > pr_uniform["A"]
    assert ppr_a["A"] > ppr_a["D"]


def test_retrieval_with_ppr_and_skeleton(tmp_path: Path):
    src_file = tmp_path / "math_ops.py"
    src_file.write_text(
        'def add_numbers(x: int, y: int) -> int:\n'
        '    """Add two numbers and return sum."""\n'
        '    total = x + y\n'
        '    return total\n',
        encoding="utf-8",
    )

    G = nx.Graph()
    G.add_node(
        "math_add",
        label="add_numbers",
        source_file=str(src_file),
        source_location="L1",
        file_type="code",
        context="def add_numbers(x: int, y: int) -> int",
    )
    G.add_node(
        "math_helper",
        label="helper",
        source_file=str(src_file),
        source_location="L1",
        file_type="code",
        context="helper function",
    )
    G.add_edge("math_add", "math_helper", relation="calls")

    db_path = tmp_path / "index.db"
    res = query("add numbers", graph=G, db_path=db_path, limit=5, hops=1, skeleton=True)
    assert isinstance(res, list)
    assert len(res) >= 1
    top = res[0]
    assert top["node_id"] == "math_add"
    assert "skeleton" in top
    assert "def add_numbers" in top["skeleton"]
    assert "..." in top["skeleton"]
    assert "total = x + y" not in top["skeleton"]

    # Test formatted terse / caveman output with skeleton stub
    formatted = format_query_results(res, terse=True, skeleton=True)
    assert "[math_add]" in formatted
    assert "```" in formatted


def test_mcp_skeleton_and_symbol_tools(tmp_path: Path):
    src_file = tmp_path / "calc.py"
    src_file.write_text(
        'class Calculator:\n'
        '    """Calculator implementation."""\n'
        '    def add(self, a: int, b: int) -> int:\n'
        '        return a + b\n',
        encoding="utf-8",
    )

    G = nx.DiGraph()
    G.add_node(
        "calc_class",
        label="Calculator",
        name="Calculator",
        source_file=str(src_file),
        source_location="L1",
        file_type="code",
    )
    G.add_node(
        "calc_interface",
        label="ICalculator",
        name="ICalculator",
        file_type="code",
    )
    G.add_edge("calc_class", "calc_interface", relation="implements")

    # get_code_skeleton
    skel_res = get_code_skeleton(str(src_file), root_dir=str(tmp_path))
    assert "Calculator" in skel_res["skeleton"]
    assert "return a + b" not in skel_res["skeleton"]

    # get_symbol_implementation
    sym_res = get_symbol_implementation("Calculator", graph=G, root_dir=str(tmp_path))
    assert sym_res["node_id"] == "calc_class"
    assert "return a + b" in sym_res["code"]

    # 1-hop related_types in find_definitions
    defs = find_definitions("Calculator", graph=G, root_dir=str(tmp_path))
    assert len(defs["definitions"]) == 1
    rel_types = defs["definitions"][0]["related_types"]
    assert len(rel_types) == 1
    assert rel_types[0]["id"] == "calc_interface"
    assert rel_types[0]["relation"] == "implements"


def test_format_rag_prompt():
    from graph_fy.retrieval import format_rag_prompt

    results = [
        {
            "node_id": "math_add",
            "label": "add()",
            "source_path": "math.py",
            "source_location": "L1",
            "score": 10.5,
            "skeleton": "def add(a: int, b: int) -> int:\n    ...",
            "related_types": [
                {
                    "node_id": "math_interface",
                    "relation": "implements",
                    "skeleton": "class IMath:\n    ...",
                }
            ],
        }
    ]

    prompt = format_rag_prompt(results, "how to add numbers", token_budget=500)
    assert "### Codebase Context for: how to add numbers" in prompt
    assert "#### add() (math.py:L1) [relevance: 10.5]" in prompt
    assert "def add(a: int, b: int) -> int:" in prompt
    assert "Related implements -> `math_interface`" in prompt
    assert "class IMath:" in prompt
