# -*- coding: utf-8 -*-
"""Phase 7 Hardening — unit + regression safety tests."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock


class HardeningFlagsDefaultOnTests(unittest.TestCase):
    def test_flags_default_on(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("VINOR_HARDENING")
        }
        with mock.patch.dict(os.environ, env, clear=True):
            from app.hardening import config as cfg

            self.assertTrue(cfg.hardening_enabled())
            self.assertTrue(cfg.hardening_audit_enabled())
            self.assertTrue(cfg.hardening_audit_required())
            self.assertTrue(cfg.hardening_rbac_enabled())
            self.assertTrue(cfg.hardening_os_kpis_enabled())
            self.assertTrue(cfg.hardening_soft_cleanup_enabled())
            self.assertTrue(cfg.hardening_ui_enabled())


class AdminAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self._env = {
            "INSTANCE_PATH": self.tmp,
            "VINOR_HARDENING_ENABLED": "1",
            "VINOR_HARDENING_AUDIT_ENABLED": "1",
            "VINOR_FOUNDATION_ENABLED": "1",
            "VINOR_ACTIVITY_STORE_ENABLED": "1",
            "VINOR_TIMELINE_STORE_ENABLED": "1",
        }

    def test_record_admin_audit_writes(self) -> None:
        with mock.patch.dict(os.environ, self._env, clear=False):
            from app.hardening.audit import record_admin_audit
            from app.hardening.service import list_admin_audit

            act = record_admin_audit(
                action="admin_test_event",
                actor_key="09120000000",
                entity_type="commission",
                entity_id="1",
                summary="test audit",
            )
            self.assertIsNotNone(act)
            rows = list_admin_audit(limit=20)
            actions = [r.get("action") for r in rows]
            self.assertIn("admin_test_event", actions)


class RbacPermissionTests(unittest.TestCase):
    def test_base_admin_lacks_super(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "VINOR_HARDENING_ENABLED": "1",
                "VINOR_HARDENING_RBAC_ENABLED": "1",
                "VINOR_ROLES_ENABLED": "1",
                "VINOR_ROLES_SUPER_ADMIN_ENABLED": "1",
            },
            clear=False,
        ):
            from app.hardening.permissions import (
                PERM_FINANCE,
                PERM_SUPER,
                has_permission,
                list_permissions,
            )

            sess = {"logged_in": True, "admin_phone": "09121111111"}
            with mock.patch(
                "app.roles.service.is_super_admin",
                return_value=False,
            ):
                perms = list_permissions(session=sess)
                self.assertIn(PERM_FINANCE, perms)
                self.assertNotIn(PERM_SUPER, perms)
                self.assertTrue(has_permission(PERM_FINANCE, session=sess))
                self.assertFalse(has_permission(PERM_SUPER, session=sess))

    def test_super_admin_has_super(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "VINOR_HARDENING_ENABLED": "1",
                "VINOR_HARDENING_RBAC_ENABLED": "1",
            },
            clear=False,
        ):
            from app.hardening.permissions import PERM_SUPER, has_permission, list_permissions

            sess = {"logged_in": True}
            with mock.patch(
                "app.roles.service.is_super_admin",
                return_value=True,
            ):
                self.assertIn(PERM_SUPER, list_permissions(session=sess))
                self.assertTrue(has_permission(PERM_SUPER, session=sess))


class OsKpisTests(unittest.TestCase):
    def test_kpis_keys_present_empty(self) -> None:
        tmp = tempfile.mkdtemp()
        with mock.patch.dict(
            os.environ,
            {
                "INSTANCE_PATH": tmp,
                "VINOR_HARDENING_ENABLED": "1",
                "VINOR_HARDENING_OS_KPIS_ENABLED": "1",
            },
            clear=False,
        ):
            from app.hardening.os_kpis import compute_os_kpis

            kpis = compute_os_kpis()
            for key in (
                "visit_call_rate",
                "visit_booking_rate",
                "visit_to_deal_rate",
                "deal_close_rate",
                "sales_volume_count",
                "sales_volume_amount",
            ):
                self.assertIn(key, kpis)

    def test_bi_obs_merges_os_keys(self) -> None:
        tmp = tempfile.mkdtemp()
        with mock.patch.dict(
            os.environ,
            {
                "INSTANCE_PATH": tmp,
                "VINOR_HARDENING_ENABLED": "1",
                "VINOR_HARDENING_OS_KPIS_ENABLED": "1",
                "VINOR_BI_ENABLED": "0",
            },
            clear=False,
        ):
            from app.business_intelligence.service import get_bi_obs

            obs = get_bi_obs()
            self.assertIn("os_visit_call_rate", obs)
            self.assertIn("os_deal_close_rate", obs)


class SoftCleanupTests(unittest.TestCase):
    def test_deprecate_registry_retains_primary(self) -> None:
        from app.hardening.deprecate import RETAINED_PRIMARY_PATHS, deprecate_registry

        reg = deprecate_registry()
        self.assertFalse(reg["hard_delete"])
        for name in (
            "propose_deal",
            "mark_in_transaction",
            "express_commissions",
            "partner_withdrawals",
        ):
            self.assertIn(name, RETAINED_PRIMARY_PATHS)
            self.assertIn(name, reg["retained_primary"])

    def test_propose_deal_still_in_schema(self) -> None:
        from app.ai.agent_tools import tools_schema_for_voice
        from app.ai.audience import VOICE_PARTNER

        names = [t["function"]["name"] for t in tools_schema_for_voice(VOICE_PARTNER)]
        self.assertIn("propose_deal", names)
        self.assertIn("propose_release_deal", names)


if __name__ == "__main__":
    unittest.main()
