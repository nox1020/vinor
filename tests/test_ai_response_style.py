# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest


class VinorResponseStyleTests(unittest.TestCase):
    def test_prompt_includes_style_rules_for_sales_voices(self) -> None:
        from app.ai.config import prompt_for_voice

        for voice in ("public", "partner", "special"):
            prompt = prompt_for_voice(voice)
            self.assertIn("سبک پاسخ وینور (اجباری)", prompt)
            self.assertIn("۴ تا ۸ خط", prompt)
            self.assertIn("مرحله بعد:", prompt)

    def test_postprocess_compacts_options_and_caps_lines(self) -> None:
        from app.ai.services import _enforce_vinor_response_style

        raw = (
            "سلام، خیلی خوش اومدی.\n"
            "1) خرید ملک\n"
            "2) فروش ملک\n"
            "3) همکاری\n"
            "4) رزرو بازدید\n"
            "می‌تونم کامل توضیح بدم.\n"
            "دوست داری از کجا شروع کنیم؟\n"
            "یک سوال دیگر؟\n"
            "پایان"
        )
        out = _enforce_vinor_response_style(raw, voice="public", audience="public")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        self.assertGreaterEqual(len(lines), 4)
        self.assertLessEqual(len(lines), 8)
        self.assertIn("گزینه‌ها:", out)
        self.assertIn("CTA:", out)
        self.assertIn("مرحله بعد:", out)
        self.assertLessEqual(out.count("؟"), 1)


if __name__ == "__main__":
    unittest.main()
