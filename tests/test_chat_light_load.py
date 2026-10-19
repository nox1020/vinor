# -*- coding: utf-8 -*-
"""Light chat history, on-demand land cards, and sync-only-new."""
from __future__ import annotations

import json
import os
import tempfile
from unittest import mock

PHONE_A = "09120001111"
PHONE_B = "09120002222"


def _ai_file(root, *parts):
    return os.path.join(root, *parts)


def _patch_chat_dir(root):
    side = lambda *parts: _ai_file(root, *parts)
    return [
        mock.patch("app.ai.paths.ai_data_file", side_effect=side),
        mock.patch("app.ai.chat_store.ai_data_file", side_effect=side),
    ]


def _land(code, **extra):
    row = {"code": str(code), "is_express": True, "public": True, "express_status": "active"}
    row.update(extra)
    return row


def _catalog():
    lands = [
        _land("101"),
        _land("102", public=False),
        _land("103", express_status="sold"),
        _land("104", express_status="sold"),
    ]
    assignments = [
        {"partner_phone": PHONE_B, "land_code": "104", "status": "active"},
    ]
    return lands, assignments


def _patch_catalog():
    lands, assignments = _catalog()

    def _detail(code):
        return {"ok": True, "code": str(code), "html": f"<div class='vn-lcd' data-code='{code}'>card</div>"}

    return [
        mock.patch("app.ai.context.load_express_lands_cached", return_value=lands),
        mock.patch("app.ai.context.load_ads_cached", return_value=lands),
        mock.patch("app.ai.context.load_express_assignments", return_value=assignments),
        mock.patch(
            "app.express_partner.land_chat_detail.render_land_chat_detail_html",
            side_effect=_detail,
        ),
    ]


def test_light_history_keeps_codes_and_skips_card_html():
    from app import create_app
    from app.ai.audience import AUDIENCE_PUBLIC
    from app.ai.chat_store import append_exchange, append_typed_message

    tmp = tempfile.TemporaryDirectory()
    patches = _patch_chat_dir(tmp.name)
    for patcher in patches:
        patcher.start()
    try:
        app = create_app()
        app.config["TESTING"] = True
        with app.app_context():
            _msgs, tid = append_exchange(
                PHONE_A,
                "کدوم فایل؟",
                "این فایل مناسب است",
                audience=AUDIENCE_PUBLIC,
                assistant_land_codes=["101"],
                include_land_cards=False,
            )
            append_typed_message(
                PHONE_A,
                "جزئیات فایل 101",
                thread_id=tid,
                audience=AUDIENCE_PUBLIC,
                source="land_detail",
                land_codes=["101"],
                meta={"land_chat_detail": True, "land_code": "101"},
                include_land_cards=False,
            )
            append_exchange(
                PHONE_A,
                "تأیید",
                "کارت را بزن",
                thread_id=tid,
                audience=AUDIENCE_PUBLIC,
                assistant_agent_actions=[
                    {
                        "type": "confirm_visit",
                        "token": "tok-light",
                        "title": "تأیید بازدید",
                        "status": "pending",
                    }
                ],
                include_land_cards=False,
            )

        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user_phone"] = PHONE_A
        with mock.patch(
            "app.ai.land_cards.render_land_cards_html",
            side_effect=AssertionError("land html"),
        ), mock.patch(
            "app.ai.land_cards.land_cards_payload",
            side_effect=AssertionError("land payload"),
        ), mock.patch(
            "app.express_partner.land_chat_detail.render_land_chat_detail_html",
            side_effect=AssertionError("detail html"),
        ):
            res = client.get(f"/ai/history?thread_id={tid}")
        body = res.get_json()
        assert res.status_code == 200
        assert body["ok"] is True
        assert "threads" in body
        assert "has_more" not in body
        blob = json.dumps(body, ensure_ascii=False)
        assert "ai-land-cards" not in blob
        assert "vn-lcd" not in blob
        assert "land_detail_html" not in blob
        coded = [m for m in body["messages"] if m.get("land_codes") == ["101"] and m.get("role") == "assistant"]
        assert coded
        detail = next(m for m in body["messages"] if m.get("source") == "land_detail")
        assert detail.get("land_code") == "101"
        assert detail.get("lazy_land_codes") == ["101"]
        assert not (detail.get("content") or "").strip()
        agent = next(m for m in body["messages"] if m.get("agent_actions"))
        assert "ai-agent-card" in (agent.get("cards_html") or "")
        assert agent["agent_actions"][0]["token"] == "tok-light"

        heavy_patch = mock.patch(
            "app.ai.land_cards.render_land_cards_html",
            return_value="<div class='ai-land-cards'>heavy</div>",
        )
        detail_patch = mock.patch(
            "app.express_partner.land_chat_detail.render_land_chat_detail_html",
            return_value={"ok": True, "code": "101", "html": "<div class='vn-lcd'>detail</div>"},
        )
        with heavy_patch, detail_patch:
            heavy = client.get(f"/ai/history?thread_id={tid}&cards=1")
        heavy_body = heavy.get_json()
        heavy_blob = json.dumps(heavy_body, ensure_ascii=False)
        assert "vn-lcd" in heavy_blob
        assert "ai-land-cards" in heavy_blob
    finally:
        for patcher in patches:
            patcher.stop()
        tmp.cleanup()


