# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

KIND_SUCCESS = "SUCCESS"
KIND_FAILED = "FAILED"
KIND_TIMEOUT = "TIMEOUT"
KIND_RATE_LIMITED = "RATE_LIMITED"
KIND_INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
KIND_INVALID_PHONE = "INVALID_PHONE"
KIND_SERVER_ERROR = "SERVER_ERROR"
KIND_UNEXPECTED = "UNEXPECTED"


@dataclass(frozen=True)
class OTPDeliveryResult:
    success: bool
    provider: str
    request_id: str = ""
    error_code: str = ""
    retryable: bool = False
    configured: bool = True
    failure_kind: str = ""
    gateway: dict | None = None


class SMSProvider(Protocol):
    name: str

    def send_otp(self, phone: str, code: str, *, request_id: str = "") -> OTPDeliveryResult:
        ...


OTPProvider = SMSProvider
