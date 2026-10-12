# -*- coding: utf-8 -*-
"""تقویم بازدید در وضعیت معاملهٔ جزئیات."""


def test_schedule_payload_has_calendar_fields():
    from app.express_partner.visit_requests import visit_schedule_for_land

    payload = visit_schedule_for_land("no-such-code")
    assert payload["visit_request_url"] == "/express/partner/visit-requests/no-such-code"
    assert payload["visit_date_min"]
    assert isinstance(payload["visit_allowed_weekdays"], list)
    assert payload["visit_allowed_hours"]
    assert all(isinstance(hour, int) for hour in payload["visit_allowed_hours"])
