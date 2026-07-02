#!/usr/bin/env bash
# یک‌بار روی سرور production: آپلود فایل‌ها به instance/secrets/ سپس اجرای این اسکریپت
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p instance/secrets instance/data
python scripts/sync_firebase_config.py
touch tmp/restart.txt 2>/dev/null || true
