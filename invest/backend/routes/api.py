# -*- coding: utf-8 -*-
"""REST API Invest — /invest/api/v1/*"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from invest_app.models.asset import Asset
from invest_app.models.settings import AppSettings

from ..config import diag_override, invest_api_version, market_index_db_path
from ..auth import current_invest_phone, require_invest_auth
from ..context import close_request_context, get_request_context
from ..serializers import asset_to_dict, metrics_to_dict, settings_to_dict, trade_to_dict
from ..users import get_or_create_profile, update_profile

invest_api_bp = Blueprint("invest_api", __name__, url_prefix="/invest/api/v1")

_market_index_service = None


def _market_index():
    """Process-wide shared market index service."""
    override = diag_override() or {}
    if override.get("market") is not None:
        return override["market"]
    global _market_index_service
    if _market_index_service is None:
        from invest_app.services.market_index_service import MarketIndexService
        from invest_app.services.market_index_store import MarketIndexStore

        store = MarketIndexStore(market_index_db_path())
        _market_index_service = MarketIndexService(store)
    return _market_index_service


def _sync_portfolio_quotes_from_index(ctx, essentials: list) -> None:
    """Reuse index USDT/gold into portfolio live rates when present."""
    if not essentials:
        return
    by_id = {
        str(item.get("id") or ""): item
        for item in essentials
        if isinstance(item, dict)
    }
    usdt = by_id.get("usdt") or {}
    gold = by_id.get("gold") or {}
    try:
        usdt_price = float(usdt.get("price") or 0)
    except (TypeError, ValueError):
        usdt_price = 0.0
    try:
        gold_price = float(gold.get("price") or 0)
    except (TypeError, ValueError):
        gold_price = 0.0
    if usdt_price > 0:
        ctx.fx.apply_fetched_rate(usdt_price, source="market_index")
    if gold_price > 0:
        ctx.market.apply_fetched_gold(gold_price, source="market_index")
    ctx.persist_live_quotes()


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
    bundle = _market_index().get_bundle(force=False)
    essentials = bundle.get("essentials") or []
    by_id = {
        str(item.get("id") or ""): item
        for item in essentials
        if isinstance(item, dict)
    }

    def _price(key: str) -> float | None:
        try:
            value = float((by_id.get(key) or {}).get("price") or 0)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    usdt = _price("usdt")
    gold = _price("gold")
    if usdt:
        ctx.fx.apply_fetched_rate(usdt, source="market_index")
    if gold:
        ctx.market.apply_fetched_gold(gold, source="market_index")
    if not usdt:
        usdt = ctx.fx.get_usdt_tmn(force=False)
    if not gold:
        gold = ctx.market.get_gold_toman(force=False)
    ctx.persist_live_quotes()
    return _json_ok(
        usdt_tmn=ctx.fx.usdt_tmn,
        gold_tmn_per_gram=ctx.market.gold_toman_per_gram,
        stale=bool(bundle.get("stale")),
    )


@invest_api_bp.get("/markets/index")
@require_invest_auth
def markets_index():
    """Full شاخص snapshot (essentials + Wallex + inflation), server-cached ~1m."""
    ctx = get_request_context()
    force = (request.args.get("force") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    svc = _market_index()
    bundle = svc.get_bundle(force=force)
    essentials = bundle.get("essentials") or []
    try:
        _sync_portfolio_quotes_from_index(ctx, essentials)
    except Exception:
        pass
    return _json_ok(
        essentials=essentials,
        wallex_markets=bundle.get("wallex_markets") or [],
        inflation=bundle.get("inflation"),
        updated_at=bundle.get("updated_at"),
        stale=bool(bundle.get("stale")),
        warning=bundle.get("warning"),
        error=bundle.get("error"),
        source=bundle.get("source"),
    )


@invest_api_bp.post("/markets/index")
@require_invest_auth
def markets_index_ingest():
    """Accept a client-built snapshot and persist it on the shared store."""
    data = request.get_json(silent=True) or {}
    svc = _market_index()
    bundle = svc.ingest_client_bundle(data)
    ctx = get_request_context()
    try:
        _sync_portfolio_quotes_from_index(ctx, bundle.get("essentials") or [])
    except Exception:
        pass
    return _json_ok(
        essentials=bundle.get("essentials") or [],
        wallex_markets=bundle.get("wallex_markets") or [],
        inflation=bundle.get("inflation"),
        updated_at=bundle.get("updated_at"),
        source=bundle.get("source") or "client",
    )


@invest_api_bp.get("/markets/history")
@require_invest_auth
def markets_history():
    """Minute ticks of essentials stored on the backend."""
    try:
        hours = float(request.args.get("hours") or 24)
    except (TypeError, ValueError):
        hours = 24.0
    hours = max(1.0, min(hours, 24 * 14))
    ticks = _market_index().history(hours=hours)
    return _json_ok(items=ticks, hours=hours)


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


def _update_open_trade(trade_id: int):
    ctx = get_request_context()
    data = request.get_json(silent=True) or {}
    try:
        trade = ctx.trades.update_open_trade(
            trade_id,
            quantity=float(data["quantity"]) if data.get("quantity") is not None else None,
            buy_price=float(data["buy_price"]) if data.get("buy_price") is not None else None,
            buy_fee=float(data["buy_fee"]) if data.get("buy_fee") is not None else None,
            buy_date=data.get("buy_date"),
            buy_note=data.get("buy_note"),
        )
        ctx.invalidate_caches()
        return _json_ok(item=trade_to_dict(trade))
    except ValueError as exc:
        msg = str(exc)
        if "یافت نشد" in msg:
            return _json_err(msg, error="not_found", status=404)
        return _json_err(msg)
    except (TypeError,) as exc:
        return _json_err(str(exc))


@invest_api_bp.patch("/trades/<int:trade_id>")
@require_invest_auth
def update_open_trade(trade_id: int):
    return _update_open_trade(trade_id)


@invest_api_bp.put("/trades/<int:trade_id>")
@require_invest_auth
def update_open_trade_put(trade_id: int):
    return _update_open_trade(trade_id)


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
    payload = settings_to_dict(ctx.settings)
    try:
        from invest_app.config import SETTING_GOLD_TMN_PER_GRAM, SETTING_USDT_TMN_RATE

        usdt = ctx.settings_repo.get(SETTING_USDT_TMN_RATE)
        gold = ctx.settings_repo.get(SETTING_GOLD_TMN_PER_GRAM)
        if usdt not in (None, ""):
            payload["usdt_tmn_rate"] = float(usdt)
        if gold not in (None, ""):
            payload["gold_tmn_per_gram"] = float(gold)
    except (TypeError, ValueError):
        pass
    _attach_annual_withdrawal_pct(ctx, payload)
    _attach_client_extras(ctx, payload)
    _attach_client_checks(ctx, payload, None)
    return _json_ok(settings=payload)


_ANNUAL_PCT_KEY = "annual_withdrawal_pct"


def _attach_annual_withdrawal_pct(ctx, payload: dict) -> None:
    raw = ctx.settings_repo.get(_ANNUAL_PCT_KEY)
    try:
        if raw not in (None, ""):
            payload[_ANNUAL_PCT_KEY] = max(1, min(100, int(float(raw))))
    except (TypeError, ValueError):
        pass


# کلیدهایی که فقط اپ موبایل می‌فرستد و قبلاً سرور دور می‌ریخت. افزودنی در جدول settings
# با پیشوند جدا ذخیره می‌شوند و در GET/PUT برگردانده می‌شوند.
_CLIENT_LIST_KEYS = ("client_withdrawals", "price_alerts", "profit_alerts", "year_nav_history")
_CLIENT_BOOL_KEYS = ("notify_background", "app_lock_biometric")
_CLIENT_TEXT_KEYS = ("app_lock_hash",)
_CLIENT_PREFIX = "client_ext:"
_CLIENT_MAX_BYTES = 2_000_000


def _parse_client_extras(data: dict) -> tuple[dict, str | None]:
    import json

    out: dict = {}
    for key in _CLIENT_LIST_KEYS:
        if key not in data:
            continue
        val = data.get(key)
        if isinstance(val, str):
            try:
                val = json.loads(val) if val.strip() else []
            except ValueError:
                return {}, f"مقدار {key} نامعتبر است."
        if val is None:
            val = []
        if not isinstance(val, list) or not all(isinstance(x, dict) for x in val):
            return {}, f"مقدار {key} باید فهرست باشد."
        text = json.dumps(val, ensure_ascii=False)
        if len(text.encode()) > _CLIENT_MAX_BYTES:
            return {}, f"حجم {key} بیش از حد مجاز است."
        out[key] = text
    for key in _CLIENT_BOOL_KEYS:
        if key not in data:
            continue
        val = data.get(key)
        if isinstance(val, str) and val.strip().lower() in ("1", "true", "0", "false", "yes", "no", "on", "off"):
            val = val.strip().lower() in ("1", "true", "yes", "on")
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val in (0, 1):
            val = bool(val)
        if not isinstance(val, bool):
            return {}, f"مقدار {key} باید درست/نادرست باشد."
        out[key] = "1" if val else "0"
    for key in _CLIENT_TEXT_KEYS:
        if key not in data:
            continue
        val = data.get(key)
        val = "" if val is None else val
        if not isinstance(val, str) or len(val) > 512:
            return {}, f"مقدار {key} نامعتبر است."
        out[key] = val.strip()
    return out, None


def _attach_client_extras(ctx, payload: dict) -> None:
    import json

    for key in _CLIENT_LIST_KEYS:
        raw = ctx.settings_repo.get(_CLIENT_PREFIX + key)
        if raw is None:
            continue
        try:
            payload[key] = json.loads(raw)
        except ValueError:
            continue
    for key in _CLIENT_BOOL_KEYS:
        raw = ctx.settings_repo.get(_CLIENT_PREFIX + key)
        if raw is not None:
            payload[key] = raw == "1"
    for key in _CLIENT_TEXT_KEYS:
        raw = ctx.settings_repo.get(_CLIENT_PREFIX + key)
        if raw is not None:
            payload[key] = raw


def _attach_client_checks(ctx, payload: dict, incoming) -> None:
    """آینهٔ client_checks برای اپ فعلی. دفتر خالی تا اولین همگام‌سازی برنمی‌گردد."""
    from invest_app.services.check_service import CheckError, CheckService

    service = CheckService(ctx.conn)
    if isinstance(incoming, dict) and "client_checks" in incoming:
        raw = incoming.get("client_checks")
        if isinstance(raw, str):
            try:
                import json
                raw = json.loads(raw)
            except (TypeError, ValueError):
                raw = None
        if not isinstance(raw, list):
            payload["client_checks_error"] = {
                "error": "validation",
                "message": "فهرست چک‌ها نامعتبر است.",
            }
            if service.synced():
                payload["client_checks"] = service.list_public()
            return
        try:
            payload["client_checks"] = service.replace_snapshot(raw)
        except CheckError as exc:
            payload["client_checks_error"] = {"error": exc.code, "message": exc.message}
            if service.synced():
                payload["client_checks"] = service.list_public()
        return
    if service.synced():
        payload["client_checks"] = service.list_public()


@invest_api_bp.put("/settings")
@require_invest_auth
def put_settings():
    ctx = get_request_context()
    data = request.get_json(silent=True) or {}
    extras, extras_error = _parse_client_extras(data)
    if extras_error:
        return _json_err(extras_error, error="validation")
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
    if "notifications_enabled" in data:
        s.notifications_enabled = bool(data["notifications_enabled"])
    if "notify_trades" in data:
        s.notify_trades = bool(data["notify_trades"])
    if "notify_withdrawals" in data:
        s.notify_withdrawals = bool(data["notify_withdrawals"])
    if "notify_price_moves" in data:
        s.notify_price_moves = bool(data["notify_price_moves"])
    if "wallex_markets_url" in data:
        url = str(data.get("wallex_markets_url") or "").strip()
        if url:
            s.wallex_markets_url = url
    if "persiantoolbox_url" in data:
        url = str(data.get("persiantoolbox_url") or "").strip()
        if url:
            s.persiantoolbox_url = url
    annual_pct_error = None
    if _ANNUAL_PCT_KEY in data:
        try:
            pct = float(data.get(_ANNUAL_PCT_KEY))
            if pct != pct or pct < 1 or pct > 100:
                raise ValueError
            ctx.settings_repo.set(_ANNUAL_PCT_KEY, str(int(round(pct))))
        except (TypeError, ValueError):
            annual_pct_error = "درصد برداشت سالانه باید بین ۱ تا ۱۰۰ باشد."
    if annual_pct_error:
        return _json_err(annual_pct_error, error="validation")
    if extras:
        ctx.settings_repo.set_many({_CLIENT_PREFIX + k: v for k, v in extras.items()})
    ctx.save_settings(s)
    # Optional cached rates (also written by /quotes).
    if "usdt_tmn_rate" in data and data.get("usdt_tmn_rate") not in (None, ""):
        try:
            from invest_app.config import SETTING_USDT_TMN_RATE

            ctx.settings_repo.set(
                SETTING_USDT_TMN_RATE, f"{float(data['usdt_tmn_rate']):.4f}"
            )
        except (TypeError, ValueError):
            pass
    if "gold_tmn_per_gram" in data and data.get("gold_tmn_per_gram") not in (
        None,
        "",
    ):
        try:
            from invest_app.config import SETTING_GOLD_TMN_PER_GRAM

            ctx.settings_repo.set(
                SETTING_GOLD_TMN_PER_GRAM,
                f"{float(data['gold_tmn_per_gram']):.4f}",
            )
        except (TypeError, ValueError):
            pass
    ctx.apply_price_api_settings()
    phone = current_invest_phone()
    if phone and "first_run_done" in data:
        update_profile(phone, first_run_done=bool(data["first_run_done"]))
    payload = settings_to_dict(ctx.settings)
    _attach_annual_withdrawal_pct(ctx, payload)
    _attach_client_extras(ctx, payload)
    _attach_client_checks(ctx, payload, data)
    return _json_ok(settings=payload)


from ..checks_api import register_check_routes

register_check_routes()

from ..pwo_api import register_pwo_routes  # noqa: E402

register_pwo_routes()


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

from ..biz_api import register_biz_routes  # noqa: E402

register_biz_routes()
