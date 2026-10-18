# -*- coding: utf-8 -*-
"""SMS-only OTP — unit, integration, security. Live sms.ir is never called."""
from __future__ import annotations

import io
import logging
import os
import tempfile
import threading
import unittest
from unittest import mock

from flask import Flask

from app.auth.otp.providers.base import (
    KIND_FAILED,
    KIND_INVALID_CREDENTIALS,
    KIND_SUCCESS,
    KIND_TIMEOUT,
    OTPDeliveryResult,
)

SMS_OK = OTPDeliveryResult(success=True, provider="sms", failure_kind=KIND_SUCCESS)
SMS_FAIL = OTPDeliveryResult(success=False, provider="sms", failure_kind=KIND_FAILED, error_code="FAILED")
SMS_TIMEOUT = OTPDeliveryResult(success=False, provider="sms", failure_kind=KIND_TIMEOUT, error_code="TIMEOUT")
SMS_CREDS = OTPDeliveryResult(
    success=False,
    provider="sms",
    failure_kind=KIND_INVALID_CREDENTIALS,
    error_code="INVALID_CREDENTIALS",
)


def _env(tmp: str, extra: dict | None = None) -> dict:
    env = {
        "INSTANCE_PATH": tmp,
        "SECRET_KEY": "test-session-secret",
        "VINOR_OTP_HMAC_SECRET": "test-otp-hmac-secret",
        "VINOR_OTP_SMS_ENABLED": "1",
        "VINOR_OTP_EXPOSE_IN_DEV": "0",
        "VINOR_OTP_RESEND_COOLDOWN_SECONDS": "60",
        "VINOR_OTP_PHONE_HOURLY_LIMIT": "5",
        "VINOR_OTP_IP_HOURLY_LIMIT": "20",
        "VINOR_OTP_MAX_ATTEMPTS": "5",
        "VINOR_OTP_TTL_SECONDS": "120",
        "VINOR_OTP_DIGITS": "5",
    }
    if extra:
        env.update(extra)
    return env


class GenerateOtpTests(unittest.TestCase):
    def test_generate_otp(self) -> None:
        from app.auth.otp.crypto import generate_otp

        code = generate_otp(5)
        self.assertEqual(len(code), 5)
        self.assertTrue(code.isdigit())
        self.assertGreater(len({generate_otp(5) for _ in range(30)}), 1)


class OtpHashTests(unittest.TestCase):
    def setUp(self) -> None:
        self._patch = mock.patch.dict(os.environ, _env(tempfile.mkdtemp()), clear=False)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()

    def test_hash_otp(self) -> None:
        from app.auth.otp.crypto import hash_otp, verify_otp_hash

        h = hash_otp("09121234567", "auth_api", "58321")
        self.assertEqual(len(h), 64)
        self.assertNotEqual(h, "58321")
        self.assertTrue(verify_otp_hash("09121234567", "auth_api", "58321", h))
        self.assertFalse(verify_otp_hash("09121234567", "auth_api", "00000", h))


class ClientIpTests(unittest.TestCase):
    def test_public_peer_ignores_forwarded_header(self) -> None:
        from app.auth.otp.request_meta import public_client_ip

        seen = public_client_ip("8.8.8.8", "1.0.0.1, 1.1.1.1")
        self.assertEqual(seen, "8.8.8.8")

    def test_loopback_uses_rightmost_public_forwarded(self) -> None:
        from app.auth.otp.request_meta import public_client_ip

        seen = public_client_ip("127.0.0.1", "1.0.0.1, 8.8.8.8")
        self.assertEqual(seen, "8.8.8.8")

    def test_private_without_header_stays_private(self) -> None:
        from app.auth.otp.request_meta import ip_is_public, public_client_ip

        self.assertFalse(ip_is_public("127.0.0.1"))
        self.assertEqual(public_client_ip("127.0.0.1", ""), "127.0.0.1")


class PhoneNormalizationTests(unittest.TestCase):
    def test_phone_normalization(self) -> None:
        from app.auth.otp.phone import canonical_mobile, is_canonical_mobile

        expected = "09121234567"
        self.assertEqual(canonical_mobile("09121234567"), expected)
        self.assertEqual(canonical_mobile("+989121234567"), expected)
        self.assertEqual(canonical_mobile("989121234567"), expected)
        self.assertEqual(canonical_mobile("۰۹۱۲۱۲۳۴۵۶۷"), expected)
        self.assertEqual(canonical_mobile("+۹۸۹۱۲۱۲۳۴۵۶۷"), expected)
        self.assertTrue(is_canonical_mobile(expected))
        self.assertFalse(is_canonical_mobile("12345"))


