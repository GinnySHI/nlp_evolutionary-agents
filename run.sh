#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  printf '%s\n' 'Create a Python 3.11+ environment first:' '  python3.12 -m venv .venv' '  .venv/bin/python -m pip install -e ".[dev]"' >&2
  exit 1
fi
if [[ $# -eq 0 ]]; then
  exec .venv/bin/python -m evoagents --help
fi
exec .venv/bin/python -m evoagents "$@"
