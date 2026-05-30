# -*- coding: utf-8 -*-
"""تشخیص و بارگذاری خودکار پیکربندی Firebase (سرور + موبایل)."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Tuple

PACKAGE_NAME = "ir.vinor.app"


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
    candidates = [
        custom,
        os.path.join(_data_dir(app), "google-services.json"),
        os.path.join(_data_dir(app), "firebase", "google-services.json"),
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
    candidates = [
        custom,
        gac,
        os.path.join(_data_dir(app), "firebase-service-account.json"),
        os.path.join(_data_dir(app), "firebase", "service-account.json"),
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
    import shutil

    data_dir = _data_dir(app)
    target_gs = os.path.join(data_dir, "google-services.json")
    if not os.path.isfile(target_gs):
        candidates = [
            (app.config.get("FCM_GOOGLE_SERVICES_FILE") or "").strip(),
            os.path.normpath(os.path.join(app.root_path, "..", "..", "apk", "app", "google-services.json")),
            os.path.normpath(os.path.join(app.root_path, "..", "apk", "app", "google-services.json")),
        ]
        for src in candidates:
            if src and os.path.isfile(src):
                try:
                    shutil.copy2(src, target_gs)
                    try:
                        app.logger.info("Auto-synced google-services.json from %s", src)
                    except Exception:
                        pass
                    break
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
                "Firebase mobile config found but service account missing — "
                "place firebase-service-account.json in instance/data/",
            )
        else:
            app.logger.info(
                "Firebase not configured — drop google-services.json and "
                "firebase-service-account.json into instance/data/ (or set env JSON)",
            )
    except Exception:
        pass
    return status