class _OtpStoreCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self._patch = mock.patch.dict(os.environ, _env(self.tmp), clear=False)
        self._patch.start()
        from app.auth.otp import store

        store.drop_schema()
        store.init_schema()

    def tearDown(self) -> None:
        from app.auth.otp import store

        store.drop_schema()
        self._patch.stop()


class SmsProviderTests(unittest.TestCase):
    def test_sms_success(self) -> None:
        from app.auth.otp.providers.sms import SmsOTPProvider

        with mock.patch("app.services.sms.send_sms_code", return_value={"ok": True, "status": 200, "body": {}}):
            result = SmsOTPProvider().send_otp("09121234567", "12345", request_id="r1")
        self.assertTrue(result.success)
        self.assertEqual(result.provider, "sms")
        self.assertEqual(result.failure_kind, KIND_SUCCESS)

    def test_sms_failure(self) -> None:
        from app.auth.otp.providers.sms import SmsOTPProvider

        with mock.patch(
            "app.services.sms.send_sms_code",
            return_value={"ok": False, "status": 400, "body": {"error": "fail"}},
        ):
            result = SmsOTPProvider().send_otp("09121234567", "12345")
        self.assertFalse(result.success)
        self.assertEqual(result.failure_kind, KIND_FAILED)

    def test_verify_rejection_uses_service_line_once(self) -> None:
        from app.services.sms import send_sms_code

        with mock.patch("app.services.sms.get_sms_api_key", return_value="test-key"):
            with mock.patch(
                "app.services.sms._send_otp_verify",
                return_value={"ok": False, "status": 400, "body": {"message": "template"}},
            ):
                with mock.patch(
                    "app.services.sms.send_sms_direct",
                    return_value={"ok": True, "status": 200, "body": {"status": 1}},
                ) as bulk:
                    result = send_sms_code("09121234567", "12345", record_history=False)
        self.assertTrue(result["ok"])
        bulk.assert_called_once()

    def test_verify_timeout_does_not_send_a_second_sms(self) -> None:
        from app.services.sms import send_sms_code

        with mock.patch("app.services.sms.get_sms_api_key", return_value="test-key"):
            with mock.patch(
                "app.services.sms._send_otp_verify",
                return_value={"ok": False, "status": 0, "body": {"error": "timed out"}},
            ):
                with mock.patch("app.services.sms.send_sms_direct") as bulk:
                    result = send_sms_code("09121234567", "12345", record_history=False)
        self.assertFalse(result["ok"])
        bulk.assert_not_called()

    def test_sms_timeout(self) -> None:
        from app.auth.otp.providers.sms import SmsOTPProvider

        with mock.patch(
            "app.services.sms.send_sms_code",
            return_value={"ok": False, "status": 0, "body": {"error": "timed out"}},
        ):
            result = SmsOTPProvider().send_otp("09121234567", "12345")
        self.assertFalse(result.success)
        self.assertEqual(result.failure_kind, KIND_TIMEOUT)

    def test_sms_invalid_credentials(self) -> None:
        from app.auth.otp.providers.sms import SmsOTPProvider

        with mock.patch(
            "app.services.sms.send_sms_code",
            return_value={"ok": False, "status": 401, "body": {"error": "unauthorized"}},
        ):
            result = SmsOTPProvider().send_otp("09121234567", "12345")
        self.assertFalse(result.success)
        self.assertEqual(result.failure_kind, KIND_INVALID_CREDENTIALS)


