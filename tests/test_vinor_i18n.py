# -*- coding: utf-8 -*-
"""Vinor Control i18n — locale parity + presentation smoke."""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCALE_DIR = ROOT / "app" / "static" / "admin" / "locales"


def _flatten(obj, prefix=""):
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out |= _flatten(v, key)
            elif isinstance(v, list):
                out.add(key)
            else:
                out.add(key)
    return out


class LocaleParityTests(unittest.TestCase):
    def test_fa_en_key_parity(self) -> None:
        fa = json.loads((LOCALE_DIR / "fa.json").read_text(encoding="utf-8"))
        en = json.loads((LOCALE_DIR / "en.json").read_text(encoding="utf-8"))
        fa_keys = _flatten(fa)
        en_keys = _flatten(en)
        self.assertEqual(fa_keys, en_keys, msg=f"missing in fa: {en_keys-fa_keys} | missing in en: {fa_keys-en_keys}")

    def test_required_namespaces(self) -> None:
        en = json.loads((LOCALE_DIR / "en.json").read_text(encoding="utf-8"))
        for ns in ("meta", "common", "nav", "dashboard", "cmd", "login", "search_aliases"):
            self.assertIn(ns, en)


class I18nPresentationTests(unittest.TestCase):
    def setUp(self) -> None:
        from app import create_app

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def _login(self) -> None:
        with self.client.session_transaction() as sess:
            sess["logged_in"] = True
            sess["username"] = "admin"

    def test_shell_loads_i18n_assets(self) -> None:
        self._login()
        r = self.client.get("/admin/")
        self.assertEqual(r.status_code, 200)
        body = r.data.decode("utf-8", errors="ignore")
        self.assertIn("vinor-i18n.js", body)
        self.assertIn("data-i18n=", body)
        self.assertIn("vc-lang-switch", body)
        self.assertIn("admin/locales", body)

    def test_locale_files_served(self) -> None:
        for lang in ("fa", "en"):
            r = self.client.get(f"/static/admin/locales/{lang}.json")
            self.assertEqual(r.status_code, 200, msg=lang)
            data = json.loads(r.data.decode("utf-8"))
            self.assertEqual(data["nav"]["dashboard"] is not None, True)

    def test_i18n_js_exists(self) -> None:
        path = ROOT / "app" / "static" / "admin" / "vinor-i18n.js"
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertIn("formatCurrency", text)
        self.assertIn("formatDate", text)
        self.assertIn("searchMatch", text)


if __name__ == "__main__":
    unittest.main()
