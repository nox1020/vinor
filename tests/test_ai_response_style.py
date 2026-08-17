# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest


class VinorResponseStyleTests(unittest.TestCase):
    def test_prompt_includes_style_rules_for_sales_voices(self) -> None:
        from app.ai.config import prompt_for_voice

        for voice in ("public", "partner", "special"):
            prompt = prompt_for_voice(voice)
            self.assertIn("۱ تا ۳ جمله", prompt)
            self.assertIn("قدم بعد", prompt)

    def test_postprocess_compacts_options_and_caps_lines(self) -> None:
        from app.ai.postprocess import enforce_response_style
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
        out = enforce_response_style(raw, voice="public", audience="public")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        self.assertGreaterEqual(len(lines), 1)
        self.assertLessEqual(len(lines), 8)
        self.assertIn("گزینه‌ها:", out)
        self.assertLessEqual(out.count("؟"), 1)
        # services همان تابع را برای مسیرهای قدیمی alias می‌کند
        self.assertEqual(
            _enforce_vinor_response_style(raw, voice="public", audience="public"), out
        )


if __name__ == "__main__":
    unittest.main()
