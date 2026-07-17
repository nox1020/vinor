#!/usr/bin/env bash
# One-shot production sync for App Links (run on server as vinorir).
set -euo pipefail
cd "${HOME}/public_html/vinor"
git fetch --all --prune
git reset --hard origin/main
mkdir -p tmp && touch tmp/restart.txt
# Verify Digital Asset Links endpoint
curl -sI "https://vinor.ir/.well-known/assetlinks.json" | head -n 15
curl -s "https://vinor.ir/.well-known/assetlinks.json"
echo
