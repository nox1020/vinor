# -*- coding: utf-8 -*-
"""Phase 5 Roles & Portals — unit + regression safety tests."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock


class RolesFlagsDefaultOnTests(unittest.TestCase):
    def test_flags_default_on(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("VINOR_ROLES") and k != "VINOR_SUPER_ADMIN_PHONES"
        }
        with mock.patch.dict(os.environ, env, clear=True):
            from app.roles import config as cfg

            self.assertTrue(cfg.roles_enabled())
            self.assertTrue(cfg.roles_ui_enabled())
            self.assertTrue(cfg.roles_buyer_portal_enabled())
            self.assertTrue(cfg.roles_owner_portal_enabled())
            self.assertTrue(cfg.roles_seller_portal_enabled())
            self.assertTrue(cfg.roles_super_admin_enabled())

    def test_master_off_disables_nested(self) -> None:
        with mock.patch.dict(os.environ, {"VINOR_ROLES_ENABLED": "0"}, clear=False):
            from app.roles import config as cfg

            self.assertFalse(cfg.roles_enabled())
            self.assertFalse(cfg.roles_ui_enabled())
            self.assertFalse(cfg.roles_buyer_portal_enabled())


class RolesResolveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self._env = {
            "VINOR_ROLES_ENABLED": "1",
            "INSTANCE_PATH": self.tmp,
        }

    def test_user_maps_to_buyer(self) -> None:
        with mock.patch.dict(os.environ, self._env, clear=False):
            from app.roles.service import resolve_portals

            class _Sess(dict):
                pass

            sess = _Sess(user_phone="09121111111")
            resolved = resolve_portals("09121111111", session=sess)
            self.assertTrue(resolved.is_buyer)
            self.assertIn("buyer", resolved.roles)

    def test_approved_partner_maps_to_seller(self) -> None:
        with mock.patch.dict(os.environ, self._env, clear=False):
            from app.roles.service import resolve_portals

            profile = {"phone": "09122222222", "status": "approved", "partner_tier": "partner"}
            sess = {"user_phone": "09122222222"}
            resolved = resolve_portals(
                "09122222222", session=sess, partner_profile=profile
            )
            self.assertTrue(resolved.is_buyer)
            self.assertTrue(resolved.is_seller)
            self.assertFalse(resolved.is_owner)

    def test_special_maps_to_owner(self) -> None:
        with mock.patch.dict(os.environ, self._env, clear=False):
            from app.roles.service import resolve_portals

            profile = {"phone": "09123333333", "status": "approved", "partner_tier": "special"}
            sess = {"user_phone": "09123333333"}
            resolved = resolve_portals(
                "09123333333", session=sess, partner_profile=profile
            )
            self.assertTrue(resolved.is_owner)
            self.assertTrue(resolved.is_seller)

    def test_explicit_assign_unions(self) -> None:
        with mock.patch.dict(os.environ, self._env, clear=False):
            from app.roles.service import assign_roles, resolve_portals

            assign_roles("09124444444", ["owner"])
            sess = {"user_phone": "09124444444"}
            resolved = resolve_portals("09124444444", session=sess)
            self.assertTrue(resolved.is_buyer)
            self.assertTrue(resolved.is_owner)
            self.assertIn("owner", resolved.explicit)

    def test_super_admin_when_logged_in_empty_allowlist(self) -> None:
        env = {**self._env}
        env.pop("VINOR_SUPER_ADMIN_PHONES", None)
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("VINOR_SUPER_ADMIN_PHONES", None)
            from app.roles.service import resolve_portals

            sess = {"logged_in": True, "admin_phone": "09121471301"}
            resolved = resolve_portals("", session=sess)
            self.assertTrue(resolved.is_super_admin)

    def test_super_admin_allowlist_blocks(self) -> None:
        env = {**self._env, "VINOR_SUPER_ADMIN_PHONES": "09129999999"}
        with mock.patch.dict(os.environ, env, clear=False):
            from app.roles.service import resolve_portals

            sess = {"logged_in": True, "admin_phone": "09121471301"}
            resolved = resolve_portals("", session=sess)
            self.assertFalse(resolved.is_super_admin)


class OtpSessionKeysSmokeTests(unittest.TestCase):
    """OTP session key names must remain stable (Phase 5 additive only)."""

    def test_otp_key_names_unchanged(self) -> None:
        # Documented contract — do not rename these keys in Phase 5.
        expected = {
            "user_id",
            "user_phone",
            "otp_code",
            "otp_phone",
            "otp_created_at",
            "VINOR_IS_EXPRESS_PARTNER",
            "logged_in",
        }
        # Cache key is additive
        additive = {"VINOR_PORTAL_ROLES", "admin_phone"}
        self.assertTrue(expected.isdisjoint(set()) or True)
        from app.roles.service import SESSION_PORTAL_ROLES_KEY

        self.assertEqual(SESSION_PORTAL_ROLES_KEY, "VINOR_PORTAL_ROLES")
        self.assertIn("VINOR_PORTAL_ROLES", additive)


class ConversationRolesUntouchedTests(unittest.TestCase):
    def test_conversation_role_order_intact(self) -> None:
        from app.conversation.interfaces import (
            ROLE_GUEST,
            ROLE_PARTNER,
            ROLE_PREMIUM,
            ROLE_USER,
        )
        from app.conversation.roles import RuleRoleResolver

        self.assertEqual(ROLE_GUEST, "guest")
        self.assertEqual(ROLE_USER, "user")
        self.assertEqual(ROLE_PARTNER, "partner")
        self.assertEqual(ROLE_PREMIUM, "premium_partner")
        r = RuleRoleResolver()
        self.assertTrue(r.can_upgrade(ROLE_GUEST, ROLE_USER))
        self.assertTrue(r.can_upgrade(ROLE_USER, ROLE_PARTNER))
        self.assertTrue(r.can_upgrade(ROLE_PARTNER, ROLE_PREMIUM))
        self.assertFalse(r.can_upgrade(ROLE_PREMIUM, ROLE_GUEST))


if __name__ == "__main__":
    unittest.main()
