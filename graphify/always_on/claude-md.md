## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships extracted deterministically from code AST.

Core Rules (Code is Source of Truth, Zero Fragmentation):
- Never explore the codebase in a fragmented, piecemeal fashion. Use graphify-out/ as your holistic architectural map to understand how components, services, and subsystems connect.
- Code is the single source of truth: every node and edge in graphify-out/ reflects deterministic AST extraction (@ 1.0 confidence). Use the graph to navigate directly to the exact `source_location` (file:line) in code.
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for dependency chains and `graphify explain "<concept>"` for focused concepts. These return a scoped, connected subgraph rather than noisy fragmented file reads.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md for overall architecture, god nodes, and community boundaries.
- After modifying code, immediately run `graphify update .` to keep the graph synchronized with code truth (AST-only, zero API cost).

Ponytail: Anti-Overengineering ("The best code is the code you never wrote")
- YAGNI: Challenge unnecessary abstractions, bloated wrappers, and speculative generality.
- Graph-First Code Reuse: Before creating any new helper function, model, or utility, query `graphify query "<concept>"` or inspect the knowledge graph. Reuse existing code first!
- Standard Library First: Always prefer native runtime/language standard library over adding third-party packages.
- Surgical Diffs: Keep code modifications minimal, focused, and precise. Never refactor surrounding untouched code.

Caveman: Terse, High-Signal Output (Token Efficiency)
- Cut conversational filler, pleasantries, preambles, apologies, and unnecessary restatements.
- Output in dense, high-signal bullet points and concise technical fragments.
- Preserve 100% technical fidelity: exact file paths, line ranges, symbol names, shell commands, and code diffs must always be verbatim and uncompressed.
