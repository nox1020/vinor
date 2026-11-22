"""Pull-to-refresh نباید با اسکرول عمودی/افقی دعوا کند (وب و WebView اپ).

بخش اول: بررسی ایستای همهٔ handlerها؛ بخش دوم: اجرای واقعی هستهٔ express-ptr-core.js با node و DOM ساختگی.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static" / "express-partner"
EXP_TPL = ROOT / "app" / "express_partner" / "templates" / "express_partner"
CORE = STATIC / "express-ptr-core.js"

PTR_FILES = [
    STATIC / "express-pull-refresh.js",
    STATIC / "express-home-pull-refresh.js",
    EXP_TPL / "dashboard.html",
    EXP_TPL / "partials" / "commissions_scripts.html",
    ROOT / "app" / "templates" / "public" / "express_list.html",
]


def _read(p):
    return Path(p).read_text(encoding="utf-8")


def test_core_exists_and_is_loaded_before_handlers():
    assert CORE.is_file()
    for tpl in ("base.html", "auth_base.html"):
        src = _read(EXP_TPL / tpl)
        core_at = src.find("express-partner/express-ptr-core.js")
        assert core_at != -1, tpl
        head_end = src.find("</head>")
        assert core_at < head_end, f"{tpl}: core must load in <head> (inline dashboard script uses it)"
        tag = src[src.rfind("<script", 0, core_at):src.find("</script>", core_at)]
        assert "defer" not in tag and "async" not in tag, tpl
        if "express-pull-refresh.js" in src:
            assert core_at < src.find("express-pull-refresh.js")
    assert "express-ptr-core.js" in _read(ROOT / "app" / "templates" / "public" / "express_list.html")


@pytest.mark.parametrize("path", PTR_FILES, ids=lambda p: p.name)
def test_every_handler_uses_shared_core(path):
    src = _read(path)
    assert "VinorPtr.attach" in src, path.name
    # باگ قبلی: رفرش بر اساس بیشینهٔ کشش (کشیدن و برگرداندن انگشت هم رفرش می‌کرد)
    assert "maxPull" not in src, path.name
    assert "PULL_TRIGGER_PX" not in src, path.name


def test_no_blocking_touchmove_preventdefault_in_ptr():
    list_src = _read(ROOT / "app" / "templates" / "public" / "express_list.html")
    assert "passive: false" not in list_src
    assert "e.preventDefault()" not in list_src.split("Pull to Refresh", 1)[1].split("Infinite Scroll", 1)[0]
    core = _read(CORE)
    assert "preventDefault" not in core
    assert "passive: false" not in core
    assert "overscroll-behavior-y:contain" in list_src.replace(" ", "")


def test_core_rules_present():
    core = _read(CORE)
    for needle in ("innerScrolled", "inFixedLayer", "AXIS_RATIO", "g.pull >= TRIGGER", "docScrollTop() <= TOP_EPS"):
        assert needle in core, needle


NODE_HARNESS = r"""
const fs = require('fs');
function el(opts) {
  opts = opts || {};
  const e = { nodeType: 1, parentElement: opts.parent || null, scrollTop: opts.scrollTop || 0,
    _fixed: !!opts.fixed, _ignore: !!opts.ignore, _listeners: {} };
  e.closest = function () { let c = e; while (c) { if (c._ignore) return c; c = c.parentElement; } return null; };
  e.contains = function (o) { while (o) { if (o === e) return true; o = o.parentElement; } return false; };
  e.addEventListener = function (t, f) { (e._listeners[t] = e._listeners[t] || []).push(f); };
  e.removeEventListener = function () {};
  return e;
}
const html = el(); const body = el({ parent: html });
const listeners = {};
global.document = {
  documentElement: Object.assign(html, { classList: { contains: () => false }, hasAttribute: () => false }),
  body, scrollingElement: html,
  addEventListener: (t, f) => { (listeners[t] = listeners[t] || []).push(f); },
  removeEventListener: () => {},
};
global.window = global;
window.scrollY = 0; window.pageYOffset = 0;
window.getComputedStyle = (n) => ({ position: n._fixed ? 'fixed' : 'static' });
eval(fs.readFileSync(process.argv[2], 'utf8'));

const shell = el({ parent: body });
function fire(t, target, x, y) {
  const ev = { target, touches: t === 'touchend' ? [] : [{ clientX: x, clientY: y }] };
  (listeners[t] || []).forEach((f) => f(ev));
}
function gesture(target, path) {
  let refreshed = 0;
  const h = window.VinorPtr.attach({ target: document, onRefresh: () => { refreshed++; return Promise.resolve(); } });
  fire('touchstart', target, path[0][0], path[0][1]);
  for (let i = 1; i < path.length; i++) fire('touchmove', target, path[i][0], path[i][1]);
  fire('touchend', target, 0, 0);
  h.detach();
  for (const k of Object.keys(listeners)) listeners[k] = [];
  return refreshed;
}
const down = [[100, 100], [100, 115], [100, 160], [100, 200]];
const out = {};
out.plainPull = gesture(el({ parent: shell }), down);
const inner = el({ parent: shell, scrollTop: 120 });
out.innerScrolled = gesture(el({ parent: inner }), down);
out.horizontal = gesture(el({ parent: shell }), [[100, 100], [130, 104], [200, 150], [260, 200]]);
out.pullBack = gesture(el({ parent: shell }), [[100, 100], [100, 120], [100, 200], [100, 130]]);
const sheet = el({ parent: body, fixed: true });
out.fixedSheet = gesture(el({ parent: sheet }), down);
out.ignored = gesture(el({ parent: el({ parent: shell, ignore: true }) }), down);
window.scrollY = 300;
out.docScrolled = gesture(el({ parent: shell }), down);
window.scrollY = 0;
out.small = gesture(el({ parent: shell }), [[100, 100], [100, 115], [100, 150]]);
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_core_gesture_behaviour(tmp_path):
    harness = tmp_path / "h.js"
    harness.write_text(NODE_HARNESS, encoding="utf-8")
    res = subprocess.run(["node", str(harness), str(CORE)], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout.strip().splitlines()[-1])
    assert out == {
        "plainPull": 1,       # کشیدن واقعی بالای صفحه → رفرش
        "innerScrolled": 0,   # لیست/شیت داخلی اسکرول‌شده → اسکرول به بالا، نه رفرش
        "horizontal": 0,      # کاروسل/تب/کشو افقی
        "pullBack": 0,        # کشید و برگرداند
        "fixedSheet": 0,      # داخل لایهٔ fixed
        "ignored": 0,         # [data-vinor-ptr-ignore] / input / dialog
        "docScrolled": 0,     # وسط صفحه
        "small": 0,           # کمتر از آستانه
    }, out
