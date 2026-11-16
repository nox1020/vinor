# -*- coding: utf-8 -*-
"""1probot ladder/payment: new Divar promotion API (cost-v2 / flow-v3), RBAC = removed endpoint."""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def dapi(tmp_path, monkeypatch):
    monkeypatch.setenv("PROBOT_DATA_DIR", str(tmp_path / "probot_data"))
    monkeypatch.setenv("PROBOT_AUTOSTART", "0")
    from probot import dapi as mod

    return mod


COST_V2_PAGE = {
    "page": {
        "page": 1,
        "submit_button": {"label": "تکمیل خرید"},
        "widget_list": [
            {"widget_type": "I_TITLE_ROW", "data": {"text": "x"}},
            {"widget_type": "I_COST_ROW", "uid": "reorder",
             "data": {"id": 45090, "name": "نردبان", "price": "94000", "field": {"key": "reorder"}}},
            {"widget_type": "I_COST_ROW", "uid": "auto_ladder_reorder",
             "data": {"id": 45090, "name": "بسته نردبان خودکار", "price": "94000",
                      "field": {"key": "auto_ladder_reorder"}, "options": [{"id": 1}]}},
            {"widget_type": "I_COST_ROW", "uid": "renew-reorder",
             "data": {"id": 54006, "name": "تمدید و نردبان", "price": "110000", "state": "DISABLED",
                      "field": {"key": "renew-reorder"}}},
        ],
    }
}


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload
        self.headers = {}

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload


class _FakeHttp:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def _hit(self, method, url, json_body):
        self.calls.append((method, url, json_body))
        for (m, frag), handler in self.routes.items():
            if m == method and frag in url:
                return handler(json_body) if callable(handler) else handler
        return _Resp(403, "RBAC: access denied")

    def post(self, url, headers=None, cookies=None, json=None, timeout=None, **kw):
        return self._hit("POST", url, json)

    def get(self, url, headers=None, cookies=None, timeout=None, **kw):
        return self._hit("GET", url, None)


def _nardeban(dapi, routes):
    n = object.__new__(dapi.nardeban)
    n.apikey = "test-access-token"
    n.headers = {"Content-Type": "application/json"}
    n.cookies = {}
    n._http = _FakeHttp(routes)
    return n


def test_rbac_means_removed_endpoint_not_ip(dapi):
    assert dapi.is_divar_ip_blocked("HTTP 403: RBAC: access denied")
    msg = dapi.DIVAR_IP_BLOCK_FA
    assert "API جدید دیوار" in msg and "IP" not in msg
    assert dapi.nardeban._error_kind("HTTP 403: RBAC: access denied") == "blocked"


def test_parse_cost_v2_plans(dapi):
    plans = dapi.nardeban.parse_cost_v2_plans(COST_V2_PAGE)
    by_key = {p["key"]: p for p in plans}
    assert by_key["reorder"]["available"] is True
    assert by_key["reorder"]["price"] == 94000 and by_key["reorder"]["id"] == 45090
    assert by_key["auto_ladder_reorder"]["available"] is False  # package
    assert by_key["renew-reorder"]["available"] is False  # DISABLED


def test_select_plan_uses_cost_v2_and_skips_packages(dapi):
    n = _nardeban(dapi, {("POST", "/v8/promotion/cost-v2/"): _Resp(200, COST_V2_PAGE)})
    plan = n.selectPlan("MNG1", priority_1=45090)
    assert plan["key"] == "reorder"
    method, url, body = n._http.calls[0]
    assert url == "https://api.divar.ir/v8/promotion/cost-v2/MNG1"
    assert body == {"specification": {"is_reload": False, "page": 0}, "request_data": {"mng_token": "MNG1"}}
    # no old endpoints are touched
    assert not any("/v8/payment/costs" in c[1] for c in n._http.calls)


def test_create_order_reload_then_submit(dapi):
    def cost(body):
        spec = body["specification"]
        if spec.get("is_reload"):
            return _Resp(200, COST_V2_PAGE)
        return _Resp(200, {"action": {"type": "LOAD_PAGE", "payload": {"url": "/promote/payment-method/ORD123abc"}},
                           "submission_message": "", "token": ""})

    n = _nardeban(dapi, {("POST", "/v8/promotion/cost-v2/"): cost})
    plan = {"id": 45090, "key": "reorder", "price": 94000, "available": True}
    assert n.createOrderID("MNG1", plan) == "ORD123abc"
    reload_body, submit_body = n._http.calls[0][2], n._http.calls[1][2]
    values = {"reorder": {"boolean": {"value": True}}}
    assert reload_body == {"specification": {"data": {"data": values}, "is_reload": True, "page": 1}}
    assert submit_body["request_data"] == {"mng_token": "MNG1"}
    assert submit_body["specification"]["data"]["data"] == values
    assert "is_reload" not in submit_body["specification"]


