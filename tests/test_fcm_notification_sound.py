# -*- coding: utf-8 -*-
"""Muted FCM devices still receive messages, but on the silent Android channel."""
from flask import Flask

from app.api.fcm import api_fcm_bp
from app.services.fcm_tokens import (
    register_token, muted_tokens_for_phones, list_tokens_for_phone,
)
import app.services.fcm_push as fcm_push


def test_device_mute_flag_persists_and_keeps_token_registered(tmp_path):
    app = Flask(__name__, instance_path=str(tmp_path))
    app.secret_key = "unit-test"
    app.register_blueprint(api_fcm_bp)
    client = app.test_client()
    phone = "09124448888"
    with client.session_transaction() as sess:
        sess["user_phone"] = phone
    headers = {"User-Agent": "VinorApp/999"}
    response = client.post("/api/fcm/register", json={"token": "device-1", "muted": True}, headers=headers)
    assert response.status_code == 200
    with app.app_context():
        assert muted_tokens_for_phones([phone]) == {"device-1": True}
        assert len(list_tokens_for_phone(phone)) == 1
    response = client.post("/api/fcm/register", json={"token": "device-1", "muted": False}, headers=headers)
    assert response.status_code == 200
    with app.app_context():
        assert muted_tokens_for_phones([phone]) == {"device-1": False}
        assert len(list_tokens_for_phone(phone)) == 1


def test_fcm_payload_mutes_sound_but_keeps_notification(tmp_path, monkeypatch):
    app = Flask(__name__, instance_path=str(tmp_path))
    with app.app_context():
        monkeypatch.setattr(fcm_push, "is_fcm_configured", lambda: True)
        monkeypatch.setattr(fcm_push, "_access_token", lambda: "test-access")
        monkeypatch.setattr(fcm_push, "_project_id", lambda: "test-project")
        captured = []
        class Response:
            status_code = 200
            text = "ok"
        def fake_post(endpoint, **kwargs):
            captured.append(kwargs["json"]["message"])
            return Response()
        monkeypatch.setattr(fcm_push.requests, "post", fake_post)
        assert fcm_push.send_fcm_to_token("device", title="Title", body="Body", muted=True)["ok"]
        assert fcm_push.send_fcm_to_token("device", title="Title", body="Body", muted=False)["ok"]
        silent, audible = captured
        assert silent["notification"]["title"] == audible["notification"]["title"] == "Title"
        quiet = silent["android"]["notification"]
        loud = audible["android"]["notification"]
        assert quiet["channel_id"] == "vinor_express_partner_silent"
        assert "sound" not in quiet
        assert quiet["notification_priority"] == "PRIORITY_LOW"
        assert loud["channel_id"] == "vinor_express_partner"
        assert loud["sound"] == "default"
