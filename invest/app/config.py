"""Application paths, constants, and setting keys."""

from __future__ import annotations

from pathlib import Path

# Project root (parent of the `app` package)
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "invest.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "database" / "schema.sql"
STYLES_DIR = Path(__file__).resolve().parent / "ui" / "styles"
RESOURCES_DIR = Path(__file__).resolve().parent / "resources"

APP_NAME = "V+"

# Setting keys stored in the `settings` table
SETTING_CALENDAR = "calendar"
SETTING_CURRENCY = "currency"
SETTING_THEME = "theme"
SETTING_FIRST_RUN = "first_run_done"
SETTING_USDT_TMN_RATE = "usdt_tmn_rate"
SETTING_GOLD_TMN_PER_GRAM = "gold_tmn_per_gram"
SETTING_LIVE_PRICES = "live_prices_enabled"
SETTING_USDT_API = "usdt_api_enabled"
SETTING_GOLD_API = "gold_api_enabled"
SETTING_GOLD_AUTO_UPDATE = "gold_auto_update_assets"
SETTING_PRICE_REFRESH_SEC = "price_refresh_seconds"
SETTING_WALLEX_URL = "wallex_markets_url"
SETTING_PERSIANTOOLBOX_URL = "persiantoolbox_url"
SETTING_GOAL_ROI_PCT = "goal_roi_pct"

# Live price API defaults
DEFAULT_WALLEX_MARKETS_URL = "https://api.wallex.ir/v1/markets"
DEFAULT_PERSIANTOOLBOX_URL = "https://persiantoolbox.ir/api/market"
PRICE_REFRESH_OPTIONS = (30, 60, 120, 300)

CALENDAR_JALALI = "jalali"
CALENDAR_GREGORIAN = "gregorian"
CALENDARS = (CALENDAR_JALALI, CALENDAR_GREGORIAN)

CURRENCY_TOMAN = "toman"
CURRENCY_RIAL = "rial"
CURRENCY_USD = "usd"
CURRENCY_USDT = "usdt"
CURRENCIES = (CURRENCY_TOMAN, CURRENCY_RIAL, CURRENCY_USD, CURRENCY_USDT)

THEME_LIGHT = "light"
THEME_DARK = "dark"
THEMES = (THEME_DARK, THEME_LIGHT)

TRADE_STATUS_OPEN = "open"
TRADE_STATUS_CLOSED = "closed"

DEFAULT_SETTINGS: dict[str, str] = {
    SETTING_CALENDAR: CALENDAR_JALALI,
    SETTING_CURRENCY: CURRENCY_TOMAN,
    SETTING_THEME: THEME_DARK,
    SETTING_FIRST_RUN: "0",
    SETTING_LIVE_PRICES: "1",
    SETTING_USDT_API: "1",
    SETTING_GOLD_API: "1",
    SETTING_GOLD_AUTO_UPDATE: "1",
    SETTING_PRICE_REFRESH_SEC: "60",
    SETTING_WALLEX_URL: DEFAULT_WALLEX_MARKETS_URL,
    SETTING_PERSIANTOOLBOX_URL: DEFAULT_PERSIANTOOLBOX_URL,
    SETTING_GOAL_ROI_PCT: "",
}

CURRENCY_LABELS: dict[str, str] = {
    CURRENCY_TOMAN: "تومان",
    CURRENCY_RIAL: "ریال",
    CURRENCY_USD: "دلار",
    CURRENCY_USDT: "تتر (USDT)",
}

CALENDAR_LABELS: dict[str, str] = {
    CALENDAR_JALALI: "شمسی (جلالی)",
    CALENDAR_GREGORIAN: "میلادی",
}

THEME_LABELS: dict[str, str] = {
    THEME_LIGHT: "روشن",
    THEME_DARK: "تاریک",
}