class VerifyOtpFlowTests(_OtpStoreCase):
    def _issue(self, phone: str, code: str):
        from app.auth.otp.service import PURPOSE_AUTH_API, request_otp

        with mock.patch("app.auth.otp.service.generate_otp", return_value=code):
            with mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=SMS_OK):
                return request_otp(phone=phone, purpose=PURPOSE_AUTH_API, digits=5, ip="1.1.1.1")

    def test_request_otp(self) -> None:
        issued = self._issue("09121234567", "58321")
        self.assertTrue(issued.accepted)

    def test_invalid_otp(self) -> None:
        from app.auth.otp.errors import OTP_INVALID
        from app.auth.otp.service import PURPOSE_AUTH_API, verify_otp

        self._issue("09121234567", "58321")
        result = verify_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, code="00000", digits=5)
        self.assertFalse(result.ok)
        self.assertEqual(result.error, OTP_INVALID)

    def test_expired_otp(self) -> None:
        from app.auth.otp.errors import OTP_EXPIRED
        from app.auth.otp.service import PURPOSE_AUTH_API, verify_otp
        from app.auth.otp.store import create_challenge

        create_challenge(phone="09121234567", purpose=PURPOSE_AUTH_API, code="11111", ttl_seconds=-1)
        result = verify_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, code="11111", digits=5)
        self.assertEqual(result.error, OTP_EXPIRED)

    def test_used_otp(self) -> None:
        from app.auth.otp.errors import OTP_ALREADY_USED
        from app.auth.otp.service import PURPOSE_AUTH_API, verify_otp

        self._issue("09121234567", "22222")
        first = verify_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, code="22222", digits=5)
        second = verify_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, code="22222", digits=5)
        self.assertTrue(first.ok)
        self.assertEqual(second.error, OTP_ALREADY_USED)

    def test_latest_otp_only(self) -> None:
        from app.auth.otp.service import PURPOSE_AUTH_API, request_otp, verify_otp

        with mock.patch("app.auth.otp.service.otp_resend_cooldown_seconds", return_value=0):
            with mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=SMS_OK):
                with mock.patch("app.auth.otp.service.generate_otp", side_effect=["11111", "22222"]):
                    request_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, digits=5, ip="1.1.1.1")
                    request_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, digits=5, ip="1.1.1.1")
        old = verify_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, code="11111", digits=5)
        new = verify_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, code="22222", digits=5)
        self.assertFalse(old.ok)
        self.assertTrue(new.ok)

    def test_max_attempts(self) -> None:
        from app.auth.otp.errors import OTP_TOO_MANY_ATTEMPTS
        from app.auth.otp.service import PURPOSE_AUTH_API, verify_otp

        self._issue("09121234567", "33333")
        last = None
        for _ in range(5):
            last = verify_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, code="00000", digits=5)
        self.assertEqual(last.error, OTP_TOO_MANY_ATTEMPTS)
        locked = verify_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, code="33333", digits=5)
        self.assertEqual(locked.error, OTP_TOO_MANY_ATTEMPTS)

    def test_resend_cooldown(self) -> None:
        from app.auth.otp.errors import OTP_COOLDOWN
        from app.auth.otp.service import PURPOSE_AUTH_API, request_otp

        with mock.patch("app.auth.otp.service.generate_otp", return_value="44444"):
            with mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=SMS_OK):
                first = request_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, digits=5, ip="1.1.1.1")
                second = request_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, digits=5, ip="1.1.1.1")
        self.assertTrue(first.accepted)
        self.assertEqual(second.error, OTP_COOLDOWN)


