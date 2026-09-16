## graph_fy

This project has a knowledge graph at graph_fy_out/ with god nodes, community structure, and cross-file relationships extracted deterministically from code AST.

Core Rules (Pre-Agent Briefing, Zero Fragmentation):
- Pre-Agent Analysis Briefing: Before asking frontier models or planning changes, run `graph_fy context "<task>"` (or MCP tool `get_agent_context`). Generates a prompt-cache-friendly architectural briefing with Mermaid diagrams, Tier 1 AST skeletons, execution flow, co-changes, and test targets.
- Never explore the codebase in a fragmented, piecemeal fashion. Use graph_fy_out/ as your holistic architectural map to understand how components, services, and subsystems connect.
- Code is the single source of truth: every node and edge in graph_fy_out/ reflects deterministic AST extraction (@ 1.0 confidence). Use the graph to navigate directly to the exact `source_location` (file:line) in code.
- For codebase questions, first run `graph_fy query "<question>"` when graph_fy_out/graph.json exists. Use `graph_fy path "<A>" "<B>"` for relationships and `graph_fy explain "<concept>"` for focused concepts. These return a scoped, connected subgraph rather than noisy fragmented file reads.
- If graph_fy_out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graph_fy_out/GRAPH_REPORT.md for overall architecture, god nodes, and community boundaries.
- After modifying code, immediately run `graph_fy update .` to keep the graph synchronized with code truth (AST-only, zero API cost).

Ponytail: Anti-Overengineering ("The best code is the code you never wrote")
- YAGNI: Challenge unnecessary abstractions, bloated wrappers, and speculative generality.
- Graph-First Code Reuse: Before creating any new helper function, model, or utility, query `graph_fy query "<concept>"` or inspect the knowledge graph. Reuse existing code first!
- Standard Library First: Always prefer native runtime/language standard library over adding third-party packages.
- Surgical Diffs: Keep code modifications minimal, focused, and precise. Never refactor surrounding untouched code.

Caveman: Terse, High-Signal Output (Token Efficiency)
- Cut conversational filler, pleasantries, preambles, apologies, and unnecessary restatements.
- Output in dense, high-signal bullet points and concise technical fragments.
- Preserve 100% technical fidelity: exact file paths, line ranges, symbol names, shell commands, and code diffs must always be verbatim and uncompressed.
