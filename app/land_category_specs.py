"""مشخصات ملک بر اساس دسته‌بندی (زمین، باغ، ویلا، آپارتمان، تجاری)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# فیلدهای اختصاصی هر دسته — برای ذخیره/پاک‌سازی در فرم ادمین
KIND_FIELDS: Dict[str, List[str]] = {
    "land": [
        "frontage", "length", "street_width",
        "land_shape", "land_use",
        "has_fence", "has_corner", "has_well", "has_guardroom",
    ],
    "garden": [
        "frontage", "length", "street_width",
        "land_shape", "land_use", "irrigation", "tree_count",
        "has_fence", "has_corner", "has_well", "has_guardroom",
    ],
    "villa": [
        "villa_land_area", "villa_built_area", "villa_bedrooms", "villa_bathrooms",
        "villa_terrace", "villa_pool", "villa_direction",
        "year_built", "docs_status",
    ],
    "apartment": [
        "year_built", "floor", "floors", "rooms",
        "elevator", "parking", "warehouse", "docs_status",
    ],
    "commercial": [
        "front_width", "commercial_floor", "has_license", "commercial_type",
        "docs_status",
    ],
}

ALL_SPEC_FIELDS = sorted({f for fields in KIND_FIELDS.values() for f in fields})

CHECKBOX_FIELDS = frozenset({
    "has_fence", "has_corner", "has_well", "has_guardroom",
    "villa_terrace", "villa_pool", "elevator", "parking", "warehouse", "has_license",
})

YES_NO_SELECT_FIELDS = frozenset({
    "villa_terrace", "villa_pool", "elevator", "parking", "warehouse", "has_license",
})


def category_kind(category: Optional[str]) -> str:
    c = (category or "").strip()
    if c in ("زمین",):
        return "land"
    if c in ("باغ", "باغچه"):
        return "garden"
    if c in ("ویلا",):
        return "villa"
    if c in ("آپارتمان",):
        return "apartment"
    if c in ("تجاری",):
        return "commercial"
    return "other"


def _s(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


def land_expert_verified(land: dict) -> bool:
    """آگهی توسط کارشناسی تأیید شده (فیلد expert_verified در ثبت ادمین)."""
    if not isinstance(land, dict):
        return False
    return _truthy(land.get("expert_verified"))


def _truthy(val: Any) -> bool:
    if val in (True, 1, "1", "true", "True", "دارد", "yes", "بله"):
        return True
    if isinstance(val, str) and val.strip().lower() in ("1", "true", "دارد", "yes"):
        return True
    return False


def _yes_no_label(val: Any) -> str:
    if not _s(val):
        return ""
    return "دارد" if _truthy(val) else "ندارد"


def _area_val(land: dict, *keys: str) -> str:
    for k in keys:
        v = _s(land.get(k))
        if v:
            return v
    return ""


def land_area_m(land: dict) -> str:
    return _area_val(land, "villa_land_area", "land_area", "size")


def built_area_m(land: dict) -> str:
    return _area_val(land, "villa_built_area", "built_area")


def bedrooms(land: dict) -> str:
    return _area_val(land, "villa_bedrooms", "rooms")


def bathrooms(land: dict) -> str:
    return _area_val(land, "villa_bathrooms", "bathrooms", "wc")


def has_terrace(land: dict) -> bool:
    if _truthy(land.get("villa_terrace")) or _truthy(land.get("terrace")):
        return True
    feats = land.get("features") or []
    if isinstance(feats, list):
        text = ",".join(str(x) for x in feats)
        return "تراس" in text
    return False


def price_basis_area(land: dict) -> int:
    kind = category_kind(land.get("category"))
    if kind in ("villa", "apartment", "commercial"):
        b = built_area_m(land)
        if b:
            try:
                return int(float(str(b).replace(",", "")))
            except (ValueError, TypeError):
                pass
    a = land_area_m(land)
    if a:
        try:
            return int(float(str(a).replace(",", "")))
        except (ValueError, TypeError):
            pass
    try:
        return int(land.get("size") or 0)
    except (ValueError, TypeError):
        return 0


def _stat(label: str, icon: str, value: str, *, suffix: str = " م", unit_suffix: bool = True) -> Dict[str, Any]:
    display = value
    if value and unit_suffix and suffix and not str(value).endswith("متر"):
        display = f"{value}{suffix}"
    return {
        "label": label,
        "icon": icon,
        "value": value,
        "display": display or "—",
        "empty": not bool(value),
    }


def land_quick_stats(land: dict) -> List[Dict[str, Any]]:
    """آیکن‌های سریع جزئیات / کارت — فقط فیلدهای مرتبط با دسته."""
    kind = category_kind(land.get("category"))
    out: List[Dict[str, Any]] = []

    if kind == "land":
        la = land_area_m(land)
        out.append(_stat("متراژ زمین", "fa-vector-square", la))
        for label, icon, key in (
            ("عرض بر", "fa-arrows-left-right", "frontage"),
            ("عرض گذر", "fa-road", "street_width"),
            ("شکل زمین", "fa-shapes", "land_shape"),
        ):
            v = _s(land.get(key))
            if v:
                out.append(_stat(label, icon, v, suffix="", unit_suffix=False))
        return out[:4]

    if kind == "garden":
        la = land_area_m(land)
        if la:
            out.append(_stat("متراژ زمین", "fa-vector-square", la))
        tc = _s(land.get("tree_count"))
        if tc:
            out.append(_stat("تعداد درخت", "fa-tree", tc, suffix="", unit_suffix=False))
        irr = _s(land.get("irrigation"))
        if irr:
            out.append(_stat("آبیاری", "fa-droplet", irr, suffix="", unit_suffix=False))
        lu = _s(land.get("land_use"))
        if lu:
            out.append(_stat("کاربری", "fa-seedling", lu, suffix="", unit_suffix=False))
        return out[:4]

    if kind == "villa":
        out.append(_stat("متراژ بنا", "fa-building", built_area_m(land)))
        out.append(_stat("اتاق خواب", "fa-bed", bedrooms(land), suffix="", unit_suffix=False))
        out.append(_stat("سرویس", "fa-bath", bathrooms(land), suffix="", unit_suffix=False))
        out.append(_stat("تراس", "fa-tree", "دارد" if has_terrace(land) else "ندارد", suffix="", unit_suffix=False))
        return out

    if kind == "apartment":
        out.append(_stat("متراژ", "fa-vector-square", land_area_m(land) or _s(land.get("size"))))
        out.append(_stat("اتاق", "fa-bed", bedrooms(land), suffix="", unit_suffix=False))
        fl = _s(land.get("floor"))
        out.append(_stat("طبقه", "fa-layer-group", fl, suffix="", unit_suffix=False))
        yb = _s(land.get("year_built"))
        out.append(_stat("سال ساخت", "fa-calendar", yb, suffix="", unit_suffix=False))
        return out

    if kind == "commercial":
        la = land_area_m(land) or _s(land.get("size"))
        out.append(_stat("متراژ", "fa-vector-square", la))
        fw = _s(land.get("front_width"))
        out.append(_stat("ویترین/بر", "fa-store", fw, suffix=" م"))
        cf = _s(land.get("commercial_floor"))
        out.append(_stat("طبقه", "fa-layer-group", cf, suffix="", unit_suffix=False))
        ct = _s(land.get("commercial_type"))
        out.append(_stat("کاربری", "fa-briefcase", ct, suffix="", unit_suffix=False))
        return out

    # سایر / بدون دسته — فقط متراژ در صورت وجود
    la = land_area_m(land)
    if la:
        out.append(_stat("متراژ", "fa-vector-square", la))
    return out[:4]


def land_card_footer_stats(land: dict) -> List[Dict[str, str]]:
    """نوار پایین کارت پریمیوم — حداکثر ۳ ستون قبل از قیمت."""
    kind = category_kind(land.get("category"))
    rows: List[Dict[str, str]] = []

    if kind == "land":
        la = land_area_m(land)
        rows.append({"label": "متراژ زمین", "value": f"{la} متر" if la else "—"})
        ls = _s(land.get("land_shape"))
        if ls:
            rows.append({"label": "شکل زمین", "value": ls})
        lu = _s(land.get("land_use"))
        if lu:
            rows.append({"label": "کاربری", "value": lu})
        return rows[:3]

    if kind == "garden":
        la = land_area_m(land)
        rows.append({"label": "متراژ زمین", "value": f"{la} متر" if la else "—"})
        tc = _s(land.get("tree_count"))
        rows.append({"label": "تعداد درخت", "value": tc or "—"})
        irr = _s(land.get("irrigation"))
        if irr:
            rows.append({"label": "آبیاری", "value": irr})
        return rows[:3]

    if kind == "villa":
        la = land_area_m(land)
        rows.append({"label": "متراژ زمین", "value": f"{la} متر" if la else "—"})
        bm = built_area_m(land)
        rows.append({"label": "متراژ بنا", "value": f"{bm} متر" if bm else "—"})
        beds = bedrooms(land)
        rows.append({"label": "اتاق خواب", "value": beds or "—"})
        return rows[:3]

    if kind == "apartment":
        la = land_area_m(land) or _s(land.get("size"))
        rows.append({"label": "متراژ", "value": f"{la} متر" if la else "—"})
        rows.append({"label": "اتاق", "value": bedrooms(land) or "—"})
        fl = _s(land.get("floor"))
        rows.append({"label": "طبقه", "value": fl or "—"})
        return rows

    if kind == "commercial":
        la = land_area_m(land) or _s(land.get("size"))
        rows.append({"label": "متراژ", "value": f"{la} متر" if la else "—"})
        fw = _s(land.get("front_width"))
        rows.append({"label": "ویترین", "value": f"{fw} متر" if fw else "—"})
        ct = _s(land.get("commercial_type"))
        rows.append({"label": "کاربری", "value": ct or "—"})
        return rows

    la = land_area_m(land)
    if la:
        rows.append({"label": "متراژ", "value": f"{la} متر"})
    return rows[:3]


def _row(label: str, icon: str, value: str) -> Optional[Dict[str, str]]:
    v = _s(value)
    if not v:
        return None
    return {"label": label, "icon": icon, "value": v}


def _fmt_meter(val: Any) -> str:
    v = _s(val)
    return f"{v} متر" if v else "—"


def _row_always(
    label: str,
    icon: str,
    value: Any,
    *,
    meter: bool = False,
    yes_no: bool = False,
) -> Dict[str, str]:
    if yes_no:
        if not _s(value) and value not in (0, "0", False):
            display = "—"
        else:
            display = "دارد" if _truthy(value) else "ندارد"
    elif meter:
        display = _fmt_meter(value)
    else:
        v = _s(value)
        display = v if v else "—"
    return {"label": label, "icon": icon, "value": display}


def land_category_detail_rows(land: dict) -> List[Dict[str, str]]:
    """ردیف‌های مشخصات ملک برای جدول جزئیات (فیلدهای اصلی همیشه؛ بقیه اگر پر شده)."""
    kind = category_kind(land.get("category"))
    rows: List[Dict[str, str]] = []

    def add(r: Optional[Dict[str, str]]):
        if r:
            rows.append(r)

    if kind == "land":
        rows.append(_row_always("متراژ زمین", "fa-vector-square", land_area_m(land), meter=True))
        add(_row("عرض بر", "fa-arrows-left-right", land.get("frontage")))
        add(_row("طول", "fa-ruler", land.get("length")))
        add(_row("عرض گذر", "fa-road", land.get("street_width")))
        add(_row("شکل زمین", "fa-shapes", land.get("land_shape")))
        add(_row("کاربری", "fa-seedling", land.get("land_use")))
        for label, key in (
            ("دیوارکشی", "has_fence"),
            ("نبش", "has_corner"),
            ("چاه", "has_well"),
            ("سرایداری", "has_guardroom"),
        ):
            yn = _yes_no_label(land.get(key))
            if yn:
                add(_row(label, "fa-check", yn))
        return rows

    if kind == "garden":
        rows.append(_row_always("متراژ زمین", "fa-vector-square", land_area_m(land), meter=True))
        rows.append(_row_always("تعداد درخت", "fa-tree", land.get("tree_count")))
        add(_row("سیستم آبیاری", "fa-droplet", land.get("irrigation")))
        add(_row("شکل زمین", "fa-shapes", land.get("land_shape")))
        add(_row("کاربری", "fa-seedling", land.get("land_use")))
        add(_row("عرض بر", "fa-arrows-left-right", land.get("frontage")))
        return rows

    if kind == "villa":
        rows.append(_row_always("متراژ زمین", "fa-vector-square", land_area_m(land), meter=True))
        rows.append(_row_always("متراژ بنا", "fa-building", built_area_m(land), meter=True))
        rows.append(_row_always("اتاق خواب", "fa-bed", bedrooms(land)))
        rows.append(_row_always("سرویس", "fa-bath", bathrooms(land)))
        t_val = land.get("villa_terrace")
        rows.append(
            _row_always(
                "تراس",
                "fa-tree",
                t_val if _s(t_val) else has_terrace(land),
                yes_no=True,
            )
        )
        rows.append(_row_always("استخر", "fa-water", land.get("villa_pool"), yes_no=True))
        add(_row("جهت", "fa-compass", land.get("villa_direction") or land.get("direction")))
        rows.append(_row_always("سال ساخت", "fa-calendar", land.get("year_built")))
        return rows

    if kind == "apartment":
        rows.append(_row_always("متراژ", "fa-vector-square", land_area_m(land) or land.get("size"), meter=True))
        rows.append(_row_always("تعداد اتاق", "fa-bed", bedrooms(land)))
        rows.append(_row_always("طبقه", "fa-layer-group", land.get("floor")))
        rows.append(_row_always("سال ساخت", "fa-calendar", land.get("year_built")))
        for label, key, icon in (
            ("آسانسور", "elevator", "fa-elevator"),
            ("پارکینگ", "parking", "fa-car"),
            ("انباری", "warehouse", "fa-box"),
        ):
            rows.append(_row_always(label, icon, land.get(key), yes_no=True))
        return rows

    if kind == "commercial":
        rows.append(_row_always("متراژ", "fa-vector-square", land_area_m(land) or land.get("size"), meter=True))
        rows.append(_row_always("ویترین/بر", "fa-store", land.get("front_width"), meter=True))
        rows.append(_row_always("طبقه", "fa-layer-group", land.get("commercial_floor") or land.get("floor")))
        rows.append(_row_always("نوع کاربری", "fa-briefcase", land.get("commercial_type")))
        rows.append(_row_always("مجوز کسب", "fa-file-signature", land.get("has_license"), yes_no=True))
        return rows

    la = land_area_m(land) or _s(land.get("size"))
    if la:
        rows.append(_row_always("متراژ", "fa-vector-square", la, meter=True))
    return rows


def apply_category_specs_from_form(land: dict, form) -> None:
    """ذخیره فیلدهای اختصاصی دسته از فرم POST ادمین؛ حذف فیلدهای نامرتبط."""
    cat = _s(form.get("category")) or _s(land.get("category"))
    if cat:
        land["category"] = cat
    kind = category_kind(cat)

    allowed = set(KIND_FIELDS.get(kind, []))
    for field in ALL_SPEC_FIELDS:
        if field not in allowed:
            land.pop(field, None)
            continue
        if field in CHECKBOX_FIELDS:
            land[field] = "1" if form.get(field) else ""
            continue
        val = _s(form.get(field))
        if val:
            land[field] = val
        else:
            land.pop(field, None)

    # هم‌راستایی متراژ ویلا با فیلد size
    if kind == "villa":
        vla = _s(form.get("villa_land_area"))
        if vla:
            land["villa_land_area"] = vla
        size_raw = _s(form.get("size"))
        if size_raw and not land.get("villa_land_area"):
            land["villa_land_area"] = size_raw
