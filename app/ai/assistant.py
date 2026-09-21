"""دستیار وینور — یک هماهنگ‌کنندهٔ نازک برای یک نوبت چت.

هدف محصول قفل: `app/ai/goal.py` · `roadmap/AGENT_GOAL.md`
یک ایجنت = یک بازاریاب؛ فروش فایل سیستم از چت.

مسیر یک پیام:
  ۱) هویت/مخاطب/لحن            → audience.py
  ۲) گیت اعتبار و فیوز مصرف     → credits.py
  ۳) میان‌بر فرم بازدید/مشتری   → agent_tools.try_continue_*
  ۴) ساخت prompt + حافظه       → prompts.py
  ۵) seed برنامه‌ریز (یک بار)   → app.planning.service
  ۶) حلقهٔ مدل و ابزار          → runner.py
  ۷) پس‌پردازش و کارت‌ها        → postprocess.py
  ۸) پاسخ ساخت‌یافته + تحلیل    → request_analytics.py

لایه‌های supervisor/agents/executive/goals/decision/parallel/evaluation در مسیر
هر پیام اجرا نمی‌شوند؛ ماژول‌هایشان سر جای خود مانده و مستقل قابل اجرا هستند.
"""
from __future__ import annotations

import time
from typing import Any

from flask import current_app

from .audience import resolve_ai_voice
from .context import AssistantContext, build_assistant_context
from .credits import (
    SPEND_FUSE_ERROR,
    apply_credit_guard,
    budget_config,
    is_api_balance_depleted,
    recheck_api_balance_if_depleted,
    record_api_call,
    store_cached_reply,
)
from .escalations import create_escalation
from .intents import ChatIntent, detect_intent
from .land_cards import collect_land_codes, land_cards_payload
from .postprocess import (
    build_cards_html,
    enforce_response_style,
    sanitize_unconfirmed_action_claims,
    strip_escalate_marker,
    strip_listing_dump_when_copy_cards,
)
from .prompts import build_messages, normalize_chat_audience, prompt_token_parts
from .request_analytics import record_request_analytics
from .runner import run_agent_loop

_MAX_LAND_CARDS = 5


