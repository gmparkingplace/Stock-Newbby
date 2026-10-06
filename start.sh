#!/usr/bin/env bash
set -e
TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [ -n "${PYTHON:-}" ]; then
  TASK_PY="$PYTHON"
elif [ -x "$TASK_ROOT/.venv/bin/python" ]; then
  TASK_PY="$TASK_ROOT/.venv/bin/python"
else
  TASK_PY=python3
fi
exec "$TASK_PY" "$TASK_ROOT/run.py" "$@"
