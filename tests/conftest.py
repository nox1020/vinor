"""Dummy required env for pytest, including fork PRs with no secrets.

Assigned at import time so values exist before test modules import or create
the Flask app. ``setdefault`` keeps an explicit CI or fixture value.
"""
from __future__ import annotations

import os
import tempfile

# Absolute file so the URI is sqlite:////<abs>/vinor-pytest.db, never sqlite:///relative.db.
_PYTEST_DB = os.path.abspath(os.path.join(tempfile.gettempdir(), "vinor-pytest.db"))

os.environ.setdefault("SECRET_KEY", "pytest-dummy-secret-key")
os.environ.setdefault("SMS_API_KEY", "pytest-dummy-sms-api-key")
os.environ.setdefault("VAPID_PRIVATE_KEY", "pytest-dummy-vapid-private")
os.environ.setdefault("VAPID_PUBLIC_KEY", "pytest-dummy-vapid-public")
os.environ.setdefault("DATABASE_URL", "sqlite:///" + _PYTEST_DB)
os.environ.setdefault("VINOR_WEBHOOK_SECRET", "pytest-dummy-webhook-secret")
# Tests point DATABASE_URL at sqlite files that do not exist yet.
os.environ.setdefault("VINOR_DB_CREATE_ALL", "1")
