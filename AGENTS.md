## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)

### Ponytail: Anti-Overengineering ("The best code is the code you never wrote")
- YAGNI: Challenge unnecessary abstractions, bloated wrappers, and speculative generality.
- Graph-First Code Reuse: Before creating any new helper function, model, or utility, query `graphify query "<concept>"` or inspect the knowledge graph. Reuse existing code first!
- Standard Library First: Always prefer native runtime/language standard library over adding third-party packages.
- Surgical Diffs: Keep code modifications minimal, focused, and precise. Never refactor surrounding untouched code.

### Caveman: Terse, High-Signal Output (Token Efficiency)
- Cut conversational filler, pleasantries, preambles, apologies, and unnecessary restatements.
- Output in dense, high-signal bullet points and concise technical fragments.
- Preserve 100% technical fidelity: exact file paths, line ranges, symbol names, shell commands, and code diffs must always be verbatim and uncompressed.

