```bash
# Detect the correct Python interpreter (handles uv tool, pipx, venv, system installs)
PYTHON=""
GRAPHIFY_BIN=$(which graph_fy 2>/dev/null || which graphify 2>/dev/null)
# 1. uv tool installs — most reliable on modern Mac/Linux
if [ -z "$PYTHON" ] && command -v uv >/dev/null 2>&1; then
    _UV_PY=$(uv tool run --from graphifyy python -c "import sys; print(sys.executable)" 2>/dev/null)
    if [ -n "$_UV_PY" ]; then PYTHON="$_UV_PY"; fi
fi
# 2. Read shebang from graph_fy binary (pipx and direct pip installs)
if [ -z "$PYTHON" ] && [ -n "$GRAPHIFY_BIN" ]; then
    _SHEBANG=$(head -1 "$GRAPHIFY_BIN" | tr -d '#!')
    case "$_SHEBANG" in
        *[!a-zA-Z0-9/_.@-]*) ;;
        *) "$_SHEBANG" -c "import graph_fy" 2>/dev/null && PYTHON="$_SHEBANG" ;;
    esac
fi
# 3. Fall back to python3
if [ -z "$PYTHON" ]; then PYTHON="python3"; fi
if ! "$PYTHON" -c "import graph_fy" 2>/dev/null; then
    if command -v uv >/dev/null 2>&1; then
        uv tool install --upgrade graphifyy -q 2>&1 | tail -3
        _UV_PY=$(uv tool run --from graphifyy python -c "import sys; print(sys.executable)" 2>/dev/null)
        if [ -n "$_UV_PY" ]; then PYTHON="$_UV_PY"; fi
    else
        "$PYTHON" -m pip install graphifyy -q 2>/dev/null \
          || "$PYTHON" -m pip install graphifyy -q --break-system-packages 2>&1 | tail -3
    fi
fi
# Write interpreter path for all subsequent steps (persists across invocations)
mkdir -p graph_fy_out
"$PYTHON" -c "import sys; open('graph_fy_out/.graphify_python', 'w', encoding='utf-8').write(sys.executable)"
# Save scan root so `graph_fy update` (no args) knows where to look next time.
# INPUT_PATH is passed through a quoted heredoc, never substituted into the
# command line itself: a bare `cd INPUT_PATH` (or an unquoted heredoc, which
# still expands $()/backticks in its body) would let a malicious path execute
# as shell code the moment this line runs.
"$PYTHON" -c "import os, sys; out_path = os.path.abspath('graph_fy_out/.graphify_root'); os.chdir(sys.stdin.readline().rstrip('\n')); open(out_path, 'w', encoding='utf-8').write(os.getcwd())" <<'GRAPHIFY_ROOT_EOF' || exit 1
INPUT_PATH
GRAPHIFY_ROOT_EOF
# Ensure graph_fy_out/ is in .gitignore if in a git repository
if [ -d .git ] || git rev-parse --git-dir >/dev/null 2>&1; then
    if [ ! -f .gitignore ] || ! grep -q "graph_fy_out" .gitignore 2>/dev/null; then
        printf "\n# graph_fy output\ngraph_fy_out/\ngraph_fy_out/\n.graphify_*\n.graphify_python\n.graphify_root\n" >> .gitignore
    fi
fi
```

If the import succeeds, print nothing and move straight to Step 2.

**In every subsequent bash block, replace `python3` with `$(cat graph_fy_out/.graphify_python)` to use the correct interpreter.**
