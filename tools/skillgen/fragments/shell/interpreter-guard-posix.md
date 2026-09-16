```bash
if [ ! -f graph_fy_out/.graphify_python ]; then
    GRAPHIFY_BIN=$(which graph_fy 2>/dev/null || which graphify 2>/dev/null)
    if [ -n "$GRAPHIFY_BIN" ]; then
        PYTHON=$(head -1 "$GRAPHIFY_BIN" | tr -d '#!')
        case "$PYTHON" in *[!a-zA-Z0-9/_.@-]*) PYTHON="python3" ;; esac
    else
        PYTHON="python3"
    fi
    mkdir -p graph_fy_out
    "$PYTHON" -c "import sys; open('graph_fy_out/.graphify_python', 'w', encoding='utf-8').write(sys.executable)"
fi
```
