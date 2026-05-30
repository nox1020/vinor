#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""همگام‌سازی خودکار فایل‌های Firebase به instance/data (یک‌بار یا در deploy)."""
from __future__ import annotations

import json
import os
import shutil
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INSTANCE_DATA = os.path.join(ROOT, "instance", "data")
APK_GS = os.path.join(ROOT, "..", "apk", "app", "google-services.json")
TARGET_GS = os.path.join(INSTANCE_DATA, "google-services.json")
TARGET_SA = os.path.join(INSTANCE_DATA, "firebase-service-account.json")
SRC_SA = os.path.join(INSTANCE_DATA, "firebase-service-account.json.example")


def main() -> int:
    os.makedirs(INSTANCE_DATA, exist_ok=True)
    copied = []

    if os.path.isfile(APK_GS) and not os.path.isfile(TARGET_GS):
        shutil.copy2(APK_GS, TARGET_GS)
        copied.append("google-services.json")

    # env override for service account path
    sa_src = (os.environ.get("FCM_SERVICE_ACCOUNT_FILE") or "").strip()
    if sa_src and os.path.isfile(sa_src) and sa_src != TARGET_SA:
        shutil.copy2(sa_src, TARGET_SA)
        copied.append("firebase-service-account.json")

    if copied:
        print("Synced:", ", ".join(copied))
    else:
        print("Nothing to sync (targets already exist or sources missing)")

    # validate parse
    try:
        sys.path.insert(0, ROOT)
        from app import create_app
        app = create_app()
        with app.app_context():
            from app.services.firebase_config import get_firebase_status
            st = get_firebase_status()
            print(json.dumps({
                "mobile_ready": st.get("mobile_ready"),
                "send_ready": st.get("send_ready"),
                "project_id": st.get("project_id"),
            }, ensure_ascii=False))
    except Exception as e:
        print("Validate warning:", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