class SecurityOtpTests(_OtpStoreCase):
    def test_otp_replay(self) -> None:
        from app.auth.otp.errors import OTP_ALREADY_USED
        from app.auth.otp.service import PURPOSE_AUTH_API, request_otp, verify_otp

        with mock.patch("app.auth.otp.service.generate_otp", return_value="55555"):
            with mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=SMS_OK):
                request_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, digits=5, ip="8.8.8.8")
        self.assertTrue(verify_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, code="55555", digits=5).ok)
        self.assertEqual(
            verify_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, code="55555", digits=5).error,
            OTP_ALREADY_USED,
        )

    def test_concurrent_verify(self) -> None:
        from app.auth.otp.service import PURPOSE_AUTH_API, request_otp, verify_otp

        with mock.patch("app.auth.otp.service.generate_otp", return_value="66666"):
            with mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=SMS_OK):
                request_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, digits=5, ip="8.8.8.8")
        results: list[bool] = []

        def _run() -> None:
            results.append(verify_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, code="66666", digits=5).ok)

        threads = [threading.Thread(target=_run) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(1 for ok in results if ok), 1)
        self.assertEqual(len(results), 10)

    def test_rate_limit_phone(self) -> None:
        from app.auth.otp.errors import OTP_RATE_LIMITED
        from app.auth.otp.service import PURPOSE_AUTH_API, request_otp

        with mock.patch("app.auth.otp.service.otp_phone_hourly_limit", return_value=1):
            with mock.patch("app.auth.otp.service.otp_resend_cooldown_seconds", return_value=0):
                with mock.patch("app.auth.otp.service.generate_otp", return_value="77777"):
                    with mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=SMS_OK):
                        first = request_otp(phone="09120000001", purpose=PURPOSE_AUTH_API, digits=5, ip="9.9.9.9")
                        second = request_otp(phone="09120000001", purpose=PURPOSE_AUTH_API, digits=5, ip="9.9.9.9")
        self.assertTrue(first.accepted)
        self.assertEqual(second.error, OTP_RATE_LIMITED)

    def test_rate_limit_ip(self) -> None:
        from app.auth.otp.errors import OTP_RATE_LIMITED
        from app.auth.otp.service import PURPOSE_AUTH_API, request_otp

        with mock.patch("app.auth.otp.service.otp_ip_hourly_limit", return_value=1):
            with mock.patch("app.auth.otp.service.otp_resend_cooldown_seconds", return_value=0):
                with mock.patch("app.auth.otp.service.otp_phone_hourly_limit", return_value=50):
                    with mock.patch("app.auth.otp.service.generate_otp", return_value="88888"):
                        with mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=SMS_OK):
                            first = request_otp(phone="09120000001", purpose=PURPOSE_AUTH_API, digits=5, ip="7.7.7.7")
                            second = request_otp(phone="09120000002", purpose=PURPOSE_AUTH_API, digits=5, ip="7.7.7.7")
        self.assertTrue(first.accepted)
        self.assertEqual(second.error, OTP_RATE_LIMITED)

    def test_otp_not_logged(self) -> None:
        from app.auth.otp.service import PURPOSE_AUTH_API, request_otp

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        log = logging.getLogger("app.auth.otp")
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        try:
            with mock.patch("app.auth.otp.service.generate_otp", return_value="99999"):
                with mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=SMS_OK):
                    request_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, digits=5, ip="1.2.3.4")
        finally:
            log.removeHandler(handler)
        dumped = stream.getvalue()
        self.assertNotIn("99999", dumped)
        self.assertNotIn("09121234567", dumped)

    def test_secret_not_logged(self) -> None:
        from app.auth.otp.config import log_otp_startup

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        log = logging.getLogger("otp.secretcheck")
        log.addHandler(handler)
        log.setLevel(logging.DEBUG)
        try:
            log_otp_startup(log)
        finally:
            log.removeHandler(handler)
        dumped = stream.getvalue()
        self.assertNotIn("test-otp-hmac-secret", dumped)
        self.assertNotIn("test-session-secret", dumped)


