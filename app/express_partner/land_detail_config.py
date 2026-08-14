# -*- coding: utf-8 -*-
"""پیکربندی JSON صفحه جزئیات فایل همکار — یک‌جا و امن برای parse در JS."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.utils.images import gallery_display_url, normalize_upload_url


def build_land_detail_config(
    land: Dict[str, Any],
    *,
    images: List[Any],
    has_video: bool,
    total_items: int,
    share_url: str,
    is_approved: bool,
    visit_date_min: str,
    visit_allowed_weekdays_js: Optional[List[int]] = None,
    visit_allowed_hours: Optional[List[int]] = None,
    flash_messages: List[Dict[str, str]],
    tx_status_url: str,
    csrf_token: str,
) -> Dict[str, Any]:
    code = str(land.get("code") or "file")
    desc = str(land.get("description") or land.get("desc") or "").strip()

    slides: List[Dict[str, str]] = []
    if has_video:
        slides.append({"type": "video", "src": normalize_upload_url(land.get("video"))})
    for img in images or []:
        if not img:
            continue
        slides.append(
            {
                "type": "image",
                "thumb": gallery_display_url(img),
                "full": normalize_upload_url(img),
            }
        )

    marketing_media: List[Dict[str, str]] = []
    if is_approved:
        if has_video:
            marketing_media.append(
                {
                    "type": "video",
                    "url": normalize_upload_url(land.get("video")),
                    "filename": f"{code}_video.mp4",
                }
            )
        for idx, img in enumerate(images or [], start=1):
            if not img:
                continue
            marketing_media.append(
                {
                    "type": "image",
                    "url": normalize_upload_url(img),
                    "filename": f"{code}_{idx}.jpg",
                }
            )

    return {
        "hasVideo": bool(has_video),
        "totalItems": int(total_items),
        "shareUrl": share_url or "",
        "code": code,
        "txMode": str(land.get("_tx_button_mode") or "visit"),
        "canRevisit": bool(land.get("_can_revisit")),
        "visitDateMin": visit_date_min or "",
        "visitAllowedWeekdays": list(visit_allowed_weekdays_js or []),
        "visitAllowedHours": list(visit_allowed_hours or []),
        "visitDate": str(land.get("_visit_date") or ""),
        "visitDateJalali": str(land.get("_visit_date_jalali") or ""),
        "txStatusUrl": tx_status_url or "",
        "csrfToken": csrf_token or "",
        "isApprovedPartner": bool(is_approved),
        "marketingTitle": str(land.get("title") or ""),
        "marketingDescription": desc,
        "marketingMedia": marketing_media,
        "flashMessages": flash_messages,
        "slides": slides,
    }
