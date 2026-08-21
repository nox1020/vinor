# -*- coding: utf-8 -*-
"""Unit tests for APK versionCode payload and update visibility."""
from __future__ import annotations

from app.utils.apk_meta import version_code_from_name
from app.utils.apk_version import (
    android_apk_version_payload,
    parse_vinor_app_version_code,
    should_show_apk_update,
)


class _Req:
    def __init__(self, headers: dict):
        self.headers = headers


def test_version_code_from_name_matches_gradle():
    assert version_code_from_name("1.0.4") == 10004
    assert version_code_from_name("1.0.272") == 10272
    assert version_code_from_name("1.0.273") == 10273


def test_payload_includes_code_and_name():
    payload = android_apk_version_payload(
        {
            "android_apk_version": "1.0.273",
            "android_apk_version_code": 10273,
            "android_apk_min_supported_version_code": 0,
        }
    )
    assert payload["android_apk_version"] == "1.0.273"
    assert payload["android_apk_version_name"] == "1.0.273"
    assert payload["android_apk_version_code"] == 10273
    assert payload["android_apk_min_supported_version_code"] == 0


def test_payload_falls_back_to_name_formula():
    payload = android_apk_version_payload({"android_apk_version": "1.0.272"})
    assert payload["android_apk_version_code"] == 10272


def test_should_show_uses_version_code_over_name():
    req = _Req(
        {
            "X-Vinor-App-Version": "1.0.9",
            "X-Vinor-App-Version-Code": "4000",
            "User-Agent": "VinorApp/WebViewOnly/1.0.9",
        }
    )
    assert should_show_apk_update(
        "1.0.1",
        apk_url="/uploads/apk/x.apk",
        req=req,
        server_version_code=5000,
    )
    assert not should_show_apk_update(
        "1.0.9",
        apk_url="/uploads/apk/x.apk",
        req=req,
        server_version_code=4000,
    )


def test_should_show_false_for_browser():
    req = _Req({"User-Agent": "Mozilla/5.0"})
    assert not should_show_apk_update(
        "1.0.273",
        apk_url="/d/vinor-1.0.273.apk",
        req=req,
        server_version_code=10273,
    )


def test_parse_version_code_header():
    req = _Req({"X-Vinor-App-Version-Code": "10272"})
    assert parse_vinor_app_version_code(req) == 10272
    assert parse_vinor_app_version_code(header_code="12") == 12
    assert parse_vinor_app_version_code(_Req({})) == 0
