#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تست ارسال FCM از روی سرور — خطای دقیق Firebase را نشان می‌دهد."""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def main() -> int:
    sys.path.insert(0, ROOT)
    from app import create_app
    from app.services.firebase_config import get_firebase_status
    from app.services.fcm_push import send_fcm_to_token
    from app.services.fcm_tokens import all_registered

    app = create_app()
    with app.app_context():
        st = get_firebase_status()
        print("status:", json.dumps({
            "mobile_ready": st.get("mobile_ready"),
            "send_ready": st.get("send_ready"),
            "project_id": st.get("project_id"),
        }, ensure_ascii=False))

        data = all_registered()
        if not data:
            print("no tokens in fcm_tokens.json (login in APK first)")
            return 1

        phone, items = next(iter(data.items()))
        token = (items[0].get("token") or "").strip()
        if not token:
            print("no valid token found")
            return 1
        print(f"testing phone={phone} token={token[:16]}…")

        res = send_fcm_to_token(token, title="تست وینور", body="اگر این را دیدید FCM کار می‌کند")
        print("result:", json.dumps(res, ensure_ascii=False)[:1200])
        return 0 if res.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
