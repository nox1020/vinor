from __future__ import annotations

import re

from app.conversation.interfaces import (
    ROLE_GUEST,
    ROLE_PARTNER,
    ROLE_PREMIUM,
    ROLE_USER,
    IdentityInfo,
    IdentityResolver,
)


class RuleIdentityResolver(IdentityResolver):
    """Session/phone/audience only — no Prompt."""

    def resolve(self, *, user_key: str, audience: str, phone: str = "") -> IdentityInfo:
        uk = (user_key or "").strip()
        ph = (phone or "").strip()
        if not ph and uk and not uk.startswith("guest_"):
            ph = uk
        is_guest = (not ph) or uk.startswith("guest_")
        is_logged_in = not is_guest
        is_partner = False
        is_premium = False
        signals: dict = {"audience": audience or "", "user_key": uk}

        if is_logged_in and ph:
            try:
                from flask import session

                if session.get("VINOR_IS_EXPRESS_PARTNER"):
                    is_partner = True
                    signals["session_partner_flag"] = True
            except Exception:
                pass
            try:
                from app.ai.audience import is_express_partner_profile
                from app.express_partner.partner_roles import partner_is_special
                from app.utils.storage import load_express_partners

                partners = load_express_partners() or []
                digits = re.sub(r"\D+", "", ph)

                def _norm(p: str) -> str:
                    d = re.sub(r"\D+", "", str(p or ""))
                    return d[-11:] if len(d) >= 11 else d

                me = _norm(digits)
                prof = next(
                    (p for p in partners if _norm(str(p.get("phone") or "")) == me),
                    None,
                )
                if isinstance(prof, dict):
                    signals["profile_status"] = str(prof.get("status") or "")
                    if is_express_partner_profile(prof) or str(prof.get("status") or "") in (
                        "approved",
                        "true",
                        "1",
                    ):
                        is_partner = True
                    if partner_is_special(prof):
                        is_premium = True
                        is_partner = True
            except Exception:
                pass

        if (audience or "").lower() == "partner" and is_logged_in:
            # Partner chat surface — treat as partner track even if pending
            signals["partner_surface"] = True

        role = ROLE_GUEST
        if is_premium:
            role = ROLE_PREMIUM
        elif is_partner:
            role = ROLE_PARTNER
        elif is_logged_in:
            role = ROLE_USER

        return IdentityInfo(
            role=role,
            user_key=uk,
            phone=ph if not is_guest else "",
            is_logged_in=is_logged_in,
            is_partner=is_partner,
            is_premium=is_premium,
            signals=signals,
        )
