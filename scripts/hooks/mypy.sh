#!/usr/bin/env bash
# Type-check whole packages (mypy needs the full import graph, not just staged files).
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
py="$root/scripts/hooks/venv-python.sh"
(cd "$root/api" && "$py" -m mypy)
(cd "$root/worker" && "$py" -m mypy)