class VinorAssistant:
    """یک نوبت گفتگو را از پیام کاربر تا پاسخ ساخت‌یافته می‌برد."""

    def handle(
        self,
        message: str,
        *,
        user_key: str | None = None,
        audience: str | None = None,
        thread_id: str | None = None,
        chip_intent: str | None = None,
        voice: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        text = (message or "").strip()
        if not text:
            return {"ok": False, "error": "پیام خالی است."}

        key = (user_key or "").strip()
        aud = normalize_chat_audience(audience)
        resolved_voice = (voice or "").strip().lower() or resolve_ai_voice(
            phone=key, audience=aud
        )
        ctx = build_assistant_context(
            user_key=key,
            audience=aud,
            voice=resolved_voice,
            thread_id=thread_id,
        )

        gate = self._gates(ctx, text)
        if gate is not None:
            return gate

        self._begin_request(ctx, text)

        guard = self._credit_gate(ctx, text)
        if guard is not None:
            return guard

        intent = detect_intent(text, chip_intent)

        short = self._form_shortcut(ctx, text, intent)
        if short is not None:
            return short

        return self._llm_turn(ctx, text, intent, history, started)

    # --- گیت‌ها ------------------------------------------------------------

    def _gates(self, ctx: AssistantContext, text: str) -> dict[str, Any] | None:
        from .services import ai_config

        cfg = ai_config()
        if not cfg["enabled"]:
            return {
                "ok": False,
                "error": (
                    "سرویس هوش مصنوعی موقتاً متوقف شده است. "
                    "لطفاً کمی بعد دوباره پیام بدهید."
                ),
                "error_code": "ai_paused",
            }

        balance_out = self._recheck_balance(ctx, text)
        if balance_out is not None:
            return balance_out

        if ctx.is_lawyer:
            try:
                from app.lawyer.config import lawyer_enabled

                if not lawyer_enabled():
                    return {
                        "ok": False,
                        "error": "وکیل ملکی فعلاً غیرفعال است.",
                        "error_code": "lawyer_disabled",
                    }
            except Exception:
                pass

        fuse = cfg.get("spend_fuse") or {}
        if fuse.get("tripped"):
            return {
                "ok": False,
                "error": SPEND_FUSE_ERROR,
                "error_code": "spend_fuse",
                "spend_fuse": True,
            }
        return None

    def _recheck_balance(
        self, ctx: AssistantContext, text: str
    ) -> dict[str, Any] | None:
        """اگر قبلاً اتمام موجودی ثبت شده، با هر پیام استعلام مجدد بزن."""
        try:
            from flask import g

            if bool(getattr(g, "ai_balance_resume", False)):
                return None
        except Exception:
            pass
        if not is_api_balance_depleted():
            return None
        try:
            check = recheck_api_balance_if_depleted()
        except Exception:
            self._log_exception("AI balance recheck failed")
            return None
        if check.get("restored"):
            self._log_info(
                "AI balance restored on message | user=%s | audience=%s",
                ctx.user_key,
                ctx.audience,
            )
            return None
        if check.get("depleted"):
            # هنوز موجودی نیست — سوال را صف کن و زود برگرد (بدون ساخت prompt)
            return self._escalation_fallback(ctx, text, reason="balance")
        return None

    def _credit_gate(self, ctx: AssistantContext, text: str) -> dict[str, Any] | None:
        from .agent_tools import append_support_call_if_needed

        if ctx.is_admin:
            try:
                from .credits import validate_message_length

                err = validate_message_length(text)
            except Exception:
                err = None
            return {"ok": False, "error": err} if err else None

        guard = apply_credit_guard(ctx.user_key, ctx.audience, text)
        if guard is None:
            return None
        codes = [str(c).strip() for c in (guard.get("land_codes") or []) if str(c).strip()]
        if guard.get("ok") and codes:
            guard["land_cards"] = land_cards_payload(
                ctx.user_key, codes, audience=ctx.audience
            )
            try:
                from .land_cards import render_land_cards_html

                land_html = (
                    render_land_cards_html(ctx.user_key, codes, audience=ctx.audience)
                    or ""
                )
                if land_html:
                    guard["cards_html"] = land_html + str(guard.get("cards_html") or "")
            except Exception:
                pass
        try:
            guard["cards_html"] = append_support_call_if_needed(
                str(guard.get("cards_html") or ""),
                str(guard.get("reply") or guard.get("error") or ""),
                land_codes=codes,
                audience=ctx.audience,
            )
        except Exception:
            pass
        return guard

    # --- زمینهٔ درخواست ----------------------------------------------------

    def _begin_request(self, ctx: AssistantContext, text: str) -> None:
        """وضعیت درخواست را برای ابزارها آماده کن و قیف را بی‌صدا رصد کن."""
        try:
            from flask import g

            g.ai_user_key = ctx.user_key
            g.ai_tool_thread_id = ctx.thread_id
            g.ai_tool_audience = ctx.audience
            g.ai_last_user_message = text
            if ctx.focus_land_code:
                g.ai_focus_land_code = ctx.focus_land_code
        except Exception:
            pass
        # فلگ‌های لایهٔ قدیمی نباید از درخواست قبلی بمانند — پیش‌فرض همه روشن.
        try:
            from app.supervisor.service import set_supervisor_context

            set_supervisor_context(None)
        except Exception:
            pass
        if ctx.is_admin or ctx.is_lawyer:
            return
        try:
            from app.supervisor.funnel_service import watch_user

            watch_user(ctx.user_key, audience=ctx.audience, voice=ctx.voice)
        except Exception:
            pass

    # --- میان‌بر فرم بازدید / مشتری ---------------------------------------

    def _form_shortcut(
        self, ctx: AssistantContext, text: str, intent: ChatIntent
    ) -> dict[str, Any] | None:
        """
        این تنها «حالت گفتگو»ی نگه‌داشته‌شده است: پیش‌نویس بازدید و مشتری و
        نتیجهٔ بازدید در Backend ذخیره می‌شوند، پس ادامهٔ مرحله‌ای باید بدون مدل جلو برود.
        """
        if ctx.is_lawyer or ctx.is_admin or not ctx.user_key:
            return None

        if intent.chip == "visit":
            self._reset_visit_draft(ctx)
            return None

        from .agent_tools import (
            try_continue_lead_from_user_message,
            try_continue_visit_from_user_message,
            try_continue_visit_result_from_user_message,
        )

        out = try_continue_visit_from_user_message(
            ctx.user_key,
            text,
            audience=ctx.audience,
            voice=ctx.voice,
            thread_id=ctx.thread_id,
        )
        if out and out.get("ok"):
            return self._shortcut_response(ctx, out, provider="visit_step")

        out = try_continue_lead_from_user_message(
            ctx.user_key,
            text,
            audience=ctx.audience,
            voice=ctx.voice,
            thread_id=ctx.thread_id,
            chip_intent=intent.chip,
        )
        if out and out.get("ok"):
            return self._shortcut_response(ctx, out, provider="lead_step")

        out = try_continue_visit_result_from_user_message(
            ctx.user_key,
            text,
            audience=ctx.audience,
            voice=ctx.voice,
            thread_id=ctx.thread_id,
            chip_intent=intent.chip,
        )
        if out and out.get("ok"):
            return self._shortcut_response(ctx, out, provider="visit_result_step")
        return None

    def _reset_visit_draft(self, ctx: AssistantContext) -> None:
        """شروع تازهٔ ثبت بازدید — نام/شماره قبلی پاک، کد فایل موضوع حفظ."""
        try:
            from flask import g

            from .agent_tools import reset_visit_draft_keep_land

            focus_land = reset_visit_draft_keep_land(
                ctx.user_key, thread_id=ctx.thread_id
            )
            if focus_land:
                g.ai_focus_land_code = focus_land
            g.ai_tool_thread_id = ctx.thread_id
            g.ai_tool_audience = ctx.audience
        except Exception:
            pass

    def _shortcut_response(
        self,
        ctx: AssistantContext,
        out: dict[str, Any],
        *,
        provider: str,
    ) -> dict[str, Any]:
        from .agent_tools import render_agent_actions_html

        reply = str(out.get("reply") or "").strip()
        agent_actions = [a for a in (out.get("agent_actions") or []) if isinstance(a, dict)]
        actions_html = ""
        if agent_actions:
            try:
                actions_html = render_agent_actions_html(
                    agent_actions, phone=ctx.user_key, audience=ctx.audience
                )
            except Exception:
                actions_html = ""
        cards_html = build_cards_html(
            user_key=ctx.user_key,
            audience=ctx.audience,
            reply=reply,
            agent_actions=agent_actions,
        )
        result: dict[str, Any] = {
            "ok": True,
            "reply": reply,
            "land_codes": [],
            "land_cards": [],
            "agent_actions": agent_actions,
            "agent_actions_html": actions_html,
            "meta": out.get("meta") or {"provider": provider},
        }
        if cards_html:
            result["cards_html"] = cards_html
        return result

    # --- نوبت مدل ----------------------------------------------------------

    def _llm_turn(
        self,
        ctx: AssistantContext,
        text: str,
        intent: ChatIntent,
        history: list[dict[str, str]] | None,
        started: float,
    ) -> dict[str, Any]:
        from .agent_budget import agent_budget
        from .agent_tools import tools_schema_for_voice
        from .token_diag import apply_threshold_fixes

        tools = tools_schema_for_voice(ctx.voice) if ctx.user_key else []
        messages = build_messages(
            text,
            history,
            user_key=ctx.user_key,
            audience=ctx.audience,
            voice=ctx.voice,
            with_tools=bool(tools),
            chip_intent=intent.chip or None,
            thread_id=ctx.thread_id,
        )

        plan_out = self._planning_seed(ctx, text, intent, messages)
        loop_tools: list[dict[str, Any]] | None = tools or None
        # اگر برنامه‌ریز ابزار را seed کرده، دوباره schema نفرست (۱ درخواست کمتر).
        if plan_out is not None and plan_out.seed_messages:
            loop_tools = None

        messages, loop_tools, token_fixes = apply_threshold_fixes(
            messages,
            loop_tools,
            voice=ctx.voice,
            user_message=text,
            chip_intent=intent.chip,
        )
        try:
            from .tools.selection import per_round_tool_selection_enabled

            if per_round_tool_selection_enabled() and tools:
                loop_tools = list(tools)
        except Exception:
            pass

        prompt_parts = prompt_token_parts(messages)
        try:
            from flask import g

            g.ai_last_user_message = text
            g.ai_tools_schema = loop_tools
            g.ai_token_fixes_applied = token_fixes
        except Exception:
            pass

        completion_cap = int(
            agent_budget(ctx.voice).get("max_tokens") or budget_config()["max_tokens"]
        )
        result = run_agent_loop(
            messages,
            tools=loop_tools,
            phone=ctx.user_key,
            audience=ctx.audience,
            voice=ctx.voice,
            thread_id=ctx.thread_id,
            max_tokens=completion_cap,
            user_message=text,
            chip_intent=intent.chip,
        )
        try:
            from flask import g

            g.ai_tool_selection = (
                result.get("tool_selection") if isinstance(result, dict) else None
            )
        except Exception:
            pass

        if not result.get("ok"):
            return self._handle_failure(
                ctx, text, result, messages, prompt_parts, started
            )
        return self._finalize(
            ctx, text, result, plan_out, messages, prompt_parts, started
        )

    def _planning_seed(
        self,
        ctx: AssistantContext,
        text: str,
        intent: ChatIntent,
        messages: list[dict[str, Any]],
    ) -> Any:
        """یک فراخوان برنامه‌ریز برای seed جستجو — کمک واقعی به «زمین گرمابسرد»."""
        if ctx.is_lawyer or not ctx.user_key or intent.skip_planning:
            return None
        try:
            from app.planning.service import run_planning_once

            plan_out = run_planning_once(
                goal=text,
                user_key=ctx.user_key,
                audience=ctx.audience,
                voice=ctx.voice,
                thread_id=ctx.thread_id,
                chip_intent=intent.chip,
            )
        except Exception:
            return None
        if plan_out is None:
            return None
        from .prompts import append_internal_hint, set_planning_obs

        set_planning_obs(plan_out)
        if plan_out.compact_hint:
            append_internal_hint(messages, plan_out.compact_hint)
        if plan_out.seed_messages:
            messages.extend(plan_out.seed_messages)
        return plan_out

    def _handle_failure(
        self,
        ctx: AssistantContext,
        text: str,
        result: dict[str, Any],
        messages: list[dict[str, Any]],
        prompt_parts: dict[str, int],
        started: float,
    ) -> dict[str, Any]:
        from .services import ai_config

        reason = None
        if result.get("balance_depleted") or is_api_balance_depleted():
            reason = "balance"
        elif not ai_config()["api_key_set"] or result.get("error_code") == "no_api_key":
            reason = "no_key"
        if reason:
            fallback = self._escalation_fallback(ctx, text, reason=reason)
            if fallback.get("ok"):
                return fallback
        record_request_analytics(
            user_key=ctx.user_key,
            audience=ctx.audience,
            voice=ctx.voice,
            messages=messages,
            prompt_parts=prompt_parts,
            result=result,
            started=started,
        )
        return result

    def _finalize(
        self,
        ctx: AssistantContext,
        text: str,
        result: dict[str, Any],
        plan_out: Any,
        messages: list[dict[str, Any]],
        prompt_parts: dict[str, int],
        started: float,
    ) -> dict[str, Any]:
        from .card_registry import normalize_card

        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        if meta.get("provider") == "deepseek":
            record_api_call(ctx.user_key, ctx.audience)

        reply, escalate_q = strip_escalate_marker(result.get("reply") or "")
        reply, land_codes = collect_land_codes(
            reply, user_text=text, phone=ctx.user_key, audience=ctx.audience
        )
        tool_codes = [
            str(c).strip() for c in (result.get("tool_land_codes") or []) if str(c).strip()
        ]
        for code in tool_codes:
            if code not in land_codes:
                land_codes.append(code)
        if plan_out is not None:
            for code in plan_out.land_codes or []:
                c = str(code).strip()
                if c and c not in land_codes:
                    land_codes.append(c)
        land_codes = land_codes[:_MAX_LAND_CARDS]
        # ادمین: کارت فایل فقط وقتی ابزار صریحاً land_codes برگرداند (show_cards)
        if ctx.is_admin:
            land_codes = [c for c in land_codes if c in tool_codes][:_MAX_LAND_CARDS]

        agent_actions = [
            normalize_card(a)
            for a in (result.get("agent_actions") or [])
            if isinstance(a, dict)
        ]
        if plan_out is not None:
            for a in plan_out.agent_actions or []:
                if isinstance(a, dict):
                    agent_actions.append(normalize_card(a))
        if any(str(a.get("type") or "") == "copy_blocks" for a in agent_actions):
            reply = strip_listing_dump_when_copy_cards(reply)

        # اگر کارت تأیید اکشن هست، کارت فایل همان کد را دوباره نشان نده
        action_codes = {
            str(a.get("land_code") or "").strip()
            for a in agent_actions
            if str(a.get("type") or "").startswith("confirm_")
        }
        if action_codes:
            land_codes = [c for c in land_codes if c not in action_codes]
        strip_codes = list(land_codes) + [c for c in action_codes if c]
        if strip_codes:
            try:
                from .land_cards import strip_visible_land_codes

                reply = strip_visible_land_codes(reply, strip_codes)
            except Exception:
                pass

        reply, escalated, escalation_id = self._apply_escalation(
            ctx, text, reply, escalate_q
        )
        if not reply and agent_actions:
            reply = "جزئیات را در کارت زیر بررسی کنید."
        if reply:
            reply = enforce_response_style(
                reply, voice=ctx.voice, audience=ctx.audience
            )
            reply = sanitize_unconfirmed_action_claims(
                reply, agent_actions=agent_actions, escalated=escalated
            )

        result["reply"] = reply
        result["audience"] = ctx.audience
        result["voice"] = ctx.voice
        result["escalated"] = escalated
        if escalation_id:
            result["escalation_id"] = escalation_id
        if land_codes:
            result["land_codes"] = land_codes
            if ctx.is_admin:
                result["show_land_cards"] = True
            result["land_cards"] = land_cards_payload(
                ctx.user_key, land_codes, audience=ctx.audience
            )
        elif ctx.is_admin:
            result["land_codes"] = []
            result["land_cards"] = []
        if agent_actions:
            result["agent_actions"] = agent_actions
        cards_html = build_cards_html(
            user_key=ctx.user_key,
            audience=ctx.audience,
            reply=reply,
            land_codes=land_codes,
            agent_actions=agent_actions,
        )
        if cards_html:
            result["cards_html"] = cards_html

        self._after_reply(ctx, text, reply, land_codes, result)
        record_request_analytics(
            user_key=ctx.user_key,
            audience=ctx.audience,
            voice=ctx.voice,
            messages=messages,
            prompt_parts=prompt_parts,
            result=result,
            started=started,
        )
        return result

    def _apply_escalation(
        self,
        ctx: AssistantContext,
        text: str,
        reply: str,
        escalate_q: str | None,
    ) -> tuple[str, bool, str]:
        if escalate_q is None:
            return reply, False, ""
        esc = create_escalation(
            user_key=ctx.user_key,
            audience=ctx.audience,
            question=escalate_q or text[:200],
            user_message=text,
            thread_id=ctx.thread_id,
        )
        escalated = bool(esc.get("ok"))
        escalation_id = str(esc.get("id") or "") if escalated else ""
        if not escalated:
            self._log_warning(
                "AI escalation not saved | user=%s | err=%s",
                ctx.user_key,
                esc.get("error"),
            )
        if not reply or len(reply) < 20:
            reply = (
                "سوال شما را برای تیم وینور ثبت کردم. "
                "به‌محض دریافت پاسخ از پشتیبانی، در همین گفتگو به شما اطلاع می‌دهم."
            )
        elif "ثبت" not in reply and "تیم" not in reply:
            reply = (
                reply.rstrip()
                + "\n\nسوال شما برای تیم وینور ثبت شد؛ به‌زودی در همین چت پاسخ می‌گیرید."
            )
        return reply, escalated, escalation_id

    def _after_reply(
        self,
        ctx: AssistantContext,
        text: str,
        reply: str,
        land_codes: list[str],
        result: dict[str, Any],
    ) -> None:
        store_cached_reply(ctx.user_key, ctx.audience, text, result)
        try:
            from app.memory.service import learn_from_exchange

            learn_from_exchange(
                user_key=ctx.user_key,
                user_message=text,
                assistant_reply=reply,
                audience=ctx.audience,
                thread_id=ctx.thread_id,
                land_codes=land_codes or [],
            )
        except Exception:
            pass
        try:
            from app.supervisor.funnel_service import watch_user

            watch_user(ctx.user_key, audience=ctx.audience, voice=ctx.voice)
        except Exception:
            pass
        try:
            from app.express_partner.partner_live_memory import (
                rewrite_partner_live_memory,
            )

            if (
                ctx.user_key
                and not ctx.is_lawyer
                and not str(ctx.user_key).startswith("guest_")
            ):
                rewrite_partner_live_memory(
                    ctx.user_key, last_user=text, last_assistant=reply
                )
        except Exception:
            pass

    # --- ارجاع به ادمین وقتی API در دسترس نیست ----------------------------

    def _escalation_fallback(
        self, ctx: AssistantContext, text: str, *, reason: str
    ) -> dict[str, Any]:
        from .agent_tools import append_support_call_if_needed
        from .audience import AUDIENCE_PUBLIC

        esc = create_escalation(
            user_key=ctx.user_key,
            audience=ctx.audience,
            question=text[:200],
            user_message=text,
            thread_id=ctx.thread_id,
            reason=reason,
        )
        if reason == "balance":
            out: dict[str, Any] = {
                "ok": True,
                "reply": "به زودی به شما پاسخ خواهم داد.",
                "escalated": bool(esc.get("ok")),
                "meta": {"provider": "escalation", "reason": reason},
            }
            if esc.get("ok"):
                out["escalation_id"] = str(esc.get("id") or "")
            return out

        intro = (
            "سرویس هوش مصنوعی هنوز پیکربندی نشده است. "
            if reason == "no_key"
            else "پاسخ خودکار AI موقتاً در دسترس نیست. "
        )
        if esc.get("ok"):
            return {
                "ok": True,
                "reply": intro
                + "سوال شما برای تیم وینور ثبت شد؛ به‌زودی در همین گفتگو پاسخ می‌گیرید.",
                "escalated": True,
                "escalation_id": str(esc.get("id") or ""),
                "meta": {"provider": "escalation", "reason": reason},
            }
        err = intro + "لطفاً بعداً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید."
        return {
            "ok": False,
            "error": err,
            "error_code": "api_unavailable",
            "cards_html": append_support_call_if_needed(
                "", err, audience=AUDIENCE_PUBLIC
            ),
        }

    # --- log (هرگز مسیر چت را نمی‌شکند) ----------------------------------

    @staticmethod
    def _log_info(msg: str, *args: Any) -> None:
        try:
            current_app.logger.info(msg, *args)
        except Exception:
            pass

    @staticmethod
    def _log_warning(msg: str, *args: Any) -> None:
        try:
            current_app.logger.warning(msg, *args)
        except Exception:
            pass

    @staticmethod
    def _log_exception(msg: str) -> None:
        try:
            current_app.logger.exception(msg)
        except Exception:
            pass


def handle(
    message: str,
    *,
    user_key: str | None = None,
    audience: str | None = None,
    thread_id: str | None = None,
    chip_intent: str | None = None,
    voice: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """ورودی سطح ماژول — همان `VinorAssistant().handle`."""
    return VinorAssistant().handle(
        message,
        user_key=user_key,
        audience=audience,
        thread_id=thread_id,
        chip_intent=chip_intent,
        voice=voice,
        history=history,
    )


__all__ = ["VinorAssistant", "handle"]