class AuthApiTests(_OtpStoreCase):
    def _app(self) -> Flask:
        app = Flask(__name__, instance_path=self.tmp)
        app.secret_key = "test-session-secret"
        app.config["TESTING"] = True
        from app.auth.otp.routes import auth_otp_bp

        app.register_blueprint(auth_otp_bp)
        return app

    def test_cooldown_message_names_the_wait(self) -> None:
        app = self._app()
        with mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=SMS_OK):
            client = app.test_client()
            first = client.post("/auth/request-otp", json={"phone": "09120000001"})
            second = client.post("/auth/request-otp", json={"phone": "09120000001"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        body = second.get_json()
        self.assertEqual(body["error"], "OTP_COOLDOWN")
        self.assertIn("ثانیه", body["message"])
        self.assertIn("retry_after", body)

    def test_user_enumeration(self) -> None:
        app = self._app()
        with mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=SMS_OK):
            client = app.test_client()
            a = client.post("/auth/request-otp", json={"phone": "09120000001"})
            b = client.post("/auth/request-otp", json={"phone": "09120000002"})
        self.assertEqual(a.status_code, 200)
        self.assertEqual(b.status_code, 200)
        self.assertEqual(a.get_json().get("message"), b.get_json().get("message"))

    def test_session_creation(self) -> None:
        from app.auth.otp.service import PURPOSE_AUTH_API, request_otp

        with mock.patch("app.auth.otp.service.generate_otp", return_value="12121"):
            with mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=SMS_OK):
                request_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, digits=5, ip="1.1.1.1")
        app = self._app()
        with mock.patch("app.express_partner.routes._finalize_partner_login", return_value="/express/partner/"):
            r = app.test_client().post("/auth/verify-otp", json={"phone": "09121234567", "code": "12121"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json().get("success"))

    def test_logout(self) -> None:
        app = self._app()

        @app.post("/logout-test")
        def _logout_test():
            from flask import jsonify, session

            session["user_phone"] = "09121234567"
            session["user_id"] = "09121234567"
            session.pop("user_phone", None)
            session.pop("user_id", None)
            return jsonify({"ok": True, "logged_in": bool(session.get("user_phone"))})

        r = app.test_client().post("/logout-test")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.get_json().get("logged_in"))

    def test_delivery_failure_includes_gateway(self) -> None:
        failed = OTPDeliveryResult(
            success=False,
            provider="sms",
            failure_kind=KIND_FAILED,
            error_code="FAILED",
            gateway={
                "attempts": [
                    {
                        "path": "verify",
                        "http": 200,
                        "status": 113,
                        "message": "قالب پیدا نشد",
                        "message_id": "",
                        "duration_ms": 40,
                    }
                ]
            },
        )
        app = self._app()
        with mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=failed):
            resp = app.test_client().post("/auth/request-otp", json={"phone": "09120000009"})
        self.assertEqual(resp.status_code, 502)
        body = resp.get_json()
        self.assertEqual(body["error"], "OTP_DELIVERY_FAILED")
        self.assertEqual(body["gateway"]["attempts"][0]["status"], 113)
        self.assertNotIn("لطفاً کمی صبر کنید و دوباره تلاش کنید.", body["message"])

    def test_gateway_log_scrubs_the_code(self) -> None:
        from app.auth.otp.send_log import recent_attempts
        from app.services.sms import send_sms_code

        body = {"status": 16, "message": "bad 12345 for 09121234567", "data": {"messageId": 99887766}}
        with mock.patch("app.services.sms.get_sms_api_key", return_value="test-key"):
            with mock.patch(
                "app.services.sms._send_otp_verify",
                return_value={"ok": False, "status": 400, "body": body},
            ):
                with mock.patch(
                    "app.services.sms.send_sms_direct",
                    return_value={"ok": False, "status": 200, "body": {"status": 102, "message": "credit"}},
                ):
                    result = send_sms_code("09121234567", "12345", record_history=False)
        dumped = str(result["attempts"])
        self.assertNotIn("12345", dumped)
        self.assertNotIn("09121234567", dumped)
        self.assertEqual(result["attempts"][0]["path"], "verify")
        self.assertEqual(result["attempts"][1]["path"], "service_line")
        logged = str(recent_attempts())
        self.assertNotIn("12345", logged)
        self.assertNotIn("09121234567", logged)
        self.assertIn("4567", logged)

    def test_healthz_otp_requires_the_webhook_secret(self) -> None:
        from flask import Flask

        from app.routes.public import healthz_otp

        app = Flask(__name__, instance_path=self.tmp)
        app.config["TESTING"] = True
        app.add_url_rule("/healthz/otp", view_func=healthz_otp)
        client = app.test_client()
        with mock.patch.dict(os.environ, {"VINOR_WEBHOOK_SECRET": "ci-only-not-secret"}):
            denied = client.get("/healthz/otp")
            self.assertEqual(denied.status_code, 401)
            with mock.patch(
                "app.auth.otp.send_log.fetch_sms_ir_account",
                return_value={"credit": {"http": 200, "body": {"status": 1, "data": 12}}, "lines": None},
            ):
                allowed = client.get("/healthz/otp", headers={"X-Vinor-Otp-Diag": "ci-only-not-secret"})
        self.assertEqual(allowed.status_code, 200)
        text = allowed.get_data(as_text=True)
        self.assertNotIn("ci-only-not-secret", text)
        self.assertIn("attempts", allowed.get_json())

    def test_partner_wait_copy_names_the_reason(self) -> None:
        from app.auth.otp.errors import OTP_COOLDOWN, OTP_RATE_LIMITED
        from app.express_partner.routes import _partner_otp_fail_payload

        cooldown, status = _partner_otp_fail_payload(OTP_COOLDOWN, 45)
        limited, limited_status = _partner_otp_fail_payload(OTP_RATE_LIMITED)
        self.assertEqual(status, 429)
        self.assertEqual(limited_status, 429)
        self.assertIn("45", cooldown)
        self.assertNotIn("لطفاً کمی صبر کنید و دوباره تلاش کنید.", cooldown)
        self.assertNotIn("لطفاً کمی صبر کنید و دوباره تلاش کنید.", limited)


