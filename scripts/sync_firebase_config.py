#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""همگام‌سازی خودکار فایل‌های Firebase به instance/data (یک‌بار یا در deploy)."""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def main() -> int:
    sys.path.insert(0, ROOT)
    from app import create_app
    from app.services.firebase_config import get_firebase_status, sync_firebase_files

    app = create_app()
    with app.app_context():
        synced = sync_firebase_files(app)
        if synced:
            print("Synced:", ", ".join(sorted(set(synced))))
        else:
            print("Nothing to sync (sources missing or already up to date)")

        st = get_firebase_status()
        print(json.dumps({
            "mobile_ready": st.get("mobile_ready"),
            "send_ready": st.get("send_ready"),
            "project_id": st.get("project_id"),
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
