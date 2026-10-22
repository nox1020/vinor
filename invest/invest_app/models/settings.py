"""Application settings model."""

from __future__ import annotations

from dataclasses import dataclass

from invest_app.config import (
    CALENDAR_JALALI,
    CURRENCY_TOMAN,
    DEFAULT_PERSIANTOOLBOX_URL,
    DEFAULT_SETTINGS,
    DEFAULT_WALLEX_MARKETS_URL,
    SETTING_CALENDAR,
    SETTING_CURRENCY,
    SETTING_FIRST_RUN,
    SETTING_GOAL_ROI_PCT,
    SETTING_GOLD_API,
    SETTING_GOLD_AUTO_UPDATE,
    SETTING_LIVE_PRICES,
    SETTING_NOTIFICATIONS,
    SETTING_NOTIFY_PRICE_MOVES,
    SETTING_NOTIFY_TRADES,
    SETTING_NOTIFY_WITHDRAWALS,
    SETTING_PERSIANTOOLBOX_URL,
    SETTING_PRICE_REFRESH_SEC,
    SETTING_THEME,
    SETTING_USDT_API,
    SETTING_WALLEX_URL,
    THEME_DARK,
)


def _as_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _as_optional_float(value: str | None) -> float | None:
    if value is None or not str(value).strip():
        return None
    try:
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


@dataclass
class AppSettings:
    """Runtime application preferences."""

    calendar: str = CALENDAR_JALALI
    currency: str = CURRENCY_TOMAN
    theme: str = THEME_DARK
    first_run_done: bool = False
    live_prices_enabled: bool = True
    usdt_api_enabled: bool = True
    gold_api_enabled: bool = True
    gold_auto_update_assets: bool = True
    price_refresh_seconds: int = 60
    wallex_markets_url: str = DEFAULT_WALLEX_MARKETS_URL
    persiantoolbox_url: str = DEFAULT_PERSIANTOOLBOX_URL
    goal_roi_pct: float | None = None
    notifications_enabled: bool = True
    notify_trades: bool = True
    notify_withdrawals: bool = True
    notify_price_moves: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> AppSettings:
        merged = {**DEFAULT_SETTINGS, **data}
        refresh = _as_int(merged.get(SETTING_PRICE_REFRESH_SEC), 60)
        refresh = max(5, min(refresh, 3600))
        return cls(
            calendar=merged.get(SETTING_CALENDAR, CALENDAR_JALALI),
            currency=merged.get(SETTING_CURRENCY, CURRENCY_TOMAN),
            theme=merged.get(SETTING_THEME, THEME_DARK),
            first_run_done=merged.get(SETTING_FIRST_RUN, "0") == "1",
            live_prices_enabled=_as_bool(merged.get(SETTING_LIVE_PRICES), True),
            usdt_api_enabled=_as_bool(merged.get(SETTING_USDT_API), True),
            gold_api_enabled=_as_bool(merged.get(SETTING_GOLD_API), True),
            gold_auto_update_assets=_as_bool(
                merged.get(SETTING_GOLD_AUTO_UPDATE), True
            ),
            price_refresh_seconds=refresh,
            wallex_markets_url=(
                merged.get(SETTING_WALLEX_URL, DEFAULT_WALLEX_MARKETS_URL).strip()
                or DEFAULT_WALLEX_MARKETS_URL
            ),
            persiantoolbox_url=(
                merged.get(SETTING_PERSIANTOOLBOX_URL, DEFAULT_PERSIANTOOLBOX_URL).strip()
                or DEFAULT_PERSIANTOOLBOX_URL
            ),
            goal_roi_pct=_as_optional_float(merged.get(SETTING_GOAL_ROI_PCT)),
            notifications_enabled=_as_bool(merged.get(SETTING_NOTIFICATIONS), True),
            notify_trades=_as_bool(merged.get(SETTING_NOTIFY_TRADES), True),
            notify_withdrawals=_as_bool(
                merged.get(SETTING_NOTIFY_WITHDRAWALS), True
            ),
            notify_price_moves=_as_bool(
                merged.get(SETTING_NOTIFY_PRICE_MOVES), True
            ),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            SETTING_CALENDAR: self.calendar,
            SETTING_CURRENCY: self.currency,
            SETTING_THEME: self.theme,
            SETTING_FIRST_RUN: "1" if self.first_run_done else "0",
            SETTING_LIVE_PRICES: "1" if self.live_prices_enabled else "0",
            SETTING_USDT_API: "1" if self.usdt_api_enabled else "0",
            SETTING_GOLD_API: "1" if self.gold_api_enabled else "0",
            SETTING_GOLD_AUTO_UPDATE: "1" if self.gold_auto_update_assets else "0",
            SETTING_PRICE_REFRESH_SEC: str(self.price_refresh_seconds),
            SETTING_WALLEX_URL: self.wallex_markets_url,
            SETTING_PERSIANTOOLBOX_URL: self.persiantoolbox_url,
            SETTING_GOAL_ROI_PCT: (
                "" if self.goal_roi_pct is None else str(self.goal_roi_pct)
            ),
            SETTING_NOTIFICATIONS: "1" if self.notifications_enabled else "0",
            SETTING_NOTIFY_TRADES: "1" if self.notify_trades else "0",
            SETTING_NOTIFY_WITHDRAWALS: "1" if self.notify_withdrawals else "0",
            SETTING_NOTIFY_PRICE_MOVES: "1" if self.notify_price_moves else "0",
        }
