# -*- coding: utf-8 -*-
"""تشخیص و بارگذاری خودکار پیکربندی Firebase (سرور + موبایل)."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Tuple

PACKAGE_NAME = "ir.vinor.app"

_APK_FIREBASE_FILES = (
    ("google-services.json", "google-services.json"),
    ("firebase-service-account.json", "firebase-service-account.json"),
)


def _data_dir(app) -> str:
    path = os.path.join(app.instance_path, "data")
    os.makedirs(path, exist_ok=True)
    return path


def _read_json_file(path: str) -> Optional[Dict[str, Any]]:
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


def _apk_app_dir(app=None) -> str:
    """مسیر apk/app — monorepo کناری یا VINOR_APK_APP_DIR."""
    override = (os.environ.get("VINOR_APK_APP_DIR") or "").strip()
    if override:
        return os.path.normpath(override)
    if app is not None:
        roots = [app.root_path]
    else:
        roots = [os.path.join(os.path.dirname(__file__), "..")]
    for root in roots:
        for rel in (os.path.join("..", "..", "apk", "app"), os.path.join("..", "apk", "app")):
            path = os.path.normpath(os.path.join(root, rel))
            if os.path.isdir(path):
                return path
    return os.path.normpath(os.path.join(roots[0], "..", "..", "apk", "app"))


def _sync_file_if_newer(src: str, dst: str) -> bool:
    """کپی src→dst اگر مقصد نباشد یا src جدیدتر باشد."""
    if not src or not os.path.isfile(src):
        return False
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if not os.path.isfile(dst) or os.path.getmtime(src) > os.path.getmtime(dst):
            import shutil
            shutil.copy2(src, dst)
            return True
    except Exception:
        pass
    return False


def _secrets_dir(app) -> str:
    """مسیر آپلود دستی روی سرور production (خارج از git)."""
    path = os.path.join(app.instance_path, "secrets")
    os.makedirs(path, exist_ok=True)
    return path


def sync_firebase_files(app) -> list[str]:
    """همگام‌سازی فایل‌های Firebase از apk/app، instance/secrets و env به instance/data."""
    data_dir = _data_dir(app)
    apk_dir = _apk_app_dir(app)
    secrets_dir = _secrets_dir(app)
    synced: list[str] = []

    for src_name, dst_name in _APK_FIREBASE_FILES:
        dst = os.path.join(data_dir, dst_name)
        for src in (
            os.path.join(apk_dir, src_name),
            os.path.join(secrets_dir, src_name),
        ):
            if _sync_file_if_newer(src, dst):
                synced.append(dst_name)

    gs_custom = (app.config.get("FCM_GOOGLE_SERVICES_FILE") or os.environ.get("FCM_GOOGLE_SERVICES_FILE") or "").strip()
    if gs_custom and gs_custom != os.path.join(data_dir, "google-services.json"):
        if _sync_file_if_newer(gs_custom, os.path.join(data_dir, "google-services.json")):
            synced.append("google-services.json")

    sa_custom = (app.config.get("FCM_SERVICE_ACCOUNT_FILE") or os.environ.get("FCM_SERVICE_ACCOUNT_FILE") or "").strip()
    sa_dst = os.path.join(data_dir, "firebase-service-account.json")
    if sa_custom and sa_custom != sa_dst and _sync_file_if_newer(sa_custom, sa_dst):
        synced.append("firebase-service-account.json")

    gac = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
    if gac and gac != sa_dst and _sync_file_if_newer(gac, sa_dst):
        synced.append("firebase-service-account.json")

    return synced


def _read_json_env(name: str) -> Optional[Dict[str, Any]]:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _parse_google_services(raw: Dict[str, Any]) -> Optional[Dict[str, str]]:
    if not raw:
        return None
    project_info = raw.get("project_info") if isinstance(raw.get("project_info"), dict) else {}
    project_id = str(project_info.get("project_id") or "").strip()
    sender_id = str(project_info.get("project_number") or "").strip()
    clients = raw.get("client") if isinstance(raw.get("client"), list) else []

    for client in clients:
        if not isinstance(client, dict):
            continue
        client_info = client.get("client_info") if isinstance(client.get("client_info"), dict) else {}
        android_info = client_info.get("android_client_info") if isinstance(client_info.get("android_client_info"), dict) else {}
        pkg = str(android_info.get("package_name") or "").strip()
        if pkg and pkg != PACKAGE_NAME:
            continue
        app_id = str(client_info.get("mobilesdk_app_id") or "").strip()
        api_key = ""
        api_keys = client.get("api_key") if isinstance(client.get("api_key"), list) else []
        for item in api_keys:
            if isinstance(item, dict) and item.get("current_key"):
                api_key = str(item.get("current_key") or "").strip()
                break
        if app_id and api_key and project_id and sender_id:
            return {
                "application_id": app_id,
                "api_key": api_key,
                "project_id": project_id,
                "gcm_sender_id": sender_id,
                "package_name": pkg or PACKAGE_NAME,
            }
    return None


def _load_mobile_config(app) -> Optional[Dict[str, str]]:
    custom = (app.config.get("FCM_GOOGLE_SERVICES_FILE") or os.environ.get("FCM_GOOGLE_SERVICES_FILE") or "").strip()
    apk_gs = os.path.join(_apk_app_dir(app), "google-services.json")
    candidates = [
        custom,
        os.path.join(_data_dir(app), "google-services.json"),
        os.path.join(_data_dir(app), "firebase", "google-services.json"),
        os.path.join(_secrets_dir(app), "google-services.json"),
        apk_gs,
    ]
    for path in candidates:
        if not path:
            continue
        parsed = _parse_google_services(_read_json_file(path) or {})
        if parsed:
            return parsed

    env_raw = _read_json_env("FCM_GOOGLE_SERVICES_JSON")
    if env_raw:
        mobile = env_raw.get("mobile") if isinstance(env_raw.get("mobile"), dict) else env_raw
        parsed = _parse_google_services(mobile if "client" in mobile else env_raw)
        if parsed:
            return parsed
        if all(mobile.get(k) for k in ("application_id", "api_key", "project_id", "gcm_sender_id")):
            return {
                "application_id": str(mobile["application_id"]),
                "api_key": str(mobile["api_key"]),
                "project_id": str(mobile["project_id"]),
                "gcm_sender_id": str(mobile["gcm_sender_id"]),
                "package_name": str(mobile.get("package_name") or PACKAGE_NAME),
            }

    bundle = _read_json_file(os.path.join(_data_dir(app), "firebase_config.json")) or {}
    mobile = bundle.get("mobile") if isinstance(bundle.get("mobile"), dict) else {}
    if all(mobile.get(k) for k in ("application_id", "api_key", "project_id", "gcm_sender_id")):
        return {
            "application_id": str(mobile["application_id"]),
            "api_key": str(mobile["api_key"]),
            "project_id": str(mobile["project_id"]),
            "gcm_sender_id": str(mobile["gcm_sender_id"]),
            "package_name": str(mobile.get("package_name") or PACKAGE_NAME),
        }
    return None


def _load_service_account(app) -> Optional[Dict[str, Any]]:
    custom = (app.config.get("FCM_SERVICE_ACCOUNT_FILE") or os.environ.get("FCM_SERVICE_ACCOUNT_FILE") or "").strip()
    gac = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
    apk_sa = os.path.join(_apk_app_dir(app), "firebase-service-account.json")
    candidates = [
        custom,
        gac,
        os.path.join(_data_dir(app), "firebase-service-account.json"),
        os.path.join(_data_dir(app), "firebase", "service-account.json"),
        os.path.join(_secrets_dir(app), "firebase-service-account.json"),
        apk_sa,
    ]
    for path in candidates:
        if not path:
            continue
        raw = _read_json_file(path)
        if raw and raw.get("type") == "service_account" and raw.get("private_key"):
            return raw

    env_raw = _read_json_env("FCM_SERVICE_ACCOUNT_JSON")
    if env_raw and env_raw.get("type") == "service_account":
        return env_raw

    bundle = _read_json_file(os.path.join(_data_dir(app), "firebase_config.json")) or {}
    sa = bundle.get("service_account") if isinstance(bundle.get("service_account"), dict) else {}
    if sa.get("type") == "service_account" and sa.get("private_key"):
        return sa
    return None


def get_firebase_status(app=None) -> Dict[str, Any]:
    from flask import current_app
    app = app or current_app
    mobile = _load_mobile_config(app)
    sa = _load_service_account(app)
    project_id = (
        (sa or {}).get("project_id")
        or (mobile or {}).get("project_id")
        or (app.config.get("FCM_PROJECT_ID") or os.environ.get("FCM_PROJECT_ID") or "")
    ).strip()
    return {
        "project_id": project_id or None,
        "mobile_ready": bool(mobile),
        "send_ready": bool(sa),
        "configured": bool(sa),
        "mobile": mobile,
    }


def get_mobile_config_public(app=None) -> Optional[Dict[str, str]]:
    status = get_firebase_status(app)
    mobile = status.get("mobile")
    if not mobile:
        return None
    return {
        "application_id": mobile["application_id"],
        "api_key": mobile["api_key"],
        "project_id": mobile["project_id"],
        "gcm_sender_id": mobile["gcm_sender_id"],
        "package_name": mobile.get("package_name") or PACKAGE_NAME,
    }


def get_service_account(app=None) -> Optional[Dict[str, Any]]:
    from flask import current_app
    app = app or current_app
    return _load_service_account(app)


def bootstrap_firebase(app) -> Dict[str, Any]:
    """اجرای bootstrap هنگام startup — مسیرها را خودکار پیدا می‌کند."""
    synced = sync_firebase_files(app)
    if synced:
        try:
            app.logger.info("Firebase auto-synced: %s", ", ".join(sorted(set(synced))))
        except Exception:
            pass

    status = get_firebase_status(app)
    mobile = status.get("mobile") or {}
    sa = get_service_account(app)

    if sa:
        app.config["FCM_SERVICE_ACCOUNT"] = sa
        app.config["FCM_PROJECT_ID"] = sa.get("project_id") or status.get("project_id")
    if mobile:
        app.config["FCM_MOBILE_CONFIG"] = mobile

    try:
        if status.get("send_ready") and status.get("mobile_ready"):
            app.logger.info(
                "Firebase auto-config OK (send+mobile) project=%s",
                status.get("project_id"),
            )
        elif status.get("send_ready"):
            app.logger.info(
                "Firebase send ready but mobile config missing — "
                "place google-services.json in instance/data/",
            )
        elif status.get("mobile_ready"):
            app.logger.warning(
                "Firebase mobile OK — برای ارسال push، firebase-service-account.json را "
                "در apk/app/ یا instance/data/ بگذارید (Firebase Console → Service accounts)",
            )
        else:
            app.logger.info(
                "Firebase not configured — google-services.json را در apk/app/ قرار دهید "
                "(یا firebase-service-account.json برای ارسال push)",
            )
    except Exception:
        pass
    return status
