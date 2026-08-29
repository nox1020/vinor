"""Trade open/close and asset inventory updates."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.config import TRADE_STATUS_CLOSED, TRADE_STATUS_OPEN
from app.models.asset import Asset
from app.models.trade import Trade
from app.repositories.asset_repo import AssetRepository
from app.repositories.trade_repo import TradeRepository
from app.services.portfolio_service import PortfolioService
from app.utils import calc
from app.utils.dates import today_iso

_EPS = 1e-9


@dataclass(frozen=True)
class GoldFundMetrics:
    """Gold gram flows from buy/sell lots (صندوق طلا)."""

    gold_in_g: float
    """Total grams ever acquired (خرید / وارد)."""

    gold_out_g: float
    """Total grams sold / returned (فروش / خارج)."""

    gold_holding_g: float
    """Current inventory in grams (موجودی = لات‌های باز)."""

    @property
    def gold_debt_g(self) -> float:
        """Outstanding grams still held — بدهی به صندوق = موجودی."""
        return self.gold_holding_g


class TradeService:
    """Open/close trades and keep asset inventory in sync with open lots."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        portfolio: PortfolioService | None = None,
    ) -> None:
        self._conn = conn
        self.assets = AssetRepository(conn)
        self.trades = TradeRepository(conn)
        self.portfolio = portfolio or PortfolioService(conn)

    def register_buy(
        self,
        *,
        asset_id: int | None = None,
        name: str | None = None,
        symbol: str = "",
        quantity: float,
        buy_price: float,
        buy_fee: float = 0.0,
        buy_date: str | None = None,
        buy_note: str = "",
        current_price: float | None = None,
    ) -> Trade:
        if quantity <= 0:
            raise ValueError("مقدار باید بزرگ‌تر از صفر باشد.")
        if buy_price <= 0:
            raise ValueError("قیمت خرید باید بزرگ‌تر از صفر باشد.")
        if buy_fee < 0:
            raise ValueError("کارمزد نمی‌تواند منفی باشد.")

        asset = self._resolve_asset(
            asset_id=asset_id,
            name=name,
            symbol=symbol,
            buy_price=buy_price,
            current_price=current_price,
        )

        if current_price is not None and current_price > 0:
            asset.current_price = current_price
        elif asset.current_price <= 0:
            asset.current_price = buy_price

        trade = Trade(
            id=None,
            asset_id=asset.id,  # type: ignore[arg-type]
            status=TRADE_STATUS_OPEN,
            quantity=quantity,
            buy_price=buy_price,
            buy_fee=buy_fee,
            buy_date=buy_date or today_iso(),
            buy_note=buy_note,
        )
        try:
            self.assets.update(asset, commit=False)
            trade = self.trades.create(trade, commit=False)
            self._sync_asset_inventory(asset.id, commit=False)  # type: ignore[arg-type]
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        self.portfolio.record_snapshot()
        return trade

    def close_trade(
        self,
        trade_id: int,
        *,
        sell_price: float,
        sell_fee: float = 0.0,
        sell_date: str | None = None,
        sell_note: str = "",
        quantity: float | None = None,
    ) -> Trade:
        trade = self.trades.get(trade_id)
        if not trade:
            raise ValueError("معامله یافت نشد.")
        if not trade.is_open:
            raise ValueError("این معامله قبلاً بسته شده است.")
        if sell_price <= 0:
            raise ValueError("قیمت فروش باید بزرگ‌تر از صفر باشد.")
        if sell_fee < 0:
            raise ValueError("کارمزد نمی‌تواند منفی باشد.")

        close_qty = float(trade.quantity if quantity is None else quantity)
        if close_qty <= 0:
            raise ValueError("مقدار فروش باید بزرگ‌تر از صفر باشد.")
        if close_qty > trade.quantity + _EPS:
            raise ValueError("مقدار فروش از مقدار معامله باز بیشتر است.")

        asset = self.assets.get(trade.asset_id)
        if not asset:
            raise ValueError("دارایی مرتبط یافت نشد.")

        sell_d = sell_date or today_iso()
        if sell_d[:10] < trade.buy_date[:10]:
            raise ValueError("تاریخ فروش نمی‌تواند قبل از تاریخ خرید باشد.")

        # Full close
        if close_qty >= trade.quantity - _EPS:
            return self._close_full(
                trade,
                asset=asset,
                sell_price=sell_price,
                sell_fee=sell_fee,
                sell_date=sell_d,
                sell_note=sell_note,
            )

        # Partial close: shrink open lot + create a closed lot
        return self._close_partial(
            trade,
            asset=asset,
            close_qty=close_qty,
            sell_price=sell_price,
            sell_fee=sell_fee,
            sell_date=sell_d,
            sell_note=sell_note,
        )

    def _close_full(
        self,
        trade: Trade,
        *,
        asset: Asset,
        sell_price: float,
        sell_fee: float,
        sell_date: str,
        sell_note: str,
    ) -> Trade:
        pnl = calc.realized_pnl(
            trade.quantity, trade.buy_price, sell_price, trade.buy_fee, sell_fee
        )
        pct = calc.return_pct(
            trade.quantity, trade.buy_price, sell_price, trade.buy_fee, sell_fee
        )
        days = calc.holding_days(trade.buy_date, sell_date)

        trade.status = TRADE_STATUS_CLOSED
        trade.sell_price = sell_price
        trade.sell_fee = sell_fee
        trade.sell_date = sell_date
        trade.sell_note = sell_note
        trade.realized_pnl = pnl
        trade.return_pct = pct
        trade.holding_days = days

        try:
            self.trades.update(trade, commit=False)
            self._sync_asset_inventory(asset.id, commit=False)  # type: ignore[arg-type]
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        self.portfolio.record_snapshot()
        return trade

    def _close_partial(
        self,
        trade: Trade,
        *,
        asset: Asset,
        close_qty: float,
        sell_price: float,
        sell_fee: float,
        sell_date: str,
        sell_note: str,
    ) -> Trade:
        ratio = close_qty / trade.quantity
        buy_fee_closed = trade.buy_fee * ratio
        buy_fee_remain = trade.buy_fee - buy_fee_closed

        pnl = calc.realized_pnl(
            close_qty, trade.buy_price, sell_price, buy_fee_closed, sell_fee
        )
        pct = calc.return_pct(
            close_qty, trade.buy_price, sell_price, buy_fee_closed, sell_fee
        )
        days = calc.holding_days(trade.buy_date, sell_date)

        closed = Trade(
            id=None,
            asset_id=trade.asset_id,
            status=TRADE_STATUS_CLOSED,
            quantity=close_qty,
            buy_price=trade.buy_price,
            buy_fee=buy_fee_closed,
            buy_date=trade.buy_date,
            buy_note=trade.buy_note,
            sell_price=sell_price,
            sell_fee=sell_fee,
            sell_date=sell_date,
            sell_note=sell_note,
            realized_pnl=pnl,
            return_pct=pct,
            holding_days=days,
        )

        try:
            closed = self.trades.create(closed, commit=False)
            trade.quantity = trade.quantity - close_qty
            trade.buy_fee = buy_fee_remain
            self.trades.update(trade, commit=False)
            self._sync_asset_inventory(asset.id, commit=False)  # type: ignore[arg-type]
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        self.portfolio.record_snapshot()
        return closed

    def _sync_asset_inventory(self, asset_id: int, *, commit: bool = True) -> Asset:
        """Recompute quantity and average buy price from remaining open lots."""
        asset = self.assets.get(asset_id)
        if not asset:
            raise ValueError("دارایی یافت نشد.")
        open_lots = self.trades.list_by_asset(asset_id, TRADE_STATUS_OPEN)
        total_qty = sum(float(t.quantity) for t in open_lots)
        if total_qty <= _EPS:
            asset.quantity = 0.0
            asset.avg_buy_price = 0.0
        else:
            cost = sum(
                float(t.quantity) * float(t.buy_price) + float(t.buy_fee or 0)
                for t in open_lots
            )
            asset.quantity = total_qty
            asset.avg_buy_price = cost / total_qty
        self.assets.update(asset, commit=commit)
        return asset

    def update_asset_price(self, asset_id: int, current_price: float) -> Asset:
        asset = self.assets.get(asset_id)
        if not asset:
            raise ValueError("دارایی یافت نشد.")
        if current_price < 0:
            raise ValueError("قیمت فعلی نامعتبر است.")
        asset.current_price = current_price
        self.assets.update(asset)
        self.portfolio.record_snapshot()
        return asset

    @staticmethod
    def is_gold_asset(name: str, symbol: str = "") -> bool:
        """True for per-gram bullion assets (not coins / ayar pieces)."""
        sym = (symbol or "").strip().upper()
        nm = (name or "").strip()
        if sym in {"GOLD", "XAU", "GERAM", "GRAM"}:
            return True
        if sym.startswith("AYAR"):
            return False
        if "سکه" in nm or "عیار" in nm:
            return False
        return "طلا" in nm

    def gold_fund_metrics(self) -> GoldFundMetrics:
        """
        Aggregate gold grams from buy/sell lots.

        وارد  = مجموع گرم خریداری‌شده در تاریخچهٔ فعلی (لات باز + بسته)
        خارج  = مجموع گرم فروخته‌شده (لات‌های بسته‌شدهٔ باقی‌مانده)
        موجودی = مجموع لات‌های باز (= وارد − خارج)

        حذف معاملهٔ بسته از تاریخچه، وارد/خارج را هم کم می‌کند.
        """
        open_g = 0.0
        closed_g = 0.0
        for trade in self.trades.list_open() + self.trades.list_closed():
            if not self.is_gold_asset(trade.asset_name, trade.asset_symbol):
                continue
            qty = float(trade.quantity or 0.0)
            if qty <= _EPS:
                continue
            if trade.is_closed:
                closed_g += qty
            else:
                open_g += qty

        # موجودی از دارایی‌ها (باید با لات‌های باز یکی باشد)
        holding_assets = 0.0
        for asset in self.assets.list_all():
            if not self.is_gold_asset(asset.name, asset.symbol):
                continue
            holding_assets += float(asset.quantity or 0.0)

        # لات‌های باز منبع حقیقت جریان‌اند؛ اگر دارایی کمی اختلاف float داشت،
        # موجودی را از لات‌ها می‌گیریم تا وارد − خارج = موجودی دقیق بماند.
        holding = open_g
        if abs(holding_assets - open_g) > 1e-4:
            # اگر sync از دست رفته، موجودی نمایشی همان لات باز است
            holding = open_g

        gold_in = open_g + closed_g
        gold_out = closed_g

        def _clean(v: float) -> float:
            if abs(v) < _EPS:
                return 0.0
            return round(v, 8)

        return GoldFundMetrics(
            gold_in_g=_clean(gold_in),
            gold_out_g=_clean(gold_out),
            gold_holding_g=_clean(holding),
        )

    @staticmethod
    def is_usdt_asset(name: str, symbol: str = "") -> bool:
        """True for Tether / dollar cash holdings priced in toman per 1 USD."""
        sym = (symbol or "").strip().upper()
        nm = (name or "").strip().lower()
        if sym in {"USDT", "USD", "DOLLAR", "USDT.TMN", "USDTTMN"}:
            return True
        if "تتر" in (name or ""):
            return True
        if nm in {"دلار", "dollar", "usd", "usdt"}:
            return True
        return "دلار" in (name or "") and "سکه" not in (name or "")

    @staticmethod
    def live_unit_price(
        name: str,
        symbol: str = "",
        *,
        usdt_tmn: float | None = None,
        gold_tmn: float | None = None,
    ) -> float | None:
        """Return live toman price per unit for gold/USDT assets when available."""
        if TradeService.is_gold_asset(name, symbol) and gold_tmn and gold_tmn > 0:
            return float(gold_tmn)
        if TradeService.is_usdt_asset(name, symbol) and usdt_tmn and usdt_tmn > 0:
            return float(usdt_tmn)
        return None

    def apply_live_market_prices(
        self,
        *,
        usdt_tmn: float | None = None,
        gold_tmn: float | None = None,
        update_usdt: bool = True,
        update_gold: bool = True,
    ) -> dict[str, int]:
        """
        Push live dollar/gold rates into matching assets' current_price.

        Portfolio value, unrealized PnL, and charts then use these rates.
        """
        updated_usdt = 0
        updated_gold = 0
        try:
            for asset in self.assets.list_all():
                new_price: float | None = None
                kind: str | None = None
                if update_gold and self.is_gold_asset(asset.name, asset.symbol):
                    if gold_tmn and gold_tmn > 0:
                        new_price = float(gold_tmn)
                        kind = "gold"
                    else:
                        continue
                elif update_usdt and self.is_usdt_asset(asset.name, asset.symbol):
                    if usdt_tmn and usdt_tmn > 0:
                        new_price = float(usdt_tmn)
                        kind = "usdt"
                    else:
                        continue
                else:
                    continue
                if abs(asset.current_price - new_price) < 0.5:
                    continue
                asset.current_price = new_price
                self.assets.update(asset, commit=False)
                if kind == "gold":
                    updated_gold += 1
                else:
                    updated_usdt += 1
            if updated_usdt or updated_gold:
                self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        total = updated_usdt + updated_gold
        if total:
            self.portfolio.record_snapshot()
        return {"usdt": updated_usdt, "gold": updated_gold, "total": total}

    def apply_live_gold_price(self, price_toman: float) -> int:
        """Backward-compatible wrapper."""
        return self.apply_live_market_prices(
            gold_tmn=price_toman, update_usdt=False, update_gold=True
        )["gold"]

    def create_asset(
        self,
        *,
        name: str,
        symbol: str = "",
        quantity: float = 0.0,
        avg_buy_price: float = 0.0,
        current_price: float = 0.0,
        notes: str = "",
        _skip_snapshot: bool = False,
    ) -> Asset:
        if not name.strip():
            raise ValueError("نام دارایی الزامی است.")
        if quantity < 0:
            raise ValueError("مقدار نمی‌تواند منفی باشد.")
        if quantity > _EPS and avg_buy_price <= 0:
            raise ValueError("برای موجودی اولیه، قیمت خرید الزامی است.")
        existing = self.assets.find_by_name_symbol(name.strip(), symbol.strip())
        if existing:
            raise ValueError("دارایی با این نام و نماد از قبل وجود دارد.")
        price = current_price or avg_buy_price
        asset = Asset(
            id=None,
            name=name.strip(),
            symbol=symbol.strip(),
            quantity=0.0,
            avg_buy_price=0.0,
            current_price=price,
            notes=notes,
        )
        try:
            asset = self.assets.create(asset, commit=False)
            # Inventory is owned by open lots — seed an opening trade when qty given.
            if quantity > _EPS:
                trade = Trade(
                    id=None,
                    asset_id=asset.id,  # type: ignore[arg-type]
                    status=TRADE_STATUS_OPEN,
                    quantity=quantity,
                    buy_price=avg_buy_price,
                    buy_fee=0.0,
                    buy_date=today_iso(),
                    buy_note="موجودی اولیه",
                )
                self.trades.create(trade, commit=False)
                asset = self._sync_asset_inventory(asset.id, commit=False)  # type: ignore[arg-type]
                asset.current_price = price
                self.assets.update(asset, commit=False)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        if not _skip_snapshot:
            self.portfolio.record_snapshot()
        return asset

    def update_asset(self, asset: Asset) -> Asset:
        if not asset.name.strip():
            raise ValueError("نام دارایی الزامی است.")
        # Keep inventory fields driven by open trades when lots exist
        open_lots = self.trades.list_by_asset(asset.id, TRADE_STATUS_OPEN) if asset.id else []
        if open_lots:
            saved_price = asset.current_price
            saved_meta = (asset.name, asset.symbol, asset.notes)
            self.assets.update(asset)
            synced = self._sync_asset_inventory(asset.id)  # type: ignore[arg-type]
            synced.current_price = saved_price
            synced.name, synced.symbol, synced.notes = saved_meta
            self.assets.update(synced)
            asset = synced
        else:
            self.assets.update(asset)
        self.portfolio.record_snapshot()
        return asset

    def delete_asset(self, asset_id: int) -> None:
        self.assets.delete(asset_id)
        self.portfolio.record_snapshot()

    def delete_closed_trade(self, trade_id: int) -> None:
        """Remove one closed trade from history (does not change open inventory)."""
        trade = self.trades.get(trade_id)
        if not trade:
            raise ValueError("معامله یافت نشد.")
        if not trade.is_closed:
            raise ValueError("فقط معاملات بسته‌شده را می‌توان از تاریخچه حذف کرد.")
        self.trades.delete(trade_id)
        self.portfolio.record_snapshot()

    def _resolve_asset(
        self,
        *,
        asset_id: int | None,
        name: str | None,
        symbol: str,
        buy_price: float,
        current_price: float | None,
    ) -> Asset:
        if asset_id is not None:
            asset = self.assets.get(asset_id)
            if not asset:
                raise ValueError("دارایی یافت نشد.")
            return asset
        if not name or not name.strip():
            raise ValueError("دارایی یا نام دارایی الزامی است.")
        asset = self.assets.find_by_name_symbol(name.strip(), symbol.strip())
        if asset:
            return asset
        return self.create_asset(
            name=name.strip(),
            symbol=symbol.strip(),
            quantity=0.0,
            avg_buy_price=0.0,
            current_price=current_price if current_price is not None else buy_price,
            _skip_snapshot=True,
        )
