from __future__ import annotations

import json
import unittest

from app import create_app


class AssetLinksRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = create_app()
        cls.client = cls.app.test_client()

    def test_assetlinks_200_json_no_redirect(self) -> None:
        resp = self.client.get("/.well-known/assetlinks.json", follow_redirects=False)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/json", (resp.content_type or "").lower())
        data = json.loads(resp.get_data(as_text=True))
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1)
        target = data[0]["target"]
        self.assertEqual(target["package_name"], "ir.vinor.app")
        fps = target["sha256_cert_fingerprints"]
        self.assertTrue(fps)
        self.assertNotIn("REPLACE_WITH", fps[0])
        self.assertRegex(fps[0], r"^[0-9A-F:]+$")

    def test_property_deep_link_public(self) -> None:
        resp = self.client.get("/property/TESTCODE", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        loc = resp.headers.get("Location") or ""
        self.assertIn("/express/partner/lands/TESTCODE", loc)


if __name__ == "__main__":
    unittest.main()