class DeliveryAndE2ETests(_OtpStoreCase):
    def test_rejected_send_does_not_start_cooldown(self) -> None:
        from app.auth.otp.service import PURPOSE_AUTH_API, request_otp

        with mock.patch("app.auth.otp.service.generate_otp", side_effect=["13131", "14141"]):
            with mock.patch("app.auth.otp.dispatch.dispatch_otp", side_effect=[SMS_FAIL, SMS_OK]):
                first = request_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, digits=5, ip="203.0.113.8")
                second = request_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, digits=5, ip="203.0.113.8")
        self.assertFalse(first.accepted)
        self.assertTrue(second.accepted)

    def test_timeout_still_starts_cooldown(self) -> None:
        from app.auth.otp.errors import OTP_COOLDOWN, OTP_PROVIDER_UNAVAILABLE
        from app.auth.otp.service import PURPOSE_AUTH_API, request_otp

        with mock.patch("app.auth.otp.service.generate_otp", return_value="15151"):
            with mock.patch("app.auth.otp.dispatch.dispatch_otp", side_effect=[SMS_TIMEOUT, SMS_OK]):
                first = request_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, digits=5, ip="203.0.113.9")
                second = request_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, digits=5, ip="203.0.113.9")
        self.assertEqual(first.error, OTP_PROVIDER_UNAVAILABLE)
        self.assertEqual(second.error, OTP_COOLDOWN)

    def test_loopback_is_not_one_shared_bucket(self) -> None:
        from app.auth.otp.service import PURPOSE_AUTH_API, request_otp

        with mock.patch("app.auth.otp.service.otp_ip_hourly_limit", return_value=1):
            with mock.patch("app.auth.otp.service.otp_resend_cooldown_seconds", return_value=0):
                with mock.patch("app.auth.otp.service.generate_otp", return_value="16161"):
                    with mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=SMS_OK):
                        first = request_otp(phone="09120000001", purpose=PURPOSE_AUTH_API, digits=5, ip="127.0.0.1")
                        second = request_otp(phone="09120000002", purpose=PURPOSE_AUTH_API, digits=5, ip="127.0.0.1")
        self.assertTrue(first.accepted)
        self.assertTrue(second.accepted)

    def test_sms_delivery_failure_not_assumed_success(self) -> None:
        from app.auth.otp.errors import OTP_DELIVERY_FAILED
        from app.auth.otp.service import PURPOSE_AUTH_API, request_otp

        with mock.patch("app.auth.otp.service.generate_otp", return_value="13131"):
            with mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=SMS_FAIL):
                issued = request_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, digits=5, ip="1.1.1.1")
        self.assertFalse(issued.accepted)
        self.assertEqual(issued.error, OTP_DELIVERY_FAILED)

    def test_browser_e2e(self) -> None:
        from app.auth.otp.service import PURPOSE_AUTH_API, request_otp, verify_otp

        with mock.patch("app.auth.otp.service.generate_otp", return_value="14141"):
            with mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=SMS_OK):
                issued = request_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, digits=5, ip="1.1.1.1")
        self.assertTrue(issued.accepted)
        self.assertTrue(verify_otp(phone="09121234567", purpose=PURPOSE_AUTH_API, code="14141", digits=5).ok)

    def test_android_e2e(self) -> None:
        from app.auth.otp.service import PURPOSE_PARTNER, request_otp, verify_otp

        with mock.patch("app.auth.otp.service.generate_otp", return_value="15151"):
            with mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=SMS_OK):
                issued = request_otp(phone="09121234567", purpose=PURPOSE_PARTNER, digits=5, ip="1.1.1.1")
        self.assertTrue(issued.accepted)
        self.assertTrue(verify_otp(phone="09121234567", purpose=PURPOSE_PARTNER, code="15151", digits=5).ok)

    def test_admin_e2e(self) -> None:
        from app.auth.otp.service import PURPOSE_ADMIN, request_otp, verify_otp

        with mock.patch("app.auth.otp.service.generate_otp", return_value="16161"):
            with mock.patch("app.auth.otp.dispatch.dispatch_otp", return_value=SMS_OK):
                issued = request_otp(phone="09121471301", purpose=PURPOSE_ADMIN, digits=5, ip="1.1.1.1")
        self.assertTrue(issued.accepted)
        self.assertTrue(verify_otp(phone="09121471301", purpose=PURPOSE_ADMIN, code="16161", digits=5).ok)


if __name__ == "__main__":
    unittest.main()