def test_create_order_unknown_submit_shape_stops_login(dapi):
    def cost(body):
        if body["specification"].get("is_reload"):
            return _Resp(200, COST_V2_PAGE)
        return _Resp(200, {"submission_message": "ok"})

    n = _nardeban(dapi, {("POST", "/v8/promotion/cost-v2/"): cost})
    with pytest.raises(ValueError) as ei:
        n.createOrderID("MNG1", {"id": 45090, "key": "reorder"})
    assert dapi.nardeban._error_kind(str(ei.value)) == "blocked"


def test_find_order_id_variants(dapi):
    f = dapi.nardeban._find_order_id
    assert f({"action": {"payload": {"order_id": "abc12345"}}}) == "abc12345"
    assert f({"a": ["https://divar.ir/x/promote?payment_order_id=zz998877"]}) == "zz998877"
    assert f({"nothing": 1}) is None


def test_flow_v3_body_and_checkout_fallback(dapi):
    flow = {"data": {"option_row_values": [
        {"value": "bazaar", "action": {"payload": {"url": "https://pay.bazaar-pay.ir/x?token=CHK_TOKEN_1234"}}}
    ]}}
    n = _nardeban(dapi, {("POST", "/v8/paymentcore/flow-v3/"): _Resp(200, flow)})
    data = n.createFlow("ORD1")
    method, url, body = n._http.calls[0]
    assert url == "https://api.divar.ir/v8/paymentcore/flow-v3/ORD1"
    assert body == {"order_id": "ORD1", "bazaar_installed_on_device": False,
                    "install_source": "", "last_update_source": ""}
    assert dapi.nardeban._checkout_token_from_flow(data) == "CHK_TOKEN_1234"


def test_rbac_on_select_plan_stops_without_marking_failed(dapi, monkeypatch):
    n = _nardeban(dapi, {})  # everything -> 403 RBAC
    marked = []
    monkeypatch.setattr(n, "_mark_token_failed", lambda *a, **k: marked.append(a), raising=False)
    res = n._try_nardeban_tokens(1, "0912", ["MNG1", "MNG2"])
    assert res[0] == 3 and "API جدید دیوار" in res[2]
    assert marked == []
    assert len(n._http.calls) == 1  # stopped at the first post


def test_reachability_probe_reports_removed(dapi, monkeypatch):
    class S(_FakeHttp):
        pass

    good = S({("POST", "cost-v2"): _Resp(401, {"code": 16}),
              ("POST", "flow-v3"): _Resp(401, {"code": 16}),
              ("GET", "bazaarpay/initiate"): _Resp(401, {"code": 16})})
    monkeypatch.setattr(dapi, "make_divar_http_session", lambda config=None: good)
    assert dapi.check_divar_payment_reachability()["state"] == "reachable"
    bad = S({("POST", "cost-v2"): _Resp(401, {"code": 16})})
    monkeypatch.setattr(dapi, "make_divar_http_session", lambda config=None: bad)
    r = dapi.check_divar_payment_reachability()
    assert r["state"] == "blocked" and "flow-v3" in r["detail"]


def test_web_commands_run_in_bot_process_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("PROBOT_DATA_DIR", str(tmp_path / "probot_data"))
    monkeypatch.setenv("PROBOT_AUTOSTART", "0")
    monkeypatch.delenv("PROBOT_SEPARATE_WORKER", raising=False)
    from probot import bot

    assert bot.separate_worker_enabled() is False
    added = {}
    monkeypatch.setattr(bot.scheduler, "add_job", lambda fn, *a, **k: added.update(fn=fn, **k))
    assert bot.register_inprocess_web_commands() is True
    assert added["id"] == bot.WEB_COMMANDS_JOB_ID and added["max_instances"] == 1
    assert added["fn"] is bot.inprocess_web_commands
    monkeypatch.setenv("PROBOT_SEPARATE_WORKER", "1")
    assert bot.register_inprocess_web_commands() is False
