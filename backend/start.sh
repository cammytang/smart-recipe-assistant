#!/bin/bash
set -euo pipefail

# Resolve paths relative to this script, regardless of the caller's directory.
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ ! -x .venv/bin/python ]]; then
    echo "未找到 backend/.venv/bin/python，请先创建后端虚拟环境并安装依赖。" >&2
    exit 1
fi

exec .venv/bin/python -m uvicorn main:app \
    --app-dir src \
    --host 127.0.0.1 \
    --port 8000 \
    --reload