def test_land_cards_respect_access_and_batch_limit():
    from app import create_app

    tmp = tempfile.TemporaryDirectory()
    patches = _patch_chat_dir(tmp.name) + _patch_catalog()
    for patcher in patches:
        patcher.start()
    try:
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()

        anon = client.get(
            "/express/partner/ai/land-cards?codes=101",
            headers={"Accept": "application/json"},
        )
        assert anon.status_code == 401

        public = client.get("/ai/land-cards?codes=101,102,103,104,101")
        public_body = public.get_json()
        assert public.status_code == 200
        assert public_body["ok"] is True
        assert [c["code"] for c in public_body["cards"]] == ["101"]
        assert "vn-lcd" in public_body["cards"][0]["html"]
        assert set(public_body["missing"]) == {"102", "103", "104"}
        leaked = json.dumps(public_body["cards"], ensure_ascii=False)
        assert "data-code='102'" not in leaked
        assert "data-code='103'" not in leaked
        assert "data-code='104'" not in leaked

        with client.session_transaction() as sess:
            sess["user_phone"] = PHONE_A
        partner_a = client.get(
            "/express/partner/ai/land-cards?codes=101,102,103,104",
            headers={"Accept": "application/json"},
        )
        a_body = partner_a.get_json()
        assert partner_a.status_code == 200
        assert [c["code"] for c in a_body["cards"]] == ["101"]
        assert set(a_body["missing"]) == {"102", "103", "104"}

        with client.session_transaction() as sess:
            sess["user_phone"] = PHONE_B
        partner_b = client.get(
            "/express/partner/ai/land-cards?codes=101,102,103,104",
            headers={"Accept": "application/json"},
        )
        b_body = partner_b.get_json()
        assert [c["code"] for c in b_body["cards"]] == ["101", "104"]
        assert set(b_body["missing"]) == {"102", "103"}

        too_many = client.get("/ai/land-cards?codes=" + ",".join(str(n) for n in range(1, 12)))
        assert too_many.status_code == 400
        assert too_many.get_json()["error"] == "too_many_codes"
        assert too_many.get_json()["max"] == 10
    finally:
        for patcher in patches:
            patcher.stop()
        tmp.cleanup()


