# -*- coding: utf-8 -*-
"""JSON serializers for Invest API."""
from __future__ import annotations

from typing import Any, Dict

from invest_app.models.asset import Asset
from invest_app.models.trade import Trade
from invest_app.models.settings import AppSettings
from invest_app.services.portfolio_service import DashboardMetrics


def asset_to_dict(a: Asset) -> Dict[str, Any]:
    return {
        "id": a.id,
        "name": a.name,
        "symbol": a.symbol,
        "quantity": a.quantity,
        "avg_buy_price": a.avg_buy_price,
        "current_price": a.current_price,
        "notes": a.notes,
        "total_value": a.total_value,
        "cost_basis": a.cost_basis,
        "unrealized_pnl": a.unrealized_pnl,
        "unrealized_pnl_pct": a.unrealized_pnl_pct,
        "created_at": a.created_at,
        "updated_at": a.updated_at,
    }


def trade_to_dict(t: Trade) -> Dict[str, Any]:
    return {
        "id": t.id,
        "asset_id": t.asset_id,
        "asset_name": t.asset_name,
        "asset_symbol": t.asset_symbol,
        "status": t.status,
        "quantity": t.quantity,
        "buy_price": t.buy_price,
        "buy_fee": t.buy_fee,
        "buy_date": t.buy_date,
        "buy_note": t.buy_note,
        "sell_price": t.sell_price,
        "sell_fee": t.sell_fee,
        "sell_date": t.sell_date,
        "sell_note": t.sell_note,
        "realized_pnl": t.realized_pnl,
        "return_pct": t.return_pct,
        "holding_days": t.holding_days,
        "current_price": t.current_price,
        "current_value": t.current_value,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


def settings_to_dict(s: AppSettings) -> Dict[str, Any]:
    d = s.to_dict()
    return {
        "calendar": s.calendar,
        "currency": s.currency,
        "theme": s.theme,
        "first_run_done": s.first_run_done,
        "live_prices_enabled": s.live_prices_enabled,
        "usdt_api_enabled": s.usdt_api_enabled,
        "gold_api_enabled": s.gold_api_enabled,
        "gold_auto_update_assets": s.gold_auto_update_assets,
        "price_refresh_seconds": s.price_refresh_seconds,
        "wallex_markets_url": s.wallex_markets_url,
        "persiantoolbox_url": s.persiantoolbox_url,
        "goal_roi_pct": s.goal_roi_pct,
        "raw": d,
    }


def metrics_to_dict(m: DashboardMetrics) -> Dict[str, Any]:
    return {
        "total_value": m.total_value,
        "total_cost": m.total_cost,
        "total_pnl": m.total_pnl,
        "total_pnl_pct": m.total_pnl_pct,
        "open_count": m.open_count,
        "closed_count": m.closed_count,
        "realized_pnl": m.realized_pnl,
        "unrealized_pnl": m.unrealized_pnl,
        "today_pnl": m.today_pnl,
        "today_pnl_pct": m.today_pnl_pct,
        "annual_return_pct": m.annual_return_pct,
        "year_realized_pnl": m.year_realized_pnl,
    }
