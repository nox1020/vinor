#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""فشرده‌سازی تصاویر آپلودشده قبلی + ساخت واریانت نمایش.

پس از دیپلوی روی سرور (یک‌بار یا برای catch-up):
  python scripts/migrate_upload_images.py

همه فایل‌ها:
  python scripts/migrate_upload_images.py --force

فقط تست:
  python scripts/migrate_upload_images.py --dry-run --limit 5
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("VINOR_DISABLE_UPLOAD_IMAGE_MIGRATION", "1")

from app import create_app
from app.utils.upload_image_migration import migrate_all_upload_images


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate existing upload images")
    parser.add_argument("--force", action="store_true", help="Reprocess even if already migrated")
    parser.add_argument("--dry-run", action="store_true", help="List files without writing")
    parser.add_argument("--limit", type=int, default=None, help="Max files per run")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        result = migrate_all_upload_images(
            force=args.force,
            dry_run=args.dry_run,
            limit=args.limit,
        )
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
