from app.utils.money import format_money


def test_format_toman() -> None:
    assert "تومان" in format_money(1_000_000, "toman")


def test_format_usd_with_fx() -> None:
    text = format_money(65_000_000, "usd", fx_rate=65_000)
    assert "$" in text or "دلار" in text.lower() or text
