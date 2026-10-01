#!/usr/bin/env bash
# Usage: web.sh <eslint|prettier> <files under web/...>
set -euo pipefail
tool="$1"; shift
root="$(git rev-parse --show-toplevel)"
files=()
for f in "$@"; do files+=("${f#web/}"); done
[ ${#files[@]} -eq 0 ] && exit 0
cd "$root/web"
case "$tool" in
  eslint) npx --no-install eslint --max-warnings=0 "${files[@]}" ;;
  prettier) npx --no-install prettier --check --ignore-unknown "${files[@]}" ;;
esac
