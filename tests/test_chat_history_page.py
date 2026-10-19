# -*- coding: utf-8 -*-
"""Chat history pages the latest messages and stays inside the caller's thread."""
from __future__ import annotations

import os
import tempfile
from unittest import mock

PHONE_A = "09120000111"
PHONE_B = "09120000222"


def _ai_file(root, *parts):
    return os.path.join(root, *parts)


def _patch_chat_dir(root):
    side = lambda *parts: _ai_file(root, *parts)
    return [
        mock.patch("app.ai.paths.ai_data_file", side_effect=side),
        mock.patch("app.ai.chat_store.ai_data_file", side_effect=side),
    ]


def _seed(phone: str, audience: str, exchanges: int) -> str:
    from app.ai.chat_store import append_exchange

    thread_id = ""
    for index in range(exchanges):
        _msgs, thread_id = append_exchange(
            phone,
            f"user-{index}",
            f"assistant-{index}",
            thread_id=thread_id or None,
            audience=audience,
        )
    return thread_id


def test_slice_returns_latest_page_then_older_pages():
    from app.ai.chat_store import slice_messages_page

    rows = [{"id": f"m{i:02d}", "role": "user", "content": str(i)} for i in range(25)]
    page, has_more, cursor = slice_messages_page(rows, limit=10, before_id=None)
    assert [row["id"] for row in page] == [f"m{i:02d}" for i in range(15, 25)]
    assert has_more is True
    assert cursor == "m15"

    older, has_more, cursor = slice_messages_page(rows, limit=10, before_id="m15")
    assert [row["id"] for row in older] == [f"m{i:02d}" for i in range(5, 15)]
    assert has_more is True
    assert cursor == "m05"
    assert set(row["id"] for row in page).isdisjoint(row["id"] for row in older)

    rest, has_more, cursor = slice_messages_page(rows, limit=10, before_id="m05")
    assert [row["id"] for row in rest] == [f"m{i:02d}" for i in range(0, 5)]
    assert has_more is False
    assert cursor is None

    missing, has_more, cursor = slice_messages_page(rows, limit=10, before_id="nope")
    assert missing == []
    assert has_more is False
    assert cursor is None


def test_history_endpoint_pages_only_the_callers_thread():
    from app import create_app
    from app.ai.audience import AUDIENCE_PARTNER, AUDIENCE_PUBLIC

    tmp = tempfile.TemporaryDirectory()
    patches = _patch_chat_dir(tmp.name)
    for patcher in patches:
        patcher.start()
    try:
        app = create_app()
        app.config["TESTING"] = True
        with app.app_context():
            public_thread = _seed(PHONE_A, AUDIENCE_PUBLIC, 15)
            _seed(PHONE_B, AUDIENCE_PUBLIC, 3)
            partner_thread = _seed(PHONE_A, AUDIENCE_PARTNER, 15)
            _seed(PHONE_B, AUDIENCE_PARTNER, 2)

        client = app.test_client()
        anon = client.get(
            "/express/partner/ai/history?limit=10",
            headers={"Accept": "application/json"},
        )
        assert anon.status_code == 401

        with client.session_transaction() as sess:
            sess["user_phone"] = PHONE_A
        first = client.get(f"/ai/history?limit=10&thread_id={public_thread}")
        body = first.get_json()
        assert first.status_code == 200
        assert body["ok"] is True
        contents = [msg["content"] for msg in body["messages"]]
        assert contents == [
            "user-10",
            "assistant-10",
            "user-11",
            "assistant-11",
            "user-12",
            "assistant-12",
            "user-13",
            "assistant-13",
            "user-14",
            "assistant-14",
        ]
        assert body["has_more"] is True
        assert body["next_cursor"] == body["messages"][0]["id"]

        second = client.get(
            "/ai/history?limit=10&thread_id="
            + public_thread
            + "&before_id="
            + body["next_cursor"]
        )
        older = second.get_json()
        older_contents = [msg["content"] for msg in older["messages"]]
        assert older_contents[0] == "user-5"
        assert older_contents[-1] == "assistant-9"
        assert older["has_more"] is True
        assert set(contents).isdisjoint(older_contents)

        full = client.get(f"/ai/history?thread_id={public_thread}")
        full_body = full.get_json()
        assert len(full_body["messages"]) == 30
        assert "has_more" not in full_body
        assert "next_cursor" not in full_body

        with client.session_transaction() as sess:
            sess["user_phone"] = PHONE_B
        stolen = client.get(
            f"/ai/history?limit=10&thread_id={public_thread}&before_id={body['next_cursor']}"
        )
        stolen_body = stolen.get_json()
        assert stolen.status_code == 200
        stolen_text = " ".join(msg.get("content") or "" for msg in stolen_body["messages"])
        assert "user-14" not in stolen_text
        assert "assistant-10" not in stolen_text

        with client.session_transaction() as sess:
            sess["user_phone"] = PHONE_A
        partner = client.get(
            f"/express/partner/ai/history?limit=10&thread_id={partner_thread}",
            headers={"Accept": "application/json"},
        )
        partner_body = partner.get_json()
        assert partner.status_code == 200
        assert [msg["content"] for msg in partner_body["messages"]][-1] == "assistant-14"
        assert partner_body["has_more"] is True

        with client.session_transaction() as sess:
            sess["user_phone"] = PHONE_B
        other = client.get(
            f"/express/partner/ai/history?limit=10&thread_id={partner_thread}",
            headers={"Accept": "application/json"},
        )
        other_body = other.get_json()
        other_text = " ".join(msg.get("content") or "" for msg in other_body["messages"])
        assert "user-14" not in other_text
    finally:
        for patcher in patches:
            patcher.stop()
        tmp.cleanup()
