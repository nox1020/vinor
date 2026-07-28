# -*- coding: utf-8 -*-
"""تست‌های master toggle سیستم وکیل ملکی."""
from __future__ import annotations

import os
import unittest
from unittest import mock


class LawyerSystemMasterToggleTests(unittest.TestCase):
    def test_lawyer_system_defaults_off(self) -> None:
        from app.lawyer.config import default_lawyer_settings, lawyer_system_enabled

        self.assertFalse(default_lawyer_settings().get("enabled"))
        with mock.patch(
            "app.lawyer.config.lawyer_feature_enabled",
            return_value=True,
        ), mock.patch(
            "app.lawyer.config.get_lawyer_settings",
            return_value=default_lawyer_settings(),
        ):
            self.assertFalse(lawyer_system_enabled())

    def test_lawyer_system_on_when_settings_enabled(self) -> None:
        from app.lawyer.config import lawyer_system_enabled

        with mock.patch(
            "app.lawyer.config.lawyer_feature_enabled",
            return_value=True,
        ), mock.patch(
            "app.lawyer.config.get_lawyer_settings",
            return_value={"enabled": True},
        ):
            self.assertTrue(lawyer_system_enabled())

    def test_lawyer_system_off_when_settings_disabled(self) -> None:
        from app.lawyer.config import lawyer_system_enabled

        with mock.patch(
            "app.lawyer.config.lawyer_feature_enabled",
            return_value=True,
        ), mock.patch(
            "app.lawyer.config.get_lawyer_settings",
            return_value={"enabled": False},
        ):
            self.assertFalse(lawyer_system_enabled())

    def test_lawyer_system_off_when_env_disabled(self) -> None:
        from app.lawyer.config import lawyer_system_enabled

        with mock.patch(
            "app.lawyer.config.lawyer_feature_enabled",
            return_value=False,
        ):
            self.assertFalse(lawyer_system_enabled())

    def test_lawyer_enabled_alias_matches_system(self) -> None:
        from app.lawyer.config import lawyer_enabled, lawyer_system_enabled

        with mock.patch(
            "app.lawyer.config.lawyer_feature_enabled",
            return_value=True,
        ), mock.patch(
            "app.lawyer.config.get_lawyer_settings",
            return_value={"enabled": True},
        ):
            self.assertTrue(lawyer_enabled())
            self.assertEqual(lawyer_enabled(), lawyer_system_enabled())

    def test_missing_enabled_key_coerces_to_false(self) -> None:
        from app.lawyer.config import _coerce

        cfg = _coerce({"display_name": "وکیل"})
        self.assertFalse(cfg.get("enabled"))

    def test_stored_true_is_preserved(self) -> None:
        from app.lawyer.config import _coerce

        cfg = _coerce({"enabled": True, "display_name": "وکیل"})
        self.assertTrue(cfg.get("enabled"))

    def test_lawyer_thread_for_ui_hidden_when_off(self) -> None:
        from app.lawyer.service import lawyer_thread_for_ui

        with mock.patch("app.lawyer.service.lawyer_enabled", return_value=False):
            self.assertIsNone(lawyer_thread_for_ui("09121111111"))

    def test_ensure_lawyer_thread_noop_when_off(self) -> None:
        from app.lawyer.service import LAWYER_THREAD_ID, ensure_lawyer_thread

        with mock.patch("app.lawyer.service.lawyer_enabled", return_value=False), mock.patch(
            "app.ai.chat_store.load_user_record"
        ) as load_rec:
            tid = ensure_lawyer_thread("09121111111")
        self.assertEqual(tid, LAWYER_THREAD_ID)
        load_rec.assert_not_called()

    def test_env_feature_flag_defaults_on(self) -> None:
        from app.lawyer.config import lawyer_feature_enabled

        env = {k: v for k, v in os.environ.items() if k != "VINOR_LAWYER_ENABLED"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(lawyer_feature_enabled())


if __name__ == "__main__":
    unittest.main()
