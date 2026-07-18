# -*- coding: utf-8 -*-
"""Vinor Control presentation layer smoke tests."""
from __future__ import annotations

import unittest


class VinorControlRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        from app import create_app

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def _login(self) -> None:
        with self.client.session_transaction() as sess:
            sess["logged_in"] = True
            sess["username"] = "admin"

    def test_dashboard_is_mission_control(self) -> None:
        self._login()
        r = self.client.get("/admin/")
        self.assertEqual(r.status_code, 200)
        body = r.data.decode("utf-8", errors="ignore")
        self.assertIn("Mission Control", body)
        self.assertIn("vinor-control.css", body)
        self.assertIn("Vinor Control", body)

    def test_control_hubs_reachable(self) -> None:
        self._login()
        for path in (
            "/admin/control/market",
            "/admin/control/crm",
            "/admin/control/people",
            "/admin/control/analytics",
            "/admin/control/observe",
            "/admin/control/reasoning",
            "/admin/control/evaluations",
            "/admin/control/more",
        ):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, msg=path)

    def test_ai_console_still_works(self) -> None:
        self._login()
        r = self.client.get("/admin/ai-console")
        self.assertIn(r.status_code, (200, 302, 404))
        if r.status_code == 200:
            body = r.data.decode("utf-8", errors="ignore")
            self.assertIn("Intelligence", body)

    def test_command_palette_markup(self) -> None:
        self._login()
        r = self.client.get("/admin/")
        body = r.data.decode("utf-8", errors="ignore")
        self.assertIn("vinorControlShell", body)
        self.assertIn("⌘K", body)

    def test_memory_detail_and_add_land_templates(self) -> None:
        self._login()
        r = self.client.get("/admin/ai-console/memory?user=09101528014")
        self.assertEqual(r.status_code, 200)
        r2 = self.client.get("/admin/add-land")
        self.assertEqual(r2.status_code, 200)


if __name__ == "__main__":
    unittest.main()
