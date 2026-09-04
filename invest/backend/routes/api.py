# -*- coding: utf-8 -*-
"""REST API Invest — /invest/api/v1/*"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from invest_app.models.asset import Asset
from invest_app.models.settings import AppSettings

from ..config import invest_api_version
from ..auth import current_invest_phone, require_invest_auth
from ..context import close_request_context, get_request_context
from ..serializers import asset_to_dict, metrics_to_dict, settings_to_dict, trade_to_dict
from ..users import get_or_create_profile, update_profile

invest_api_bp = Blueprint("invest_api", __name__, url_prefix="/invest/api/v1")


@invest_api_bp.teardown_request
def _teardown_invest_ctx(exc):
    close_request_context()


def _json_ok(**payload):
    return jsonify({"success": True, **payload})


def _json_err(message: str, *, error: str = "error", status: int = 400):
    return jsonify({"success": False, "error": error, "message": message}), status


@invest_api_bp.get("/health")
def health():
    return _json_ok(service="invest", status="ok", api_version=invest_api_version())


@invest_api_bp.get("/app-version")
def app_version():
    return _json_ok(api_version=invest_api_version())


@invest_api_bp.get("/auth/status")
def auth_status():
    phone = current_invest_phone()
    if not phone:
        return _json_ok(authenticated=False)
    return _json_ok(authenticated=True, phone=phone, profile=get_or_create_profile(phone))


@invest_api_bp.get("/me")
@require_invest_auth
def me():
    phone = current_invest_phone()
    ctx = get_request_context()
    profile = get_or_create_profile(phone)
    return _json_ok(
        profile=profile,
        settings=settings_to_dict(ctx.settings),
    )


@invest_api_bp.patch("/me")
@require_invest_auth
def patch_me():
    phone = current_invest_phone()
    data = request.get_json(silent=True) or {}
    profile = update_profile(
        phone,
        name=data.get("name"),
        first_run_done=data.get("first_run_done"),
    )
    return _json_ok(profile=profile)


@invest_api_bp.get("/dashboard")
@require_invest_auth
def dashboard():
    ctx = get_request_context()
    ctx.sync_live_prices_to_portfolio()
    ctx.persist_live_quotes()
    data = ctx.dashboard.build(calendar=ctx.settings.calendar)
    m = data.metrics
    return _json_ok(
        metrics=metrics_to_dict(m),
        growth_series=[{"date": d, "value": v} for d, v in data.growth_series],
        assets=[
            {"name": n, "quantity": q, "value": v}
            for n, q, v in data.asset_summary
        ],
        gold_fund={
            "gold_in_g": data.gold_fund.gold_in_g,
            "gold_out_g": data.gold_fund.gold_out_g,
            "gold_holding_g": data.gold_fund.gold_holding_g,
        },
    )


@invest_api_bp.get("/quotes")
@require_invest_auth
def quotes():
    ctx = get_request_context()
    ctx.fx.get_usdt_tmn(force=True)
    ctx.market.refresh(force=True)
    ctx.persist_live_quotes()
    return _json_ok(
        usdt_tmn=ctx.fx.usdt_tmn,
        gold_tmn_per_gram=ctx.market.gold_toman_per_gram,
    )


@invest_api_bp.get("/assets")
@require_invest_auth
def list_assets():
    ctx = get_request_context()
    search = (request.args.get("q") or "").strip()
    assets = ctx.trades.assets.list_all(search)
    return _json_ok(items=[asset_to_dict(a) for a in assets])


@invest_api_bp.post("/assets")
@require_invest_auth
def create_asset():
    ctx = get_request_context()
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return _json_err("نام دارایی الزامی است.")
    asset = Asset(
        id=None,
        name=name,
        symbol=(data.get("symbol") or "").strip(),
        quantity=float(data.get("quantity") or 0),
        avg_buy_price=float(data.get("avg_buy_price") or 0),
        current_price=float(data.get("current_price") or 0),
        notes=(data.get("notes") or "").strip(),
    )
    try:
        saved = ctx.trades.assets.create(asset)
        ctx.invalidate_caches()
        return _json_ok(item=asset_to_dict(saved))
    except Exception as exc:
        return _json_err(str(exc))


@invest_api_bp.put("/assets/<int:asset_id>")
@require_invest_auth
def update_asset(asset_id: int):
    ctx = get_request_context()
    data = request.get_json(silent=True) or {}
    asset = ctx.trades.assets.get(asset_id)
    if not asset:
        return _json_err("دارایی یافت نشد.", error="not_found", status=404)
    if "name" in data:
        asset.name = (data.get("name") or asset.name).strip()
    if "symbol" in data:
        asset.symbol = (data.get("symbol") or "").strip()
    if "quantity" in data:
        asset.quantity = float(data["quantity"])
    if "avg_buy_price" in data:
        asset.avg_buy_price = float(data["avg_buy_price"])
    if "current_price" in data:
        asset.current_price = float(data["current_price"])
    if "notes" in data:
        asset.notes = (data.get("notes") or "").strip()
    try:
        saved = ctx.trades.assets.update(asset)
        ctx.invalidate_caches()
        return _json_ok(item=asset_to_dict(saved))
    except Exception as exc:
        return _json_err(str(exc))


@invest_api_bp.delete("/assets/<int:asset_id>")
@require_invest_auth
def delete_asset(asset_id: int):
    ctx = get_request_context()
    try:
        ctx.trades.assets.delete(asset_id)
        ctx.invalidate_caches()
        return _json_ok(deleted=True, id=asset_id)
    except Exception as exc:
        return _json_err(str(exc))


@invest_api_bp.get("/trades/open")
@require_invest_auth
def trades_open():
    ctx = get_request_context()
    q = (request.args.get("q") or "").strip()
    items = ctx.trades.trades.list_open(q)
    return _json_ok(items=[trade_to_dict(t) for t in items])


@invest_api_bp.get("/trades/closed")
@require_invest_auth
def trades_closed():
    ctx = get_request_context()
    q = (request.args.get("q") or "").strip()
    items = ctx.trades.trades.list_closed(q)
    return _json_ok(items=[trade_to_dict(t) for t in items])


@invest_api_bp.post("/trades/buy")
@require_invest_auth
def trade_buy():
    ctx = get_request_context()
    data = request.get_json(silent=True) or {}
    try:
        trade = ctx.trades.register_buy(
            asset_id=data.get("asset_id"),
            name=(data.get("name") or None),
            symbol=(data.get("symbol") or ""),
            quantity=float(data.get("quantity") or 0),
            buy_price=float(data.get("buy_price") or 0),
            buy_fee=float(data.get("buy_fee") or 0),
            buy_date=data.get("buy_date"),
            buy_note=(data.get("buy_note") or ""),
            current_price=(
                float(data["current_price"]) if data.get("current_price") is not None else None
            ),
        )
        ctx.invalidate_caches()
        return _json_ok(item=trade_to_dict(trade))
    except (TypeError, ValueError) as exc:
        return _json_err(str(exc))


@invest_api_bp.post("/trades/<int:trade_id>/sell")
@require_invest_auth
def trade_sell(trade_id: int):
    ctx = get_request_context()
    data = request.get_json(silent=True) or {}
    try:
        trade = ctx.trades.close_trade(
            trade_id,
            sell_price=float(data.get("sell_price") or 0),
            sell_fee=float(data.get("sell_fee") or 0),
            sell_date=data.get("sell_date"),
            sell_note=(data.get("sell_note") or ""),
            quantity=float(data["quantity"]) if data.get("quantity") is not None else None,
        )
        ctx.invalidate_caches()
        return _json_ok(item=trade_to_dict(trade))
    except (TypeError, ValueError) as exc:
        return _json_err(str(exc))


def _delete_closed_trade(trade_id: int):
    ctx = get_request_context()
    try:
        ctx.trades.delete_closed_trade(trade_id)
        ctx.invalidate_caches()
        return _json_ok(deleted=True, id=trade_id)
    except ValueError as exc:
        msg = str(exc)
        if "یافت نشد" in msg:
            return _json_err(msg, error="not_found", status=404)
        return _json_err(msg)
    except Exception as exc:
        return _json_err(str(exc))


@invest_api_bp.delete("/trades/<int:trade_id>")
@require_invest_auth
def delete_closed_trade(trade_id: int):
    return _delete_closed_trade(trade_id)


@invest_api_bp.post("/trades/<int:trade_id>/delete")
@require_invest_auth
def delete_closed_trade_post(trade_id: int):
    return _delete_closed_trade(trade_id)


@invest_api_bp.get("/settings")
@require_invest_auth
def get_settings():
    ctx = get_request_context()
    return _json_ok(settings=settings_to_dict(ctx.settings))


@invest_api_bp.put("/settings")
@require_invest_auth
def put_settings():
    ctx = get_request_context()
    data = request.get_json(silent=True) or {}
    s = ctx.settings
    if "calendar" in data:
        s.calendar = str(data["calendar"])
    if "currency" in data:
        s.currency = str(data["currency"])
    if "theme" in data:
        s.theme = str(data["theme"])
    if "first_run_done" in data:
        s.first_run_done = bool(data["first_run_done"])
    if "live_prices_enabled" in data:
        s.live_prices_enabled = bool(data["live_prices_enabled"])
    if "usdt_api_enabled" in data:
        s.usdt_api_enabled = bool(data["usdt_api_enabled"])
    if "gold_api_enabled" in data:
        s.gold_api_enabled = bool(data["gold_api_enabled"])
    if "gold_auto_update_assets" in data:
        s.gold_auto_update_assets = bool(data["gold_auto_update_assets"])
    if "price_refresh_seconds" in data:
        s.price_refresh_seconds = int(data["price_refresh_seconds"])
    if "goal_roi_pct" in data:
        raw = data.get("goal_roi_pct")
        s.goal_roi_pct = float(raw) if raw not in (None, "") else None
    ctx.save_settings(s)
    ctx.apply_price_api_settings()
    phone = current_invest_phone()
    if phone and "first_run_done" in data:
        update_profile(phone, first_run_done=bool(data["first_run_done"]))
    return _json_ok(settings=settings_to_dict(ctx.settings))


@invest_api_bp.get("/insights")
@require_invest_auth
def insights():
    ctx = get_request_context()
    ctx.insights.set_goal_roi_pct(ctx.settings.goal_roi_pct)
    bundle = ctx.insights.get_bundle(calendar=ctx.settings.calendar)
    rows = []
    for ins in bundle.insights:
        rows.append({
            "id": ins.id,
            "title": ins.title,
            "summary": ins.summary,
            "description": ins.description,
            "action": ins.action,
            "category": str(ins.category),
            "severity": str(ins.severity),
            "priority": ins.priority,
            "related_assets": list(ins.related_assets),
            "related_trades": list(ins.related_trades),
        })
    return _json_ok(items=rows, generated_at=bundle.generated_at)
