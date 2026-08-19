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

    def test_dashboard_loads(self) -> None:
        self._login()
        r = self.client.get("/admin/")
        self.assertEqual(r.status_code, 200)
        body = r.data.decode("utf-8", errors="ignore")
        self.assertIn("adminOpsDashPage", body)
        self.assertNotIn("opsDashChatOpen", body)
        self.assertIn("vinor-control.css", body)

    def test_control_hubs_redirect_to_ops_home(self) -> None:
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
            self.assertIn(r.status_code, (301, 302), msg=path)
            self.assertIn("/admin", r.location or "")

    def test_ai_console_redirects_to_monitor(self) -> None:
        self._login()
        r = self.client.get("/admin/ai-console", follow_redirects=False)
        self.assertIn(r.status_code, (302, 404))
        if r.status_code == 302:
            r2 = self.client.get(r.location)
            self.assertEqual(r2.status_code, 200)
            body = r2.data.decode("utf-8", errors="ignore")
            self.assertIn("Live Monitor", body)

    def test_command_palette_markup(self) -> None:
        self._login()
        r = self.client.get("/admin/")
        body = r.data.decode("utf-8", errors="ignore")
        self.assertIn("vinorControlShell", body)
        self.assertIn("⌘K", body)

    def test_legacy_ai_console_pages_redirect(self) -> None:
        self._login()
        for path in (
            "/admin/ai-console/memory?user=09101528014",
            "/admin/ai-console/agents",
            "/admin/ai-console/workflows",
        ):
            r = self.client.get(path, follow_redirects=False)
            self.assertIn(r.status_code, (301, 302, 404), msg=path)

    def test_add_land_template_still_reachable(self) -> None:
        self._login()
        r = self.client.get("/admin/add-land")
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
