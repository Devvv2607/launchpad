#!/usr/bin/env bash
# Run the API virtualenv's Python on any OS (Windows venvs use Scripts/, POSIX use bin/).
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
for py in "$root/api/.venv/bin/python" "$root/api/.venv/Scripts/python.exe"; do
  [ -x "$py" ] && exec "$py" "$@"
done
echo "api/.venv not found. Run 'make setup' first." >&2
exit 1
