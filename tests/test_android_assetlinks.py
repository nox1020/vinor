from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from app import create_app
from app.utils.deploy_meta import release_payload


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

        health = self.client.get("/healthz", follow_redirects=False)
        self.assertEqual(health.status_code, 204)
        self.assertEqual(health.get_data(), b"")

        repo = Path(__file__).resolve().parents[1]
        short = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "--short=7", "HEAD"],
            text=True,
        ).strip()
        full = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            text=True,
        ).strip()
        count = subprocess.check_output(
            ["git", "-C", str(repo), "rev-list", "--count", "HEAD"],
            text=True,
        ).strip()
        saved_env = os.environ.pop("VINOR_DEPLOYED_SHA", None)
        try:
            ver = self.client.get("/version", follow_redirects=False)
        finally:
            if saved_env is not None:
                os.environ["VINOR_DEPLOYED_SHA"] = saved_env
        self.assertEqual(ver.status_code, 200)
        self.assertIn("application/json", (ver.content_type or "").lower())
        self.assertEqual(ver.headers.get("Cache-Control"), "no-store")
        body = json.loads(ver.get_data(as_text=True))
        self.assertEqual(body["sha"], short)
        self.assertEqual(body.get("full_sha"), full)
        self.assertEqual(body["version"], count)
        self.assertRegex(body["sha"], r"^[0-9a-f]{7}$")

        try:
            self._assert_version_resolution_order()
        finally:
            if saved_env is not None:
                os.environ["VINOR_DEPLOYED_SHA"] = saved_env
            else:
                os.environ.pop("VINOR_DEPLOYED_SHA", None)

    def _assert_version_resolution_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inst = Path(tmp) / "instance"
            (inst / "deploy").mkdir(parents=True)
            bare = Path(tmp) / "bare"
            bare.mkdir()
            (bare / "version.txt").write_text("223\n", encoding="utf-8")
            os.environ.pop("VINOR_DEPLOYED_SHA", None)
            fallback = release_payload(inst, bare)
            self.assertEqual(fallback["sha"], "unknown")
            self.assertNotIn("full_sha", fallback)
            self.assertEqual(fallback["version"], "223")

            sha_file = inst / "deploy" / "current_sha"
            sha_file.write_text("  AbCdEf0123456789abcd\n", encoding="utf-8")
            from_file = release_payload(inst, bare)
            self.assertEqual(from_file["sha"], "abcdef0")
            self.assertEqual(from_file["full_sha"], "abcdef0123456789abcd")

            sha_file.write_text("nope\n", encoding="utf-8")
            os.utime(sha_file, (time.time() + 5, time.time() + 5))
            os.environ["VINOR_DEPLOYED_SHA"] = "1234567890abcdef"
            try:
                from_env = release_payload(inst, bare)
            finally:
                os.environ.pop("VINOR_DEPLOYED_SHA", None)
            self.assertEqual(from_env["sha"], "1234567")
            self.assertEqual(from_env["full_sha"], "1234567890abcdef")

            sha_file.write_text("deadbee\n", encoding="utf-8")
            os.utime(sha_file, (time.time() + 10, time.time() + 10))
            os.environ["VINOR_DEPLOYED_SHA"] = "ccccccc"
            try:
                file_beats_env = release_payload(inst, bare)
            finally:
                os.environ.pop("VINOR_DEPLOYED_SHA", None)
            self.assertEqual(file_beats_env["sha"], "deadbee")
            self.assertNotIn("full_sha", file_beats_env)

            sha_file.unlink()
            os.environ["VINOR_DEPLOYED_SHA"] = "abc"
            try:
                rejected = release_payload(inst, bare)
            finally:
                os.environ.pop("VINOR_DEPLOYED_SHA", None)
            self.assertEqual(rejected["sha"], "unknown")

            git_dir = bare / ".git"
            heads = git_dir / "refs" / "heads"
            heads.mkdir(parents=True)
            (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            loose = "0123456789abcdef0123456789abcdef01234567"
            (heads / "main").write_text(loose + "\n", encoding="utf-8")
            from_git = release_payload(inst, bare)
            self.assertEqual(from_git["sha"], loose[:7])
            self.assertEqual(from_git["full_sha"], loose)

            (heads / "main").unlink()
            packed = "abcdefabcdefabcdefabcdefabcdefabcdefabcd"
            (git_dir / "packed-refs").write_text(
                "# pack-refs with: peeled fully-peeled sorted\n"
                f"{packed} refs/heads/main\n"
                "^1111111111111111111111111111111111111111\n",
                encoding="utf-8",
            )
            self._bump_invalid_sha(sha_file, 15)
            from_pack = release_payload(inst, bare)
            self.assertEqual(from_pack["sha"], packed[:7])
            self.assertEqual(from_pack["full_sha"], packed)

            (git_dir / "packed-refs").unlink()
            detached = "fedcba9876543210fedcba9876543210fedcba98"
            (git_dir / "HEAD").write_text(detached + "\n", encoding="utf-8")
            self._bump_invalid_sha(sha_file, 20)
            from_head = release_payload(inst, bare)
            self.assertEqual(from_head["sha"], detached[:7])
            self.assertEqual(from_head["full_sha"], detached)

            linked = Path(tmp) / "linked"
            linked.mkdir()
            (linked / "version.txt").write_text("9\n", encoding="utf-8")
            pointed = Path(tmp) / "pointed.git"
            pointed.mkdir()
            (pointed / "HEAD").write_text(detached + "\n", encoding="utf-8")
            (linked / ".git").write_text(f"gitdir: {pointed}\n", encoding="utf-8")
            inst2 = Path(tmp) / "instance-link"
            inst2.mkdir()
            from_gitdir = release_payload(inst2, linked)
            self.assertEqual(from_gitdir["sha"], detached[:7])
            self.assertEqual(from_gitdir["full_sha"], detached)
            self.assertEqual(from_gitdir["version"], "9")

    @staticmethod
    def _bump_invalid_sha(sha_file: Path, offset: int) -> None:
        sha_file.write_text("nope\n", encoding="utf-8")
        stamp = time.time() + offset
        os.utime(sha_file, (stamp, stamp))

    def test_property_deep_link_public(self) -> None:
        resp = self.client.get("/property/TESTCODE", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        loc = resp.headers.get("Location") or ""
        self.assertIn("/express/partner/lands/TESTCODE", loc)


if __name__ == "__main__":
    unittest.main()
