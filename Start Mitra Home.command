#!/usr/bin/env sh
# Double-click to start Mitra Home. First time on a Mac: right-click this file > Open > Open (Gatekeeper asks once).
cd "$(dirname "$0")"
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
    "$c" launch.py "$@"
    status=$?
    [ "$status" -ne 0 ] && { echo; echo "Press Return to close."; read -r _; }
    exit "$status"
  fi
done
echo
echo "Mitra Home needs Python 3.12 or newer, and this Mac does not have it yet."
echo "A download page opens now. Install Python, then double-click this file again."
open "https://www.python.org/downloads/" 2>/dev/null || xdg-open "https://www.python.org/downloads/" 2>/dev/null
echo "Press Return to close."; read -r _
