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
if ! "$TASK_PY" -c "import PySide6" >/dev/null 2>&1; then
  echo "PySide6가 필요합니다. 'python setup.py --desktop'로 설치한 뒤 다시 실행하세요." >&2
  exit 2
fi
exec "$TASK_PY" "$TASK_ROOT/desktop_qt.py" "$@"