def test_sync_slices_before_enrich_and_keeps_old_app_shape():
    from app import create_app
    from app.ai.audience import AUDIENCE_PUBLIC
    from app.ai.chat_store import (
        _collapsed_thread_messages,
        _save_record,
        _select_messages_since,
        append_exchange,
        append_typed_message,
        load_user_record,
        messages_since,
    )

    tmp = tempfile.TemporaryDirectory()
    patches = _patch_chat_dir(tmp.name)
    for patcher in patches:
        patcher.start()
    calls = {"n": 0}

    def _render(*_a, **_k):
        calls["n"] += 1
        return "<div class='ai-land-cards'>heavy</div>"

    try:
        app = create_app()
        app.config["TESTING"] = True
        with app.app_context():
            tid = ""
            for index in range(4):
                _msgs, tid = append_exchange(
                    PHONE_A,
                    f"user-{index}",
                    f"assistant-{index}",
                    thread_id=tid or None,
                    audience=AUDIENCE_PUBLIC,
                    assistant_land_codes=["101"],
                    include_land_cards=False,
                )
            append_typed_message(
                PHONE_A,
                "پاسخ تیم",
                thread_id=tid,
                audience=AUDIENCE_PUBLIC,
                source="admin_escalation",
                escalation_id="esc-old",
                include_land_cards=False,
            )
            record = load_user_record(PHONE_A, AUDIENCE_PUBLIC)
            th = record["threads"][0]
            for index, item in enumerate(th["messages"]):
                item["created_at"] = f"2026-01-01T00:00:{index:02d}"
                if item.get("source") == "admin_escalation":
                    item["created_at"] = "2025-12-31T23:00:00"
            _save_record(record, PHONE_A, AUDIENCE_PUBLIC)
            collapsed = _collapsed_thread_messages(PHONE_A, tid, AUDIENCE_PUBLIC)
            assert len(collapsed) == 9

            with mock.patch("app.ai.land_cards.render_land_cards_html", side_effect=_render), mock.patch(
                "app.ai.land_cards.land_cards_payload", return_value=[]
            ):
                calls["n"] = 0
                light = messages_since(
                    PHONE_A,
                    tid,
                    audience=AUDIENCE_PUBLIC,
                    after_count=6,
                )
                assert calls["n"] == 0
                calls["n"] = 0
                heavy = messages_since(
                    PHONE_A,
                    tid,
                    audience=AUDIENCE_PUBLIC,
                    after_count=6,
                    include_land_cards=True,
                )
                assert calls["n"] == 1

            selected = _select_messages_since(collapsed, after_count=6)
            assert [m["id"] for m in light] == [m["id"] for m in selected]
            assert {m["id"] for m in light} == {m["id"] for m in collapsed[6:]}
            assert [m.get("content") for m in light] == [m.get("content") for m in heavy]
            assert "ai-land-cards" not in json.dumps(light)
            assert "ai-land-cards" in json.dumps(heavy)

            by_after = messages_since(
                PHONE_A,
                tid,
                "2026-01-01T00:00:05",
                audience=AUDIENCE_PUBLIC,
            )
            assert [m["created_at"] for m in by_after] == [
                "2025-12-31T23:00:00",
                "2026-01-01T00:00:06",
                "2026-01-01T00:00:07",
            ]
            assert by_after[0]["escalation_id"] == "esc-old"
            hidden = messages_since(
                PHONE_A,
                tid,
                "2026-01-01T00:00:05",
                audience=AUDIENCE_PUBLIC,
                exclude_escalation_ids=["esc-old"],
            )
            assert [m["created_at"] for m in hidden] == [
                "2026-01-01T00:00:06",
                "2026-01-01T00:00:07",
            ]
            counted = messages_since(
                PHONE_A,
                tid,
                "2026-01-01T00:00:00",
                audience=AUDIENCE_PUBLIC,
                after_count=8,
            )
            assert [m["id"] for m in counted] == [collapsed[8]["id"]]

        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user_phone"] = PHONE_A
        old = client.get(f"/ai/sync?thread_id={tid}&count=6")
        old_body = old.get_json()
        assert old.status_code == 200
        assert old_body["ok"] is True
        assert old_body["thread_id"] == tid
        assert old_body["total"] == len(old_body["messages"]) == 3
        assert "audience" in old_body
        for msg in old_body["messages"]:
            assert msg["role"]
            assert "content" in msg
        assert "ai-land-cards" not in json.dumps(old_body)
        hist = client.get(f"/ai/history?thread_id={tid}")
        hist_body = hist.get_json()
        assert hist_body["ok"] is True
        assert len(hist_body["messages"]) == 9
        assert hist_body["messages"][1]["land_codes"] == ["101"]
        assert "mode" in hist_body
    finally:
        for patcher in patches:
            patcher.stop()
        tmp.cleanup()
