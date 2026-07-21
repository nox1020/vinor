# -*- coding: utf-8 -*-
"""ناظر قیف + رسدکننده — هم‌راستا با PROJECT_CHART."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock


class FunnelWatchTests(unittest.TestCase):
    def test_assess_raises_stage_on_visit_memory(self) -> None:
        from app.memory.interfaces import MEMORY_RELATIONSHIP, MemoryItem
        from app.memory.store import InMemoryMemoryStore
        from app.supervisor.funnel import STAGE_VISIT, assess_funnel

        store = InMemoryMemoryStore()
        store.upsert(
            MemoryItem(
                id="",
                user_key="09121112233",
                memory_type=MEMORY_RELATIONSHIP,
                key="visit:L-1",
                value="بازدید ثبت شد: L-1",
                score=0.9,
                metadata={"land_code": "L-1", "source": "sales_event"},
            )
        )
        with mock.patch("app.memory.di.make_memory_store", return_value=store):
            with mock.patch("app.supervisor.funnel._chat_last_activity", return_value=datetime.now(timezone.utc)):
                with mock.patch("app.supervisor.funnel._goal_stage", return_value=""):
                    snap = assess_funnel("09121112233", audience="public", stall_hours=48)
        self.assertEqual(snap.stage, STAGE_VISIT)
        self.assertEqual(snap.land_code, "L-1")
        self.assertGreaterEqual(snap.progress, 0.6)
        self.assertFalse(snap.signal_reach)

    def test_stalled_signals_reach_for_phone(self) -> None:
        from app.supervisor.funnel import assess_funnel

        old = datetime.now(timezone.utc) - timedelta(hours=40)
        with mock.patch("app.supervisor.funnel._memory_signals", return_value={
            "has_budget": True,
            "has_pref": True,
            "land_codes": ["X-1"],
            "has_visit": False,
            "has_deal": False,
            "has_reject": False,
            "last_event_at": "",
        }):
            with mock.patch("app.supervisor.funnel._goal_stage", return_value=""):
                with mock.patch("app.supervisor.funnel._chat_last_activity", return_value=old):
                    snap = assess_funnel("09121112233", audience="public", stall_hours=24)
        self.assertTrue(snap.stalled)
        self.assertTrue(snap.signal_reach)

    def test_guest_does_not_signal_reach(self) -> None:
        from app.supervisor.funnel import assess_funnel

        old = datetime.now(timezone.utc) - timedelta(hours=50)
        with mock.patch("app.supervisor.funnel._memory_signals", return_value={
            "has_budget": True,
            "has_pref": False,
            "land_codes": [],
            "has_visit": False,
            "has_deal": False,
            "has_reject": False,
            "last_event_at": "",
        }):
            with mock.patch("app.supervisor.funnel._goal_stage", return_value=""):
                with mock.patch("app.supervisor.funnel._chat_last_activity", return_value=old):
                    snap = assess_funnel("guest_abc", audience="public", stall_hours=24)
        self.assertFalse(snap.signal_reach)

    def test_buyer_reach_dry_run(self) -> None:
        from app.supervisor.funnel import FunnelSnapshot, save_snapshot
        from app.reach.service import run_buyer_reach_slot

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("app.supervisor.funnel._funnel_dir", return_value=tmp):
                snap = FunnelSnapshot(
                    user_key="09129998877",
                    audience="public",
                    stage="visit",
                    progress=0.7,
                    stalled=True,
                    idle_hours=30,
                    land_code="V-2",
                    next_hint="بازدید",
                    signal_reach=True,
                    updated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
                save_snapshot(snap)
                with mock.patch("app.reach.service._is_partner_phone", return_value=False):
                    with mock.patch("app.reach.service._state_path", return_value=tmp + "/state.json"):
                        out = run_buyer_reach_slot(slot_hour=10, dry_run=True)
        self.assertTrue(out.get("ok"))
        self.assertGreaterEqual(int(out.get("sent") or 0), 1)

    def test_goal_deal_type_exists(self) -> None:
        from app.goals.extractor import RuleGoalExtractor
        from app.goals.interfaces import GoalContext, GoalType

        goals = RuleGoalExtractor().extract(
            GoalContext(message="بیا معامله را ثبت کنیم", audience="partner")
        )
        types = {g.goal_type for g in goals}
        self.assertIn(GoalType.DEAL.value, types)


if __name__ == "__main__":
    unittest.main()
