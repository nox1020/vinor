# -*- coding: utf-8 -*-
"""E2E-style checks: visit → deal via chat tools, no land_code ask, living cards."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock


PHONE = "09121111111"
LAND = "20251101112258"
THREAD = "thread-mission-1"


def _patch_ai_data(tmp: str):
    root = Path(tmp)

    def _ai_data_file(*parts):
        return str(root.joinpath(*parts))

    return mock.patch("app.ai.chat_store.ai_data_file", side_effect=_ai_data_file), mock.patch(
        "app.ai.paths.ai_data_file", side_effect=_ai_data_file
    ), mock.patch(
        "app.ai.agent_tools.ai_data_file", side_effect=_ai_data_file
    )


class ChatOpsLandFocusTests(unittest.TestCase):
    def test_resolve_uses_thread_focus_without_mission(self) -> None:
        from app.ai.agent_tools import resolve_conversation_land_code

        with mock.patch(
            "app.ai.agent_tools._active_mission_land_code", return_value=""
        ), mock.patch(
            "app.ai.agent_tools._thread_focus_land_code", return_value=LAND
        ), mock.patch(
            "app.ai.agent_tools._active_assignment_land_codes", return_value=[]
        ), mock.patch(
            "app.ai.agent_tools._load_visit_draft", return_value={}
        ), mock.patch(
            "app.ai.agent_tools._land_code_from_user_message", return_value=""
        ):
            self.assertEqual(resolve_conversation_land_code(PHONE), LAND)

    def test_run_tool_injects_land_code(self) -> None:
        from app.ai.agent_tools import TOOL_VISIT, run_tool

        captured: dict = {}

        def fake_propose(args, *, phone):
            captured["args"] = dict(args)
            return {
                "ok": False,
                "model_result": {
                    "ok": False,
                    "missing": ["customer_name"],
                    "speak_exactly": "نام مشتری را بگو",
                    "land_code": args.get("land_code"),
                },
            }

        with mock.patch(
            "app.ai.agent_tools.resolve_conversation_land_code", return_value=LAND
        ), mock.patch(
            "app.ai.agent_tools._tool_propose_visit", side_effect=fake_propose
        ):
            from app import create_app

            app = create_app()
            with app.app_context():
                with app.test_request_context("/"):
                    out = run_tool(
                        TOOL_VISIT,
                        {},
                        phone=PHONE,
                        audience="partner",
                        voice="partner",
                        thread_id=THREAD,
                    )
        self.assertEqual(captured.get("args", {}).get("land_code"), LAND)
        self.assertIn("model_result", out)

    def test_partner_rate_limit_disabled(self) -> None:
        from app.ai.credits import check_rate_limit

        self.assertIsNone(check_rate_limit(PHONE, "partner"))


class ChatOpsConversationNoLandAskTests(unittest.TestCase):
    def test_partner_visit_skips_land_code_question(self) -> None:
        from app.conversation.di import make_conversation_manager
        from app.conversation.interfaces import IdentityInfo, ROLE_PARTNER

        mgr = make_conversation_manager()
        identity = IdentityInfo(
            role=ROLE_PARTNER,
            user_key=PHONE,
            phone=PHONE,
            is_logged_in=True,
            is_partner=True,
        )
        with mock.patch.object(mgr._identity, "resolve", return_value=identity):
            out = mgr.handle(
                message="ثبت بازدید",
                user_key=PHONE,
                audience="partner",
                chip_intent="visit",
            )
        self.assertFalse(out.handled)
        self.assertTrue(out.pass_to_supervisor)
        self.assertNotIn("کد فایل", out.reply or "")
        self.assertEqual(
            (out.observability or {}).get("skip_reason"),
            "partner_chat_tools_only",
        )


class ChatOpsVisitDealCardFlowTests(unittest.TestCase):
    """propose visit → confirm → living card; deal card with assignment."""

    def test_visit_confirm_updates_living_card(self) -> None:
        from app import create_app
        from app.ai.agent_tools import (
            TOOL_VISIT,
            apply_confirm_result_to_chat,
            run_tool,
        )
        from app.ai.audience import AUDIENCE_PARTNER
        from app.ai.card_registry import STATE_COMPLETED
        from app.ai.chat_store import append_exchange

        dates = [
            {
                "n": 1,
                "iso": "2026-07-20",
                "jalali": "1405-04-29",
                "jalali_fa": "۲۹ تیر ۱۴۰۵",
                "weekday": "یکشنبه",
                "label": "۱) یکشنبه ۲۹ تیر ۱۴۰۵",
            }
        ]

        def _val(args, *, phone):
            a = dict(args or {})
            code = str(a.get("land_code") or LAND)
            name = str(a.get("customer_name") or "").strip()
            phone_c = str(a.get("customer_phone") or "").strip()
            vdate = str(a.get("visit_date") or "").strip()
            if not name:
                return {
                    "ok": False,
                    "missing": ["customer_name"],
                    "speak_exactly": "نام مشتری را بگو",
                    "land_code": code,
                }
            if not phone_c:
                return {
                    "ok": False,
                    "missing": ["customer_phone"],
                    "speak_exactly": "شماره موبایل مشتری را بگو",
                    "land_code": code,
                }
            if not vdate or vdate == "1":
                # accept "1" as date choice later; for empty ask dates
                if not vdate:
                    return {
                        "ok": False,
                        "status": "needs_date_choice",
                        "available_date_labels": [dates[0]["label"]],
                        "land_code": code,
                    }
            iso = dates[0]["iso"] if vdate in ("1", dates[0]["iso"]) else vdate
            return {
                "ok": True,
                "payload": {
                    "land_code": code,
                    "land_title": "زمین تست",
                    "visit_date": iso,
                    "visit_date_jalali": dates[0]["jalali_fa"],
                    "customer_name": name,
                    "customer_first_name": "علی",
                    "customer_last_name": "تستی",
                    "customer_phone": "09122222222",
                    "partner_name": "همکار تست",
                },
            }

        app = create_app()
        app.config["TESTING"] = True

        with tempfile.TemporaryDirectory() as tmp:
            p1, p2, p3 = _patch_ai_data(tmp)
            with p1, p2, p3, app.app_context():
                with mock.patch(
                    "app.ai.agent_tools.partner_is_approved", return_value=True
                ), mock.patch(
                    "app.ai.agent_tools.resolve_conversation_land_code",
                    return_value=LAND,
                ), mock.patch(
                    "app.ai.agent_tools._active_mission_land_code",
                    return_value=LAND,
                ), mock.patch(
                    "app.express_partner.visit_requests.list_upcoming_visit_dates",
                    return_value=dates,
                ), mock.patch(
                    "app.ai.agent_tools._validate_visit_proposal", side_effect=_val
                ), mock.patch(
                    "app.ai.agent_tools._store_pending_action", return_value="tok-visit-1"
                ), mock.patch(
                    "app.ai.agent_tools._clear_visit_draft"
                ):
                    with app.test_request_context("/"):
                        # 1) name only — land known; ask phone (tool ok=False is expected)
                        r1 = run_tool(
                            TOOL_VISIT,
                            {"customer_name": "علی تستی"},
                            phone=PHONE,
                            audience="partner",
                            voice="partner",
                            thread_id=THREAD,
                        )
                        mr1 = r1.get("model_result") or {}
                        self.assertNotIn("land_code", mr1.get("missing") or [])
                        self.assertNotIn("کد فایل", str(mr1))
                        self.assertIn("customer_phone", mr1.get("missing") or [])

                        # 2) + phone → date choice
                        r2 = run_tool(
                            TOOL_VISIT,
                            {
                                "customer_name": "علی تستی",
                                "customer_phone": "09122222222",
                            },
                            phone=PHONE,
                            audience="partner",
                            voice="partner",
                            thread_id=THREAD,
                        )
                        mr2 = r2.get("model_result") or {}
                        self.assertEqual(mr2.get("status"), "needs_date_choice")
                        self.assertTrue(r2.get("ok"))

                        # 3) date → confirm card
                        r3 = run_tool(
                            TOOL_VISIT,
                            {
                                "customer_name": "علی تستی",
                                "customer_phone": "09122222222",
                                "visit_date": dates[0]["iso"],
                            },
                            phone=PHONE,
                            audience="partner",
                            voice="partner",
                            thread_id=THREAD,
                        )
                        ui = r3.get("ui_action") or {}
                        self.assertTrue(r3.get("ok"), msg=r3)
                        self.assertEqual(ui.get("type"), "confirm_visit", msg=r3)
                        token = ui.get("token")
                        self.assertEqual(token, "tok-visit-1")
                        self.assertEqual(ui.get("status"), "pending")

                        msgs, tid = append_exchange(
                            PHONE,
                            "ثبت بازدید",
                            "اگر درست است تأیید کن.",
                            thread_id=THREAD,
                            audience=AUDIENCE_PARTNER,
                            assistant_agent_actions=[ui],
                        )
                        self.assertTrue(tid)
                        # card_id is added when persisted/normalized
                        card_id = ""
                        for m in msgs:
                            for a in m.get("agent_actions") or []:
                                if a.get("token") == token:
                                    card_id = str(a.get("card_id") or "")
                        self.assertTrue(card_id)

                        chat = apply_confirm_result_to_chat(
                            phone=PHONE,
                            token=token,
                            thread_id=THREAD,
                            audience=AUDIENCE_PARTNER,
                            confirm_out={
                                "ok": True,
                                "message": "بازدید ثبت شد.",
                                "visit_id": "V-TEST-1",
                                "land_code": LAND,
                                "action_type": "confirm_visit",
                            },
                        )
                        self.assertTrue(chat.get("card_updated"))
                        found = False
                        for m in chat.get("messages") or []:
                            for a in m.get("agent_actions") or []:
                                if a.get("token") == token or a.get("card_id") == card_id:
                                    self.assertEqual(a.get("state"), STATE_COMPLETED)
                                    found = True
                        self.assertTrue(found, "living card state not completed")

    def test_deal_card_propose_when_mode_deal(self) -> None:
        from app import create_app
        from app.ai.agent_tools import TOOL_DEAL, run_tool

        app = create_app()
        with app.app_context():
            with mock.patch(
                "app.ai.agent_tools.resolve_conversation_land_code", return_value=LAND
            ), mock.patch(
                "app.ai.agent_tools._partner_tx_snapshot",
                return_value={
                    "ok": True,
                    "tx_mode": "deal",
                    "land_title": "زمین تست",
                    "visit_date": "2026-07-20",
                    "visit_date_jalali": "۲۹ تیر",
                    "has_assignment": True,
                },
            ), mock.patch(
                "app.ai.agent_tools.partner_is_approved", return_value=True
            ), mock.patch(
                "app.ai.agent_tools._store_pending_action", return_value="tok-deal-1"
            ):
                with app.test_request_context("/"):
                    out = run_tool(
                        TOOL_DEAL,
                        {},
                        phone=PHONE,
                        audience="partner",
                        voice="partner",
                        thread_id=THREAD,
                    )
        ui = out.get("ui_action") or {}
        self.assertEqual(ui.get("type"), "confirm_deal", msg=out)
        self.assertTrue(ui.get("token"))
        self.assertEqual(ui.get("land_code"), LAND)
        self.assertNotIn("کد فایل", str(out))

    def test_deal_lazy_claims_then_opens_card(self) -> None:
        """Without assignment, chat_claim then deal card when land is claimable."""
        from app import create_app
        from app.ai.agent_tools import TOOL_DEAL, run_tool

        snaps = iter(
            [
                {
                    "ok": True,
                    "tx_mode": "deal",
                    "land_title": "زمین تست",
                    "has_assignment": False,
                },
                {
                    "ok": True,
                    "tx_mode": "deal",
                    "land_title": "زمین تست",
                    "visit_date": "2026-07-20",
                    "visit_date_jalali": "۲۹ تیر",
                    "has_assignment": True,
                },
            ]
        )

        app = create_app()
        with app.app_context():
            with mock.patch(
                "app.ai.agent_tools.resolve_conversation_land_code", return_value=LAND
            ), mock.patch(
                "app.ai.agent_tools._partner_tx_snapshot", side_effect=lambda *a, **k: next(snaps)
            ), mock.patch(
                "app.express_partner.partner_missions.claim_express_land_for_partner",
                return_value=True,
            ), mock.patch(
                "app.ai.agent_tools.partner_is_approved", return_value=True
            ), mock.patch(
                "app.ai.agent_tools._store_pending_action", return_value="tok-deal-claim"
            ):
                with app.test_request_context("/"):
                    out = run_tool(
                        TOOL_DEAL,
                        {},
                        phone=PHONE,
                        audience="partner",
                        voice="partner",
                        thread_id=THREAD,
                    )
        ui = out.get("ui_action") or {}
        self.assertEqual(ui.get("type"), "confirm_deal", msg=out)

    def test_deal_blocked_when_claim_fails(self) -> None:
        """Sold / locked lands still cannot open deal card after failed claim."""
        from app import create_app
        from app.ai.agent_tools import TOOL_DEAL, run_tool

        app = create_app()
        with app.app_context():
            with mock.patch(
                "app.ai.agent_tools.resolve_conversation_land_code", return_value=LAND
            ), mock.patch(
                "app.ai.agent_tools._partner_tx_snapshot",
                return_value={
                    "ok": True,
                    "tx_mode": "deal",
                    "land_title": "زمین تست",
                    "has_assignment": False,
                },
            ), mock.patch(
                "app.express_partner.partner_missions.claim_express_land_for_partner",
                return_value=False,
            ), mock.patch(
                "app.ai.agent_tools.partner_is_approved", return_value=True
            ):
                with app.test_request_context("/"):
                    out = run_tool(
                        TOOL_DEAL,
                        {},
                        phone=PHONE,
                        audience="partner",
                        voice="partner",
                        thread_id=THREAD,
                    )
        self.assertFalse(out.get("ok"))
        err = str((out.get("model_result") or {}).get("error") or "")
        self.assertIn("در دسترس نیست", err)


class ChatOpsLandClaimAndFocusTests(unittest.TestCase):
    def test_mission_land_code_always_empty(self) -> None:
        from app.ai.agent_tools import _active_mission_land_code

        self.assertEqual(_active_mission_land_code(PHONE, "mission-tid"), "")
        self.assertEqual(_active_mission_land_code(PHONE, None), "")

    def test_claim_express_land_for_partner(self) -> None:
        from app.express_partner import partner_missions as pm

        land = {"code": LAND, "is_express": True, "express_commission_pct": 5}
        assigned: list = []

        def fake_ensure(phone, land_row, *, source="random_mission"):
            assigned.append(
                {
                    "partner_phone": phone,
                    "land_code": land_row["code"],
                    "status": "active",
                    "source": source,
                }
            )

        with mock.patch.object(pm, "load_express_lands_cached", return_value=[land]), mock.patch.object(
            pm, "load_express_assignments", side_effect=lambda: list(assigned)
        ), mock.patch.object(pm, "_ensure_personal_assignment", side_effect=fake_ensure):
            ok = pm.claim_express_land_for_partner(PHONE, LAND, source="chat_claim")
        self.assertTrue(ok)
        self.assertEqual(assigned[0]["source"], "chat_claim")


class ChatOpsOpenVisitEarlyGateTests(unittest.TestCase):
    def test_open_visit_approved_offers_complete_card(self) -> None:
        from app import create_app
        from app.ai.agent_tools import TOOL_VISIT, run_tool

        app = create_app()
        with app.app_context():
            with mock.patch(
                "app.ai.agent_tools.resolve_conversation_land_code", return_value=LAND
            ), mock.patch(
                "app.ai.agent_tools.partner_is_approved", return_value=True
            ), mock.patch(
                "app.ai.agent_tools._load_visit_draft", return_value={}
            ), mock.patch(
                "app.ai.agent_tools._save_visit_draft"
            ), mock.patch(
                "app.ai.agent_tools.clear_visit_draft"
            ), mock.patch(
                "app.utils.storage.load_express_visit_requests",
                return_value=[
                    {
                        "id": "V1",
                        "partner_phone": PHONE,
                        "land_code": LAND,
                        "status": "approved",
                    }
                ],
            ), mock.patch(
                "app.express_partner.visit_requests.partner_open_visit",
                return_value={"id": "V1", "land_code": LAND, "status": "approved"},
            ), mock.patch(
                "app.ai.agent_tools._tool_propose_simple_tx",
                return_value={
                    "ok": True,
                    "model_result": {
                        "ok": True,
                        "status": "needs_user_confirmation",
                        "land_code": LAND,
                    },
                    "ui_action": {
                        "type": "confirm_complete_visit",
                        "token": "tok",
                        "title": "تأیید: بازدید انجام شد",
                        "status": "pending",
                        "land_code": LAND,
                    },
                },
            ):
                with app.test_request_context("/"):
                    out = run_tool(
                        TOOL_VISIT,
                        {},
                        phone=PHONE,
                        audience="partner",
                        voice="partner",
                        thread_id=THREAD,
                    )
        mr = out.get("model_result") or {}
        ui = out.get("ui_action") or {}
        self.assertTrue(out.get("ok"))
        self.assertNotEqual(mr.get("status"), "needs_date_choice")
        self.assertEqual(ui.get("type"), "confirm_complete_visit")
        self.assertIn("کارت", str(mr.get("speak_exactly") or ""))

    def test_open_visit_done_pending_does_not_ask_again(self) -> None:
        from app import create_app
        from app.ai.agent_tools import TOOL_VISIT, run_tool

        app = create_app()
        with app.app_context():
            with mock.patch(
                "app.ai.agent_tools.resolve_conversation_land_code", return_value=LAND
            ), mock.patch(
                "app.ai.agent_tools.partner_is_approved", return_value=True
            ), mock.patch(
                "app.ai.agent_tools._load_visit_draft", return_value={}
            ), mock.patch(
                "app.ai.agent_tools._save_visit_draft"
            ), mock.patch(
                "app.ai.agent_tools.clear_visit_draft"
            ), mock.patch(
                "app.utils.storage.load_express_visit_requests",
                return_value=[
                    {
                        "id": "V2",
                        "partner_phone": PHONE,
                        "land_code": LAND,
                        "status": "done_pending",
                    }
                ],
            ), mock.patch(
                "app.express_partner.visit_requests.partner_open_visit",
                return_value={
                    "id": "V2",
                    "land_code": LAND,
                    "status": "done_pending",
                },
            ):
                with app.test_request_context("/"):
                    out = run_tool(
                        TOOL_VISIT,
                        {},
                        phone=PHONE,
                        audience="partner",
                        voice="partner",
                        thread_id=THREAD,
                    )
        mr = out.get("model_result") or {}
        self.assertTrue(out.get("ok"))
        self.assertEqual(mr.get("status"), "visit_done_awaiting_admin")
        speak = str(mr.get("speak_exactly") or "")
        self.assertIn("منتظر تأیید ادمین", speak)
        self.assertNotIn("بنویس «بازدید انجام شد»", speak)


class ChatOpsHttpSmokeTests(unittest.TestCase):

    def setUp(self) -> None:
        from app import create_app

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_partner_ai_chat_accepts_when_tools_mocked(self) -> None:
        with self.client.session_transaction() as sess:
            sess["user_phone"] = PHONE
            sess["logged_in"] = True
            sess["VINOR_IS_EXPRESS_PARTNER"] = True

        with mock.patch(
            "app.ai.services.generate_reply",
            return_value={
                "ok": True,
                "reply": "نام مشتری را بگو",
                "land_codes": [],
                "agent_actions": [],
            },
        ), mock.patch(
            "app.express_partner.partner_roles.partner_is_approved", return_value=True
        ), mock.patch(
            "app.utils.storage.load_express_partners",
            return_value=[{"phone": PHONE, "status": "approved"}],
        ):
            resp = self.client.post(
                "/express/partner/ai/chat",
                json={
                    "message": "ثبت بازدید",
                    "thread_id": THREAD,
                    "intent": "visit",
                },
            )
        self.assertNotEqual(resp.status_code, 500, resp.data[:500])
        if resp.status_code == 200:
            data = resp.get_json()
            self.assertTrue(data.get("ok"))
            self.assertNotIn("کد فایل", data.get("reply") or "")


if __name__ == "__main__":
    unittest.main()
