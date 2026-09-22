# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(r"app/express_partner/templates/express_partner/partials/home_divar_ads_carousel.html")
text = p.read_text(encoding="utf-8")

css_start = text.find("  /* پاپ")
css_end_marker = "  html.vinor-home-divar-all-open {\n    overflow: hidden;\n  }\n"
css_end = text.find(css_end_marker)
if css_start < 0 or css_end < 0:
    raise SystemExit(f"css markers missing {css_start} {css_end}")
text = text[:css_start] + text[css_end + len(css_end_marker):]

modal_start = text.find('<div id="homeDivarAdsAllModal"')
script_at = text.find("<script>", modal_start)
if modal_start < 0 or script_at < 0:
    raise SystemExit(f"modal markers missing {modal_start} {script_at}")
text = text[:modal_start] + text[script_at:]

js_start = text.find("  function getAllModal()")
js_end = text.find("  function boot()")
if js_start < 0 or js_end < 0:
    raise SystemExit(f"js markers missing {js_start} {js_end}")
text = text[:js_start] + text[js_end:]

text = text.replace("    bindAllPopup();\n", "")
text = text.replace("      setPopupOpen(false);\n", "")
text = text.replace(
    """    document.addEventListener('keydown', function (ev) {
      if (!S.popupOpen) return;
      if (ev.key === 'Escape' || ev.keyCode === 27) {
        closeAllPopup(ev);
      }
    });

""",
    "",
)

if "homeDivarAdsAllModal" in text or "setPopupOpen" in text or "bindAllPopup" in text:
    raise SystemExit("leftover modal refs")

p.write_text(text, encoding="utf-8")
print("ok", len(text))
