# This Python file uses the following encoding: utf-8

import base64
import json
import random
import re
import time

import requests

from .curds import curdCommands
from .loadConfig import configBot

_BAZAAR_PAY_METHODS = ("enough_balance", "direct_debit")
_BAZAAR_PAID_STATUSES = frozenset({"paid_committed", "paid_not_committed"})
_FA_AR_DIGITS_TR = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹" + "٠١٢٣٤٥٦٧٨٩",
    "0123456789" * 2,
)

_DIVAR_AUTH_ERROR_FA = {
    "InvalidConfirmationCode": "کد تأیید اشتباه است یا منقضی شده. کد جدید از دیوار بگیرید و دوباره بفرستید.",
    "InvalidPhoneNumber": "شماره موبایل نامعتبر است.",
    "TooManyRequests": "درخواست زیاد بود. چند دقیقه صبر کنید و دوباره امتحان کنید.",
    "RateLimited": "محدودیت درخواست دیوار. کمی بعد دوباره تلاش کنید.",
}


def normalize_phone_digits(phone) -> str:
    """شماره موبایل ایران را به فرمت 9xxxxxxxxx نرمال می‌کند."""
    s = str(phone or "").strip().translate(_FA_AR_DIGITS_TR)
    s = re.sub(r"\D", "", s)
    if s.startswith("98") and len(s) >= 12:
        s = s[2:]
    if s.startswith("0") and len(s) >= 11:
        s = s[1:]
    return s


def normalize_otp_code(code) -> str:
    """فقط رقم‌های کد OTP (فارسی/عربی/لاتین)."""
    s = str(code or "").strip().translate(_FA_AR_DIGITS_TR)
    return re.sub(r"\D", "", s)


def is_divar_auth_ok(body) -> bool:
    return isinstance(body, dict) and bool(str(body.get("token") or "").strip())


def is_otp_send_ok(body) -> bool:
    if not isinstance(body, dict):
        return False
    if int(body.get("http_status") or 0) >= 400:
        return False
    if body.get("error"):
        return False
    msg = str(body.get("message") or "").strip()
    if msg in _DIVAR_AUTH_ERROR_FA:
        return False
    return True


def format_divar_auth_error(body) -> str:
    if is_divar_auth_ok(body):
        return ""
    if not isinstance(body, dict):
        return f"❌ خطا در احراز هویت دیوار: {body}"
    msg = str(body.get("message") or body.get("error") or "").strip()
    if msg in _DIVAR_AUTH_ERROR_FA:
        return f"❌ {_DIVAR_AUTH_ERROR_FA[msg]}"
    if msg:
        return f"❌ خطای دیوار: {msg}"
    http_status = body.get("http_status")
    if http_status:
        return f"❌ خطای HTTP {http_status} از دیوار"
    return "❌ خطا در احراز هویت دیوار"


def divar_authorization_header(access_token: str) -> str:
    """
    هدر Authorization مطابق کلاینت اندروید دیوار: Basic + Base64(token + ':').
    اگر مقدار از قبل با پیشوند Basic ذخیره شده باشد، همان استفاده می‌شود.
    """
    raw = str(access_token or "").strip()
    if not raw:
        return "Basic "
    if raw.lower().startswith("basic "):
        rest = raw[6:].lstrip()
        return "Basic " + rest
    return "Basic " + base64.b64encode(f"{raw}:".encode("utf-8")).decode("ascii")


def parse_login_cookie(raw) -> tuple[str, dict]:
    """JWT یا JSON ذخیره‌شدهٔ OTP را به (token, cookies_extra) تبدیل می‌کند."""
    raw_s = str(raw or "").strip()
    if not raw_s:
        return "", {}
    if not raw_s.startswith("{"):
        return raw_s, {}
    try:
        data = json.loads(raw_s)
    except json.JSONDecodeError:
        return raw_s, {}
    if not isinstance(data, dict):
        return raw_s, {}
    token = str(data.get("token") or data.get("access_token") or "").strip()
    extras = {}
    nested = data.get("cookies")
    if isinstance(nested, dict):
        extras.update({k: str(v) for k, v in nested.items() if v is not None and str(v).strip()})
    for key in ("sessionid", "session_id", "csid", "sid", "did"):
        val = data.get(key)
        if val is not None and str(val).strip() and key not in extras:
            extras[key] = str(val).strip()
    return token or raw_s, extras


def pack_login_cookie(otp_response: dict) -> str:
    """پاسخ verifyOtp را برای ذخیره در logins.cookie آماده می‌کند."""
    if not isinstance(otp_response, dict):
        return ""
    token = str(otp_response.get("token") or "").strip()
    if not token:
        return ""
    payload = {"token": token}
    for key in ("refresh_token", "session_id", "sessionid", "device_id", "sid", "csid", "did"):
        val = otp_response.get(key)
        if val is not None and str(val).strip():
            payload[key] = str(val).strip()
    resp_cookies = otp_response.get("_response_cookies")
    if isinstance(resp_cookies, dict) and resp_cookies:
        payload["cookies"] = {k: str(v) for k, v in resp_cookies.items() if v is not None and str(v).strip()}
    if len(payload) == 1:
        return token
    return json.dumps(payload, ensure_ascii=False)


def _is_divar_promote_404_html(exc: BaseException) -> bool:
    """صفحهٔ ۴۰۴ وب دیوار برای مسیر promote اشتباه (دستهٔ نادرست)."""
    text = str(exc)
    low = text.lower()
    if "404" not in low:
        return False
    return "<!doctype html>" in low or "این راه به جایی نمی‌رسد" in text


# اسلاگ‌های رایج دسته در URL دیوار؛ وقتی از JSON حدس زده نشود به‌ترتیب امتحان می‌شوند.
PROMOTE_CATEGORY_SLUG_FALLBACKS = (
    "real-estate",
    "vehicles",
    "cars",
    "electronic-devices",
    "mobile-tablet",
    "personal-goods",
    "services",
    "business-industrial",
    "jobs",
    "animals",
    "furniture-decor",
    "leisure-hobbies",
    "wholesale",
    "bulk",
    "light",
)



# ---------------------------------------------------------------------------
# [relay] رله‌ی پرداخت دیوار
# دیوار درخواست‌های پرداخت را از IP خارج از ایران رد می‌کند (403). اگر
# divar_relay_url و رمز رله تنظیم شده باشد، فقط درخواست‌های مربوط به پرداخت/نردبان
# از طریق مسیر POST /divar-relay در web_app.py روی سرور ایران ارسال می‌شوند؛
# بقیه‌ی درخواست‌ها مستقیم می‌روند. رمز: env DIVAR_RELAY_SECRET یا configs.json.
# ---------------------------------------------------------------------------
import os as _os
from urllib.parse import urlsplit as _urlsplit

_RELAY_PLACEHOLDERS = {"", "changeme", "change-me", "secret", "your-secret", "xxx", "placeholder"}


def _relay_settings(config=None):
    cfg = config if isinstance(config, dict) else {}
    url = str(_os.environ.get("DIVAR_RELAY_URL") or cfg.get("divar_relay_url") or "").strip()
    secret = str(_os.environ.get("DIVAR_RELAY_SECRET") or cfg.get("divar_relay_secret") or "").strip()
    if not url or secret.lower() in _RELAY_PLACEHOLDERS or len(secret) < 24:
        return None, None
    if not url.lower().startswith("https://"):
        return None, None
    return url, secret


def is_divar_payment_url(url) -> bool:
    """درخواست‌هایی که باید از IP ایران بروند: costs/start/paymentcore/promote و بازارپی."""
    try:
        parts = _urlsplit(str(url))
    except Exception:
        return False
    host = (parts.hostname or "").lower()
    path = (parts.path or "").lower()
    if host == "bazaar-pay.ir" or host.endswith(".bazaar-pay.ir"):
        return True
    if host == "divar.ir" or host.endswith(".divar.ir"):
        if "/v8/payment" in path:  # payment/costs, payment/start, paymentcore/...
            return True
        if path.endswith("/promote") or "/promote/" in path:
            return True
    return False


class DivarRelaySession(requests.Session):
    """
    Session که درخواست‌های پرداخت را از طریق رله می‌فرستد و یک requests.Response
    معمولی برمی‌گرداند؛ بنابراین بقیه‌ی کد (و گاردهای ضد پرداخت دوبل) بدون تغییر کار می‌کنند.
    timeout رله به requests.exceptions.Timeout تبدیل می‌شود تا POST دوباره ارسال نشود.
    """

    def __init__(self, relay_url, relay_secret):
        super().__init__()
        self._relay_url = relay_url
        self._relay_secret = relay_secret
        self._relay_http = requests.Session()

    def request(self, method, url, params=None, data=None, headers=None, cookies=None,
                files=None, auth=None, timeout=None, allow_redirects=True, proxies=None,
                hooks=None, stream=None, verify=None, cert=None, json=None):
        if not is_divar_payment_url(url):
            return super().request(
                method, url, params=params, data=data, headers=headers, cookies=cookies,
                files=files, auth=auth, timeout=timeout, allow_redirects=allow_redirects,
                proxies=proxies, hooks=hooks, stream=stream, verify=verify, cert=cert, json=json,
            )
        req = requests.Request(
            method=str(method).upper(), url=url, headers=headers, files=files, data=data or {},
            json=json, params=params or {}, auth=auth, cookies=cookies, hooks=hooks,
        )
        prep = self.prepare_request(req)
        body = prep.body
        if isinstance(body, str):
            body = body.encode("utf-8")
        inner_timeout = timeout if isinstance(timeout, (int, float)) else 30
        envelope = {
            "method": prep.method,
            "url": prep.url,
            "headers": {k: v for k, v in prep.headers.items() if k.lower() != "content-length"},
            "body_b64": base64.b64encode(body).decode("ascii") if body else None,
            "timeout": inner_timeout,
            "allow_redirects": bool(allow_redirects),
        }
        try:
            rr = self._relay_http.post(
                self._relay_url,
                json=envelope,
                headers={"X-Relay-Secret": self._relay_secret, "Content-Type": "application/json"},
                timeout=float(inner_timeout) + 15,
            )
        except requests.exceptions.Timeout as e:
            raise requests.exceptions.Timeout(f"relay timeout: {e}")
        except requests.exceptions.RequestException as e:
            raise requests.exceptions.ConnectionError(f"relay unreachable: {e}")
        if rr.status_code != 200:
            # خطای خود رله (رمز/محدودیت/میزبان غیرمجاز) — نه پاسخ دیوار
            raise requests.exceptions.ConnectionError(
                f"relay HTTP {rr.status_code}: {(rr.text or '')[:200]}"
            )
        try:
            env = rr.json()
        except Exception:
            raise requests.exceptions.ConnectionError("relay returned non-JSON")
        if env.get("error") == "upstream_timeout":
            raise requests.exceptions.Timeout(f"upstream timeout via relay: {env.get('detail')}")
        if env.get("error"):
            raise requests.exceptions.ConnectionError(f"relay upstream error: {env.get('detail') or env.get('error')}")
        resp = requests.Response()
        resp.status_code = int(env.get("status") or 0)
        resp.headers = requests.structures.CaseInsensitiveDict(env.get("headers") or {})
        raw = env.get("body_b64")
        resp._content = base64.b64decode(raw) if raw else b""
        resp.encoding = requests.utils.get_encoding_from_headers(resp.headers) or "utf-8"
        resp.url = env.get("final_url") or prep.url
        resp.request = prep
        resp.reason = env.get("reason") or ""
        return resp


def make_divar_http_session(config=None):
    url, secret = _relay_settings(config)
    if url and secret:
        return DivarRelaySession(url, secret)
    return requests.Session()


class api:
    def __init__(self):
        self.author = "ATRISK"
        self.headers = {
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13; SM-S918B Build/TP1A.220624.014)",
            "X-Device-Model": "SM-S918B",
            "X-OS-Version": "13",
            "X-Platform": "android",
            "Content-Type": "application/json",
            "Accept": "*/*"
        }
    
    def login(self, phone: str):
        url = "https://api.divar.ir/v5/auth/authenticate"
        data = {"phone": normalize_phone_digits(phone)}
        max_retries = 2
        for attempt in range(max_retries):
            try:
                response = requests.post(url=url, headers=self.headers, json=data, timeout=25)
                try:
                    body = response.json()
                except Exception:
                    body = {"error": f"invalid json response: {response.text[:200]}"}
                # در پاسخ خطا، status code را نیز برگردان
                if response.status_code >= 400 and isinstance(body, dict):
                    body.setdefault("http_status", response.status_code)
                return body
            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    time.sleep(1.5)
                    continue
                return {"error": "timeout while sending OTP"}
            except requests.exceptions.RequestException as e:
                return {"error": f"request failed: {str(e)}"}

    def verifyOtp(self, phone: str, code: str):
        url = "https://api.divar.ir/v5/auth/confirm"
        data = {
            "phone": normalize_phone_digits(phone),
            "code": normalize_otp_code(code),
        }
        max_retries = 2
        for attempt in range(max_retries):
            try:
                response = requests.post(url=url, headers=self.headers, json=data, timeout=25)
                try:
                    body = response.json()
                except Exception:
                    body = {"error": f"invalid json response: {response.text[:200]}"}
                if response.status_code >= 400 and isinstance(body, dict):
                    body.setdefault("http_status", response.status_code)
                if isinstance(body, dict) and response.cookies:
                    jar = requests.utils.dict_from_cookiejar(response.cookies)
                    if jar:
                        body["_response_cookies"] = jar
                return body  # token is : {'token':''}
            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    time.sleep(1.5)
                    continue
                return {"error": "timeout while verifying OTP"}
            except requests.exceptions.RequestException as e:
                return {"error": f"request failed: {str(e)}"}

class nardeban:
    def __init__(self,apiKey):
        self.Datas = configBot()
        self.curd = curdCommands(self.Datas)
        self.apikey, _login_cookies = parse_login_cookie(apiKey)
        if not self.apikey:
            self.apikey = str(apiKey or "").strip()
        # Header اصلی برای درخواست‌های نردبان
        self.headers = {
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13; SM-S918B Build/TP1A.220624.014)",
            "X-Device-Model": "SM-S918B",
            "X-OS-Version": "13",
            "X-Platform": "android",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Authorization": divar_authorization_header(str(self.apikey)),
        }
        self.cookies = {
            '_ga': 'GA1.2.600389233.1620222355',
            '_ga_SXEW31VJGJ': 'GS1.1.1727021501.44.1.1727022691.56.0.0',
            'did': '4fd58ceb-b62e-4eba-aa9b-29ab65717dc7',
            'FEATURE_FLAG': '%7B%22flags%22%3A%7B%22location_selector_enabled%22%3A%7B%22name%22%3A%22location_selector_enabled%22%2C%22bool_value%22%3Afalse%7D%2C%22location_selector_ux_adaption%22%3A%7B%22name%22%3A%22location_selector_ux_adaption%22%2C%22bool_value%22%3Afalse%7D%2C%22location_selector_enabled_with_defaults%22%3A%7B%22name%22%3A%22location_selector_enabled_with_defaults%22%2C%22bool_value%22%3Afalse%7D%2C%22custom_404_experiment%22%3A%7B%22name%22%3A%22custom_404_experiment%22%2C%22bool_value%22%3Atrue%7D%2C%22web_shopping_assistant_enabled%22%3A%7B%22name%22%3A%22web_shopping_assistant_enabled%22%2C%22bool_value%22%3Afalse%7D%2C%22web_shopping_assistant_enabled_on_all_cats%22%3A%7B%22name%22%3A%22web_shopping_assistant_enabled_on_all_cats%22%2C%22bool_value%22%3Afalse%7D%2C%22explore%22%3A%7B%22name%22%3A%22explore%22%2C%22bool_value%22%3Afalse%7D%2C%22enable_new_post_card_web%22%3A%7B%22name%22%3A%22enable_new_post_card_web%22%2C%22bool_value%22%3Afalse%7D%2C%22web_show_ios_appstore_promotion_banner%22%3A%7B%22name%22%3A%22web_show_ios_appstore_promotion_banner%22%2C%22bool_value%22%3Afalse%7D%2C%22chat_translate_enabled%22%3A%7B%22name%22%3A%22chat_translate_enabled%22%2C%22bool_value%22%3Atrue%7D%2C%22post-card-title-top%22%3A%7B%22name%22%3A%22post-card-title-top%22%2C%22bool_value%22%3Atrue%7D%2C%22post-card-small-img%22%3A%7B%22name%22%3A%22post-card-small-img%22%2C%22bool_value%22%3Afalse%7D%2C%22map_discovery_halfMapTest_active%22%3A%7B%22name%22%3A%22map_discovery_halfMapTest_active%22%2C%22bool_value%22%3Afalse%7D%2C%22map_discovery_halfMapTest_map_state%22%3A%7B%22name%22%3A%22map_discovery_halfMapTest_map_state%22%2C%22string_value%22%3A%22HALF_MAP%22%7D%7D%2C%22evaluatedAt%22%3A%222024-09-22T16%3A11%3A40.117895503Z%22%2C%22maximumCacheUsageSecondsOnError%22%3A86400%2C%22minimumRefetchIntervalSeconds%22%3A3600%2C%22expireDate%22%3A1727025100125%7D',
            '_gcl_au': '1.1.1878132329.1726746171',
            'LANGUAGE': 'fa',
            'theme': 'light',
            "token": str(self.apikey),
            "_gid": "GA1.2.766956976.1727008200",
            # کلاینت اندروید دیوار معمولاً access-token را هم می‌فرستد؛ خالی بودن گاهی paymentcore را 401 می‌کند.
            "access-token": str(self.apikey),
            'chat_opened': '',
            'sessionid': '',
            'csid': '',
            '_gat': '1',
            '_gat_UA-32884252-2': '1',
        }
        for ck, cv in (_login_cookies or {}).items():
            if cv is not None and str(cv).strip():
                self.cookies[ck] = str(cv).strip()
        user_type = self._jwt_claim(self.apikey, "user-type")
        if user_type:
            self.headers["X-User-Type"] = str(user_type)
        # [relay] درخواست‌های پرداخت در صورت تنظیم رله از سرور ایران می‌روند
        self._http = make_divar_http_session(getattr(self.Datas, "config", None))

    @staticmethod
    def _jwt_claim(token: str, claim: str) -> str | None:
        raw = str(token or "").strip()
        if not raw or raw.startswith("{"):
            return None
        parts = raw.split(".")
        if len(parts) < 2:
            return None
        try:
            pad = parts[1] + "=" * (-len(parts[1]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(pad))
        except Exception:
            return None
        val = payload.get(claim) if isinstance(payload, dict) else None
        return str(val).strip() if val is not None and str(val).strip() else None

    @staticmethod
    def _normalize_ir_mobile_for_bazaar_pay(number) -> str:
        """
        ده رقم موبایل ایران (۹xxxxxxxx) برای پارامتر phone در بازارپی.
        اگر با ۰ یا ۹۸ ذخیره شده باشد، اصلاح می‌شود تا دیگر ۹۸۰۹۱… ساخته نشود.
        """
        trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
        s = str(number).strip().translate(trans).replace(" ", "").replace("-", "")
        if s.startswith("+98"):
            s = s[3:]
        elif s.startswith("0098"):
            s = s[4:]
        elif s.startswith("98") and len(s) >= 12:
            s = s[2:]
        if s.startswith("0"):
            s = s[1:]
        if not s.isdigit():
            raise ValueError(f"invalid mobile for BazaarPay (non-digit): {number!r}")
        if len(s) != 10 or not s.startswith("9"):
            raise ValueError(f"invalid Iranian mobile format for BazaarPay: {number!r}")
        return s

    def _response_error_message(self, response):
        """خلاصهٔ خوانا از خطای HTTP برای لاگ و humanize."""
        if response is None:
            return "HTTP ?: no response"
        code = response.status_code
        try:
            j = response.json()
            if isinstance(j, dict):
                err = j.get("error")
                if isinstance(err, dict):
                    piece = (
                        err.get("message")
                        or err.get("detail")
                        or err.get("type")
                        or err.get("code")
                    )
                    body_snip = str(piece).strip() if piece is not None else ""
                elif isinstance(err, str):
                    body_snip = err.strip()
                else:
                    body_snip = ""
                if not body_snip:
                    body_snip = str(
                        j.get("message") or j.get("detail") or j.get("title") or ""
                    ).strip()[:220]
            else:
                body_snip = str(j)[:220]
        except Exception:
            body_snip = (response.text or "").replace("\n", " ").strip()[:220]
        body_snip = body_snip.strip()
        if body_snip:
            return f"HTTP {code}: {body_snip}"
        return f"HTTP {code}"

    def _request_with_retries(self, method, url, *, headers=None, json_data=None, retries=4, timeout=32):
        hdr = dict(headers or self.headers)
        last = None
        for attempt in range(retries):
            try:
                if method.upper() == "POST":
                    last = self._http.post(url, headers=hdr, cookies=self.cookies, json=json_data, timeout=timeout)
                else:
                    last = self._http.get(url, headers=hdr, cookies=self.cookies, timeout=timeout)
            except requests.exceptions.Timeout as e:
                # [audit] POST بعد از timeout ممکن است سمت سرور اجرا شده باشد؛ دوباره ارسال نکن
                if method.upper() != "POST" and attempt < retries - 1:
                    time.sleep(2 + random.uniform(0, 0.65))
                    continue
                raise ValueError(f"Request timeout after {attempt + 1} attempts: {e}")
            except requests.exceptions.RequestException as e:
                raise ValueError(f"Request failed: {e}")
            if last.status_code == 429 and attempt < retries - 1:
                time.sleep(2.0 * (attempt + 1) + random.uniform(0.35, 1.0))
                continue
            if 500 <= last.status_code <= 599 and method.upper() != "POST" and attempt < retries - 1:
                time.sleep(1.2 + random.uniform(0.25, 0.75))
                continue
            break
        if last is None:
            raise ValueError("Request failed: no response received after all retries")
        if last.status_code != 200:
            raise ValueError(self._response_error_message(last))
        return last

    def _between_payment_steps(self):
        """فاصلهٔ کوتاه و تصادفی بین مراحل پرداخت؛ الگوی زمان‌بندی یکنواخت کمتر می‌شود."""
        time.sleep(random.uniform(0.45, 1.35))

    def _between_list_pages(self):
        """فاصلهٔ کوتاه بین صفحات اسکرول نامحدود لیست آگهی؛ فشار به API کمتر و الگو طبیعی‌تر می‌شود."""
        time.sleep(random.uniform(0.28, 0.95))

    def _post_divar_post_list(self, brand_token, json_data, headers):
        """
        درخواست post-list با timeout و یک‌دو بار تلاش مجدد روی 429 / قطع شبکه.
        """
        url = f'https://api.divar.ir/v8/premium-user/web/business/{brand_token}/post-list'
        last_response = None
        for attempt in range(3):
            try:
                last_response = self._http.post(
                    url,
                    headers=headers,
                    json=json_data,
                    cookies=self.cookies,
                    timeout=35,
                )
            except requests.exceptions.Timeout:
                if attempt < 2:
                    time.sleep(1.2 + random.uniform(0, 0.7))
                    continue
                raise
            except requests.exceptions.RequestException:
                if attempt < 2:
                    time.sleep(0.8 + random.uniform(0, 0.5))
                    continue
                raise
            if last_response.status_code == 429 and attempt < 2:
                time.sleep(2.2 * (attempt + 1) + random.uniform(0.25, 0.9))
                continue
            return last_response
        return last_response

    def get_cost_plans(self, token):
        hdr = {**self.headers, "Authorization": divar_authorization_header(str(self.apikey))}
        try:
            response_data = self._request_with_retries(
                "GET", f"https://api.divar.ir/v8/payment/costs/{token}", headers=hdr
            ).json()
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"invalid costs response: {e}")
        if not isinstance(response_data, dict) or "costs" not in response_data:
            raise ValueError(f"costs not found in response: {response_data}")
        costs = response_data["costs"]
        if not isinstance(costs, list):
            raise ValueError(f"costs is not a list: {type(costs)}")
        if len(costs) == 0:
            raise ValueError("no costs/plans available for this post")

        normalized = []
        for row in costs:
            if not isinstance(row, dict):
                continue
            pid = row.get("id")
            if pid is None:
                continue
            try:
                pid_int = int(pid)
            except Exception:
                continue
            normalized.append(
                {
                    "id": pid_int,
                    "available": bool(row.get("available", False)),
                    "name": str(row.get("title") or row.get("name") or f"پلن {pid_int}"),
                    "price": row.get("price"),
                }
            )
        if not normalized:
            raise ValueError("no valid cost plans in response")
        return normalized

    def selectPlan(self, token, priority_1=None, priority_2=None):
        plans = self.get_cost_plans(token)
        available_ids = [p["id"] for p in plans if p.get("available")]
        if not available_ids:
            raise ValueError("no available plans for this post")

        preferred = []
        for raw in (priority_1, priority_2):
            if raw is None or raw == "":
                continue
            try:
                preferred.append(int(raw))
            except Exception:
                continue

        for pid in preferred:
            if pid in available_ids:
                return pid

        # fallback: همان رفتار قبلی (اگر اندیس 2 موجود و available بود)
        if len(plans) >= 3 and plans[2].get("available") and plans[2].get("id"):
            return int(plans[2]["id"])
        return int(available_ids[0])

    @staticmethod
    def _is_transient_error(error) -> bool:
        """خطاهای شبکه/موقت که یک بار دیگر همان توکن قابل تلاش است."""
        txt = str(error or "").lower()
        return any(
            x in txt
            for x in (
                "timeout",
                "timed out",
                "connection reset",
                "connection aborted",
                "remotedisconnected",
                "forcibly closed",
                "read error",
                "429",
                "502",
                "503",
                "504",
                "temporarily",
                "کندی ارتباط",
            )
        )

    @staticmethod
    def _error_kind(raw_error, humanized=None) -> str:
        """
        دسته‌بندی خطا برای واکنش نردبان:
        login = توقف لاگین (کیف/OTP/بازارپی) — آگهی pending می‌ماند
        ad = رد همان آگهی و ادامه صف
        transient = قبلاً با retry جدا شده
        """
        txt = f"{raw_error or ''} {humanized or ''}".lower()
        if nardeban._is_transient_error(txt):
            return "transient"

        login_markers = (
            "412",
            "insufficient",
            "not enough",
            "enough_balance",
            "موجودی",
            "invalid iranian mobile",
            "invalid mobile for bazaarpay",
            "شمارهٔ همین لاگین برای بازارپی",
            "پرداخت سریع",
            "پرداخت مستقیم",
            "هیچ درگاه",
            "درگاه مناسب",
            "no suitable",
            "no gateway",
            "checkout still unpaid",
            "وضعیت نهایی «پرداخت‌شده» نشد",
            "نشست دیوار",
            "بازارپی این پرداخت را رد کرد",
            "احراز، توکن خرید",
        )
        if any(m in txt for m in login_markers):
            return "login"
        if re.search(r"\bhttp\s+401\b", txt) or re.search(r"\bhttp\s+403\b", txt):
            return "login"
        if ("unauthorized" in txt or "forbidden" in txt) and "rate limit" not in txt:
            return "login"

        ad_markers = (
            "no available plans",
            "no costs/plans",
            "costs not found",
            "invalid costs response",
            "پلن قابل پرداختی",
            "اطلاعات پلن",
        )
        if any(m in txt for m in ad_markers):
            return "ad"
        return "ad"

    def _mark_token_failed(self, chatid, phone, token, reason=""):
        """آگهی از صف خارج می‌شود تا بلافاصله سراغ بعدی برویم."""
        why = str(reason or "").strip()
        if why:
            print(f"[nardeban] رد توکن {token}: {why[:160]}")
        else:
            print(f"[nardeban] رد توکن {token} → آگهی بعدی")
        self.curd.addSent(token=token, chatid=chatid, status="failed")
        try:
            from .tokens_manager import update_token_status

            update_token_status(
                chatid=chatid, phone=int(phone), token=token, new_status="failed"
            )
        except Exception as ex:
            print(f"[nardeban] به‌روزرسانی JSON برای {token}: {ex}")

    def _run_nardeban_pipeline(self, chatid, number, token, plan_cost):
        """اجرای مراحل پرداخت و promote برای یک توکن."""
        self._between_payment_steps()
        try:
            order_id = self.createOrderID(token=token, planPrice=plan_cost)
        except Exception as e:
            return self._payment_step_failed(chatid, token, "createOrderID", e)
        self._between_payment_steps()
        try:
            checkout_data = self.createCheckOut(order=order_id)
        except Exception as e:
            return self._payment_step_failed(chatid, token, "createCheckOut", e)
        self._between_payment_steps()
        try:
            self.createFlow(order=order_id)
        except Exception as e:
            print(f"[payment] createFlow نادیده گرفته شد: {e}")
        self._between_payment_steps()
        try:
            self.pay(
                orderid=order_id,
                checkout=checkout_data.get("checkout_token"),
                number=str(number),
                init_data=checkout_data,
            )
        except Exception as e:
            return self._payment_step_failed(chatid, token, "pay", e)
        self._between_payment_steps()
        try:
            self.promote(orderid=order_id, token=token)
        except Exception as e:
            return self._payment_step_failed(chatid, token, "promote", e)
        self.curd.addSent(token=token, chatid=chatid, status="success")
        return [1, token, number]

    def createOrderID(self, token, planPrice):
        response_data = self._request_with_retries(
            "POST",
            f"https://api.divar.ir/v8/payment/start/post/{token}",
            json_data={"cost_ids": [planPrice], "cost_to_option": {}},
        ).json()
        if not isinstance(response_data, dict):
            raise ValueError(f"response is not a dict: {type(response_data)}")
        order_id = response_data.get("order_id")
        if not order_id:
            raise ValueError(f"order_id not found in response: {response_data}")
        return order_id

    def _divar_get_headers_for_paymentcore(self, authorization: str) -> dict:
        """هدر سبک برای GET به paymentcore (بدون Content-Type)."""
        return {
            "User-Agent": self.headers["User-Agent"],
            "X-Device-Model": self.headers["X-Device-Model"],
            "X-OS-Version": self.headers["X-OS-Version"],
            "X-Platform": self.headers["X-Platform"],
            "Accept": "*/*",
            "Authorization": authorization,
            "Referer": "https://divar.ir/",
            "Origin": "https://divar.ir",
        }

    def _authorization_strategies(self):
        raw = str(self.apikey).strip()
        if not raw:
            raise ValueError("Divar access token is empty")
        if raw.lower().startswith("basic "):
            yield raw
            return
        enc = divar_authorization_header(raw)
        yield enc
        legacy = f"Basic {raw}"
        if legacy != enc:
            yield legacy
        yield f"Bearer {raw}"

    def _divar_auth_probe_request(
        self,
        url: str,
        *,
        method: str = "GET",
        json_body=None,
        timeout: float = 28,
    ):
        """
        چند حالت Authorization + هدر سبک/کامل + X-Access-Token؛ روی 401/403 به ترکیب بعدی می‌رود.
        برای خطاهای غیراحراز فوراً می‌پرد.
        """
        last_resp = None
        raw_tok = str(self.apikey).strip()
        for auth in self._authorization_strategies():
            bases = (
                self._divar_get_headers_for_paymentcore(auth),
                {**self.headers, "Authorization": auth, "Referer": "https://divar.ir/", "Origin": "https://divar.ir"},
            )
            for base in bases:
                for extra in (None, {"X-Access-Token": raw_tok}):
                    hdr = dict(base)
                    if extra:
                        hdr.update(extra)
                    r = None
                    for attempt in range(2):
                        if method.upper() == "GET":
                            r = self._http.get(url, headers=hdr, cookies=self.cookies, timeout=timeout)
                        else:
                            r = self._http.post(
                                url,
                                headers=hdr,
                                cookies=self.cookies,
                                json=json_body if json_body is not None else {},
                                timeout=timeout,
                            )
                        if r.status_code == 429 and attempt == 0:
                            time.sleep(1.45 + random.uniform(0.25, 0.85))
                            continue
                        break
                    last_resp = r
                    if r is not None and r.status_code < 400:
                        return r
                    if r is not None and r.status_code not in (401, 403):
                        raise ValueError(self._response_error_message(r))
        raise ValueError(self._response_error_message(last_resp))

    def _paymentcore_get(self, path_suffix: str):
        url = f"https://api.divar.ir/v8/paymentcore/{str(path_suffix).lstrip('/')}"
        return self._divar_auth_probe_request(url, method="GET", timeout=28)

    def _paymentcore_post(self, path_suffix: str, json_body=None):
        url = f"https://api.divar.ir/v8/paymentcore/{str(path_suffix).lstrip('/')}"
        return self._divar_auth_probe_request(
            url, method="POST", json_body=json_body if json_body is not None else {}, timeout=28
        )

    @staticmethod
    def _bazaar_pay_redirect_url(orderid, checkout_token: str, mobile_10: str) -> str:
        return (
            f"https://cafebazaar.ir/bazaar-pay/payment/status?token={checkout_token}"
            f"&phone=98{mobile_10}&callback=%7B%22url%22%3A%22https%3A%2F%2Fapi.divar.ir%2Fv8%2Fpaymentcore%2Fbazaarpay%2Fcallback%2F{orderid}%22%2C%22method%22%3A%22post%22%2C%22data%22%3A%7B%7D%7D&auth_mode=authenticated_token"
        )

    def _pay_methods_to_try(self, init_data: dict) -> list[str]:
        methods: list[str] = []
        if isinstance(init_data, dict):
            for key in ("method", "payment_method", "default_method", "default_payment_method"):
                raw = init_data.get(key)
                if raw is not None and str(raw).strip():
                    methods.append(str(raw).strip())
        for fallback in _BAZAAR_PAY_METHODS:
            if fallback not in methods:
                methods.append(fallback)
        out: list[str] = []
        for m in methods:
            if m and m not in out:
                out.append(m)
        return out

    @staticmethod
    def _is_pay_method_retryable(error_text: str) -> bool:
        txt = str(error_text or "").lower()
        return any(
            x in txt
            for x in (
                "هیچ درگاه",
                "درگاه مناسب",
                "no suitable",
                "no gateway",
                "method",
                "not supported",
                "invalid method",
                "پرداخت سریع",
                "سرویس پرداخت سریع",
                "فعال نکرده",
                "412",
                "موجودی حساب",
                "موجودی",
                "insufficient",
                "not enough",
                "balance",
                "checkout still unpaid",
            )
        )

    def _bazaar_checkout_trace_status(self, checkout_token: str) -> str | None:
        checkout_token = str(checkout_token or "").strip()
        if not checkout_token:
            return None
        try:
            r = self._http.post(
                "https://api.bazaar-pay.ir/badje/v1/trace/",
                json={"checkout_token": checkout_token},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=18,
            )
            if r.status_code >= 400:
                return None
            return str((r.json() or {}).get("status") or "").strip() or None
        except Exception as ex:
            print(f"[payment] trace status failed: {ex}")
            return None

    def _wait_checkout_paid(self, order_id, checkout_token, attempts=5) -> bool:
        """پس از pay موفق HTTP، چند بار trace را برای تأیید خودکار چک می‌کند."""
        checkout = str(checkout_token or "").strip()
        if not checkout:
            return False
        for i in range(max(1, attempts)):
            if self._bazaar_checkout_trace_status(checkout) in _BAZAAR_PAID_STATUSES:
                return True
            if i < attempts - 1:
                time.sleep(1.0 + random.uniform(0.15, 0.55))
        return False

    def _bazaar_pay_payload_variants(
        self, checkout_token, redirect_url, mobile, method
    ) -> list[dict]:
        """چند شکل payload مطابق کلاینت دیوار/بازارپی؛ auth_token+phone اول امتحان می‌شود."""
        base = {
            "checkout_token": checkout_token,
            "method": method,
            "redirect_url": redirect_url,
        }
        auth = str(self.apikey or "").strip()
        variants: list[dict] = []
        if auth and not auth.startswith("{"):
            variants.append({**base, "phone": f"98{mobile}", "auth_token": auth})
            variants.append({**base, "auth_token": auth})
        variants.extend(
            [
                {**base, "phone": f"98{mobile}"},
                dict(base),
            ]
        )
        seen: list[str] = []
        out: list[dict] = []
        for p in variants:
            key = json.dumps(p, sort_keys=True, ensure_ascii=False)
            if key not in seen:
                seen.append(key)
                out.append(p)
        return out

    def _try_divar_bazaar_autopay(self, order_id, checkout_token, mobile) -> bool:
        """پرداخت خودکار از پروکسی paymentcore دیوار (در صورت دسترسی)."""
        oid = str(order_id or "").strip()
        checkout = str(checkout_token or "").strip()
        if not oid or not checkout:
            return False
        bodies = [
            {"checkout_token": checkout, "method": "enough_balance"},
            {"checkout_token": checkout, "method": "direct_debit"},
            {
                "checkout_token": checkout,
                "method": "enough_balance",
                "phone": f"98{mobile}",
            },
        ]
        for path in (f"bazaarpay/pay/{oid}", "bazaarpay/pay"):
            for body in bodies:
                try:
                    self._paymentcore_post(path, body)
                    if self._wait_checkout_paid(oid, checkout, attempts=4):
                        print(f"[payment] Divar autopay OK via {path}")
                        return True
                except ValueError as e:
                    print(f"[payment] Divar {path} ناموفق: {e}")
        return False

    def _try_fetch_divar_direct_pay_contract(self, order_id, checkout_token) -> str | None:
        """قرارداد دایرکت‌پی ذخیره‌شده در دیوار (در صورت فعال بودن توسط کاربر)."""
        oid = str(order_id or "").strip()
        checkout = str(checkout_token or "").strip()
        if not oid or not checkout:
            return None
        url = "https://api.divar.ir/v8/paymentcore/bazaar-pay/direct-pay/contract/"
        for body in (
            {"order_id": oid, "checkout_token": checkout},
            {"order_id": oid},
            {"checkout_token": checkout},
        ):
            try:
                r = self._http.post(
                    url,
                    headers=self.headers,
                    cookies=self.cookies,
                    json=body,
                    timeout=22,
                )
                if r.status_code >= 400:
                    continue
                data = r.json()
                if not isinstance(data, dict):
                    continue
                for key in ("contract_token", "direct_pay_contract_token", "token"):
                    val = data.get(key)
                    if val is not None and str(val).strip():
                        return str(val).strip()
            except Exception:
                continue
        return None

    def _post_bazaar_pay(self, payload: dict):
        headers = {
            "User-Agent": self.headers["User-Agent"],
            "X-Device-Model": self.headers["X-Device-Model"],
            "X-OS-Version": self.headers["X-OS-Version"],
            "X-Platform": self.headers["X-Platform"],
            "Content-Type": "application/json",
            "Accept": "*/*",
        }
        checkout = payload.get("checkout_token")
        params = {"checkout_token": checkout} if checkout else None
        r = None
        for attempt in range(2):
            r = self._http.post(
                "https://api.bazaar-pay.ir/badje/v1/pay/",
                params=params,
                headers=headers,
                json=payload,
                timeout=28,
            )
            if r.status_code == 429 and attempt == 0:
                time.sleep(2.0 + random.uniform(0.35, 1.1))
                continue
            break
        if r is None or r.status_code >= 400:
            raise ValueError(f"BazaarPay {self._response_error_message(r)}")
        return r

    def _post_bazaar_direct_pay(self, contract_token: str, checkout_token: str):
        headers = {
            "User-Agent": self.headers["User-Agent"],
            "Content-Type": "application/json",
            "Accept": "*/*",
        }
        payload = {
            "contract_token": str(contract_token).strip(),
            "checkout_token": str(checkout_token).strip(),
        }
        r = None
        for attempt in range(2):
            r = self._http.post(
                "https://api.bazaar-pay.ir/badje/v1/direct-pay/",
                headers=headers,
                json=payload,
                timeout=28,
            )
            if r.status_code == 429 and attempt == 0:
                time.sleep(2.0 + random.uniform(0.35, 1.1))
                continue
            break
        if r is None or r.status_code >= 400:
            raise ValueError(f"BazaarPay direct-pay {self._response_error_message(r)}")
        return r

    def createFlow(self, order):
        oid = str(order).strip()
        url = f"https://api.divar.ir/v8/paymentcore/flow/{oid}"
        last_err = None
        # ابتدا همان سبک createOrderID (هدر + کوکی)، بعد auth probe
        for use_probe in (False, True):
            for method, jb in (("GET", None), ("POST", {})):
                try:
                    if use_probe:
                        self._divar_auth_probe_request(
                            url, method=method, json_body=jb, timeout=28
                        )
                        return
                    if method == "GET":
                        r = self._http.get(
                            url, headers=self.headers, cookies=self.cookies, timeout=28
                        )
                    else:
                        r = self._http.post(
                            url,
                            headers=self.headers,
                            cookies=self.cookies,
                            json=jb if jb is not None else {},
                            timeout=28,
                        )
                    if r.status_code < 400:
                        return
                    last_err = ValueError(self._response_error_message(r))
                except ValueError as e:
                    last_err = e
                    continue
        print(f"[payment] createFlow رد شد (GET و POST هر دو ناموفق): {last_err}")

    def createCheckOut(self, order):
        try:
            response = self._paymentcore_get(f"bazaarpay/initiate/{order}")
            data = response.json()
            if not isinstance(data, dict) or "checkout_token" not in data:
                raise ValueError(f"checkout_token not found in response: {data}")
            return data
        except ValueError:
            raise
        except Exception as e:
            print(f"Error in createCheckOut: {e}")
            raise

    def pay(self, orderid, checkout, number, init_data=None):
        init_data = init_data if isinstance(init_data, dict) else {}
        checkout_token = str(
            checkout or init_data.get("checkout_token") or ""
        ).strip()
        if not checkout_token:
            raise ValueError("checkout_token is empty")

        mobile = self._normalize_ir_mobile_for_bazaar_pay(number)
        redirect_url = self._bazaar_pay_redirect_url(orderid, checkout_token, mobile)
        oid = str(orderid).strip()

        contract_token = (
            init_data.get("contract_token")
            or init_data.get("direct_pay_contract_token")
            or self._try_fetch_divar_direct_pay_contract(orderid, checkout_token)
        )
        if contract_token:
            try:
                self._post_bazaar_direct_pay(contract_token, checkout_token)
                if self._wait_checkout_paid(oid, checkout_token):
                    return
            except ValueError as e:
                print(f"[payment] direct-pay ناموفق، ادامه با pay/: {e}")

        last_err: ValueError | None = None
        for method in self._pay_methods_to_try(init_data):
            for payload in self._bazaar_pay_payload_variants(
                checkout_token, redirect_url, mobile, method
            ):
                try:
                    self._post_bazaar_pay(payload)
                    if self._wait_checkout_paid(oid, checkout_token):
                        return
                    raise ValueError(
                        f"BazaarPay pay/{method} HTTP OK but checkout still unpaid"
                    )
                except ValueError as e:
                    last_err = e
                    if self._is_pay_method_retryable(str(e)):
                        continue
                    raise
            if last_err and self._is_pay_method_retryable(str(last_err)):
                print(f"[payment] pay/{method} ناموفق، روش بعدی: {last_err}")

        if self._try_divar_bazaar_autopay(oid, checkout_token, mobile):
            return

        if last_err is not None:
            raise last_err
        raise ValueError("BazaarPay pay failed: no method succeeded")

    def _guess_promote_category_slug(self, post_token: str) -> str | None:
        """از پاسخ post-management-page دنبال مسیر .../<slug>/admin/posts/ می‌گردد."""
        try:
            r = self._http.get(
                f"https://api.divar.ir/v8/post-management-page/web-page/{post_token}",
                headers=self.headers,
                cookies=self.cookies,
                timeout=22,
            )
            if r.status_code != 200 or not r.text:
                return None
            text = r.text
            for pat in (
                r"https://divar\.ir/([a-z0-9_-]+)/admin/posts/",
                r'https:\\/\\/divar\.ir\\/([a-z0-9_-]+)\\/admin/posts\\/',
                r'"/([a-z0-9_-]+)/admin/posts/',
                r"/([a-z0-9_-]+)/admin/posts/",
            ):
                m = re.search(pat, text, re.I)
                if not m:
                    continue
                slug = m.group(1).lower()
                if slug not in ("www", "open", "s", "divar"):
                    return m.group(1)
        except Exception as ex:
            print(f"[promote] حدس slug دسته ناموفق: {ex}")
        return None

    def promote(self, orderid, token):
        """
        اعمال نردبان در وب دیوار؛ دسته در URL باید با دستهٔ آگهی یکی باشد.
        اگر همهٔ مسیرها ۴۰۴ صفحهٔ وب باشد، پرداخت معمولاً از قبل با callback ثبت شده → خطا نمی‌دهیم.
        """
        oid = str(orderid).strip()
        pt = str(token).strip()
        guessed = self._guess_promote_category_slug(pt)
        slugs = []
        if guessed:
            slugs.append(guessed)
        for s in PROMOTE_CATEGORY_SLUG_FALLBACKS:
            if s not in slugs:
                slugs.append(s)

        last_err: ValueError | None = None
        only_not_found = True
        for cat in slugs:
            url = f"https://divar.ir/{cat}/admin/posts/{pt}/promote?payment_order_id={oid}"
            try:
                self._divar_auth_probe_request(url, method="GET", timeout=28)
                return
            except ValueError as e:
                last_err = e
                if _is_divar_promote_404_html(e):
                    continue
                only_not_found = False
                raise

        if only_not_found and last_err is not None:
            print(
                f"[promote] مسیر promote برای دستهٔ درست پیدا نشد (۴۰۴). "
                f"احتمال زیاد نردبان از callback دیوار بعد از پرداخت اعمال شده است. token={pt[:12]}…"
            )
            return
        if last_err is not None:
            raise last_err

    def isValidPost(self, uid):
        response = self._http.get(
            f"https://api.divar.ir/v8/post-management-page/web-page/{uid}",
            headers=self.headers,
            cookies=self.cookies,
            timeout=22,
        )
        if response.status_code != 200:
            return 0
        try:
            isValid = response.json()['show_delete_post']
        except Exception as e:
            print(e)
            return 0
        else:
            if isValid == True:
                return 1
            else:
                return 0
    def getPosts(self):
        tokens = []
        brantToken = self.getBranToken()
        if not brantToken:
            return tokens
        json_data = {
            'brand_token': brantToken,
            'specification': {
                'query': '',
                'last_item_identifier': '',
            },
        }
        response = self._post_divar_post_list(brantToken, json_data, self.headers)
        if response is None or response.status_code != 200:
            return tokens
        try:
            res = response.json()
        except Exception:
            return tokens
        widgets = res.get('page', {}).get('widget_list', [])
        for idx, i in enumerate(widgets):
            if idx and idx % 7 == 0:
                time.sleep(random.uniform(0.08, 0.28))
            try:
                token = i['uid']
            except Exception as e:
                print(e)
                pass
            else:
                if token not in tokens:
                    if self.isValidPost(uid=token) == 1:
                        tokens.append(token)
        return tokens

    def _fetch_tokens_by_keywords(self, keywords, brand_token=None):
        """
        Helper برای دریافت آگهی‌ها که برچسب‌شان شامل هر یک از کلمات کلیدی باشد.
        """
        if not brand_token:
            brand_token = self.getBranToken()
        if not brand_token:
            return []

        headers = {
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13; SM-S918B Build/TP1A.220624.014)",
            "X-Device-Model": "SM-S918B",
            "X-OS-Version": "13",
            "X-Platform": "android",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Authorization": divar_authorization_header(str(self.apikey)),
        }

        last_item_identifier = ''
        matched_tokens = []

        while True:
            json_data = {
                'brand_token': brand_token,
                'specification': {
                    'query': '',
                    'last_item_identifier': last_item_identifier,
                },
            }

            response = self._post_divar_post_list(brand_token, json_data, headers)

            if response is None or response.status_code != 200:
                code = getattr(response, "status_code", None)
                print(f"[fetch_tokens_by_keywords] HTTP {code} برای brand_token {brand_token}")
                break

            data = response.json()
            widgets = data.get('page', {}).get('widget_list', [])

            for widget in widgets:
                if widget.get('widget_type') != 'POST_ROW':
                    continue
                token = widget.get('uid')
                label = (widget.get('data', {}) or {}).get('label', '') or ''

                label_str = str(label)
                normalized_label = label_str.replace('‌', '').replace('ٔ', '').replace(' ', '')
                normalized_lower = normalized_label.lower()

                if any(keyword in normalized_lower for keyword in keywords):
                    matched_tokens.append({
                        'token': token,
                        'label': label_str,
                        'title': widget.get('data', {}).get('title', '')
                    })

            infinite_scroll_response = data.get('page', {}).get('infinite_scroll_response', {})
            has_next = infinite_scroll_response.get('last_item_identifier')
            if not has_next:
                break

            last_item_identifier = has_next
            self._between_list_pages()

        return matched_tokens

    def get_all_tokens(self, brand_token):
        headers = {
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13; SM-S918B Build/TP1A.220624.014)",
            "X-Device-Model": "SM-S918B",
            "X-OS-Version": "13",
            "X-Platform": "android",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Authorization": divar_authorization_header(str(self.apikey)),
        }

        last_item_identifier = ''
        all_tokens = []
        while True:
            json_data = {
                'brand_token': brand_token,
                'specification': {
                    'query': '',
                    'last_item_identifier': last_item_identifier,
                },
            }

            response = self._post_divar_post_list(brand_token, json_data, headers)

            if response is not None and response.status_code == 200:
                data = response.json()
                widgets = data.get('page', {}).get('widget_list', [])
                # استخراج توکن‌ها از widget_list
                for widget in widgets:
                    if widget.get('widget_type') == 'POST_ROW' and widget.get('data', {}).get('label') == "منتشر شده":
                        token = widget['uid']
                        if token:
                            all_tokens.append(token)

                infinite_scroll_response = data.get('page', {}).get('infinite_scroll_response', {})
                has_next = infinite_scroll_response.get('last_item_identifier')
                if not has_next:
                    break  # اگر has_next False باشد، از حلقه خارج می‌شود

                last_item_identifier = has_next  # به‌روزرسانی برای درخواست بعدی
                self._between_list_pages()
            else:
                code = getattr(response, "status_code", "?")
                print(f"Error: {code}")
                break

        return all_tokens

    def get_tokens_needing_renewal(self, brand_token=None):
        """
        آگهی‌هایی که به زودی نیاز به تمدید دارند (قبل از منقضی شدن).
        """
        keywords = ['تمدید', 'نیازبهتمدید', 'نیاز به تمدید', 'انقضا', 'expire', 'renew']
        normalized_keywords = [kw.replace('‌', '').replace(' ', '').lower() for kw in keywords]
        return self._fetch_tokens_by_keywords(normalized_keywords, brand_token=brand_token)

    def get_expired_tokens(self, brand_token=None):
        """
        آگهی‌هایی که وضعیت‌شان منقضی شده است.
        """
        keywords = ['منقضی', 'expired']
        normalized_keywords = [kw.replace('‌', '').replace(' ', '').lower() for kw in keywords]
        return self._fetch_tokens_by_keywords(normalized_keywords, brand_token=brand_token)

    def getBranToken(self):
        try:
            response = None
            for attempt in range(2):
                response = self._http.get(
                    "https://api.divar.ir/v8/premium-user/web/get-business-list-web",
                    headers=self.headers,
                    cookies=self.cookies,
                    timeout=28,
                )
                if response.status_code == 429 and attempt == 0:
                    time.sleep(1.5 + random.uniform(0.3, 0.9))
                    continue
                break
            if response is None or response.status_code != 200:
                code = getattr(response, "status_code", "?")
                print(f"getBranToken HTTP {code}")
                return None
            bToken = response.json()['business_data_list'][0]['brand_token']
        except Exception as e:
            print(e)
            return None
        else:
            return bToken

    def _humanize_payment_error(self, stage, error_text):
        txt = str(error_text or "").strip().lower()
        stage_fa = {
            "selectPlan": "انتخاب پلن", "createOrderID": "ساخت سفارش",
            "createFlow": "آماده سازی فرآیند پرداخت", "createCheckOut": "دریافت اطلاعات پرداخت",
            "pay": "ثبت پرداخت", "promote": "اعمال نردبان",
        }.get(stage, "پرداخت")
        divar_session = (
            f"🔐 مرحلهٔ «{stage_fa}»: نشست دیوار برای این لاگین به پرداخت دسترسی ندارد یا منقضی شده. "
            "یک بار از منوی ربات همان شماره را با OTP دوباره وارد کنید؛ در اپ دیوار هم بازارپی را برای همین خط فعال کنید. "
            "اگر تازه کوکی را به‌روز کرده‌اید، ربات را یک بار ری‌استارت کنید و دوباره نردبان را امتحان کنید."
        )

        def _in(*parts):
            return any(p in txt for p in parts)

        simple = (
            (("invalid iranian mobile format for bazaarpay", "invalid mobile for bazaarpay"),
             "📱 شمارهٔ همین لاگین برای بازارپی درست نیست (باید موبایل ایران مثل ۹۱۲… باشد، بدون ۹۸ در ابتدا). "
             "لاگین را با همان شمارهٔ واقعی حساب دیوار اصلاح کنید."),
            (("timeout",), f"⏳ {stage_fa} به دلیل کندی ارتباط با دیوار کامل نشد. چند لحظه بعد دوباره تلاش می کنم."),
            (("no available plans", "no costs/plans available"), "⚠️ در حال حاضر برای این آگهی پلن قابل پرداختی از سمت دیوار موجود نیست."),
            (("costs not found", "invalid costs response"), "⚠️ اطلاعات پلن های پرداخت این آگهی از دیوار ناقص دریافت شد. کمی بعد دوباره تلاش کنید."),
            (("429", "rate limit", "too many requests"), "🚦 درخواست های پرداخت موقتا محدود شده است. کمی صبر کنید تا مجدد تلاش شود."),
            (("502", "503", "504"), "⏳ سرور دیوار یا درگاه موقتاً در دسترس نیست؛ کمی بعد دوباره امتحان کنید."),
        )
        for keys, msg in simple:
            if _in(*keys):
                return msg

        if txt.startswith("bazaarpay ") or _in("bazaarpay http", "checkout still unpaid"):
            bazaar = (
                (("checkout still unpaid",),
                 "💳 درخواست پرداخت به بازارپی رسید ولی وضعیت نهایی «پرداخت‌شده» نشد. "
                 "کیف پول دیوار/بازارپی را برای همین شماره شارژ کنید یا «پرداخت سریع» را در اپ فعال کنید و دوباره تلاش کنید."),
                (("پرداخت سریع", "سرویس پرداخت سریع", "فعال نکرده"),
                 "💳 «پرداخت سریع بازارپی» برای این شماره فعال نیست. "
                 "اپ دیوار → کیف پول/پرداخت → «پرداخت مستقیم/سریع بازارپی» را فعال کنید؛ "
                 "یا کیف را شارژ کنید تا پرداخت از موجودی انجام شود."),
                (("هیچ درگاه", "درگاه مناسب", "no suitable", "no gateway"),
                 "💳 پرداخت خودکار بازارپی برای این حساب فعال نیست. "
                 "در اپ دیوار → کیف پول/پرداخت → «پرداخت مستقیم بازارپی» را برای همین شماره فعال کنید "
                 "و موجودی کافی بگذارید؛ سپس یک بار OTP لاگین را در ربات تازه کنید و دوباره نردبان را بزنید."),
                (("401", "403", "unauthorized", "forbidden", "invalid token", "expired", "authentication"),
                 "🔐 بازارپی این پرداخت را رد کرد (احراز، توکن خرید یا هم‌خوانی شماره با دیوار). "
                 "اپ دیوار را باز کنید، بازارپی را برای همین شماره تکمیل کنید؛ در صورت نیاز یک بار دیگر OTP لاگین را در ربات بزنید."),
                (("412", "موجودی حساب کافی نیست", "balance", "insufficient", "not enough", "موجودی", "enough_balance"),
                 "💳 موجودی کیف پول بازارپی/دیوار برای این مبلغ کافی نیست. کیف را شارژ کنید و دوباره نردبان را بزنید."),
            )
            for keys, msg in bazaar:
                if _in(*keys):
                    return msg
            return "⚠️ مرحلهٔ پرداخت بازارپی کامل نشد. اگر پیام تکرار شد، متن خطای فنی را از لاگ سرور بخوانید یا بعداً دوباره امتحان کنید."

        if re.search(r"\bhttp\s+401\b", txt) or re.search(r"\bhttp\s+403\b", txt):
            return divar_session
        if _in("unauthorized", "forbidden") and "bazaar" not in txt:
            return divar_session

        short = str(error_text or "").strip() or "خطای نامشخص"
        return f"⚠️ {stage_fa} کامل نشد: {short[:180]}{'...' if len(short) > 180 else ''}"

    def _payment_step_failed(self, chatid, token, stage, error):
        """ثبت خطای مرحله پرداخت + برگرداندن خروجی یکدست برای bot.py"""
        error_msg = str(error).strip() if error is not None else ""
        if not error_msg:
            error_msg = "Unknown error"
        print(f"{stage} error for token {token}: {error_msg}")
        # عنصر چهارم = مرحلهٔ خطا؛ برای جلوگیری از تکرار پرداخت در retry استفاده می‌شود
        return [0, token, self._humanize_payment_error(stage, error_msg), stage]

    def _try_nardeban_tokens(self, chatid, number, tokens, priority_1=None, priority_2=None):
        if not tokens:
            return [2, "هیچ اگهی برای نردبان پیدا نشد."]

        last_fail = None
        skipped = 0
        seen: set[str] = set()

        for candidate in tokens:
            cand = str(candidate or "").strip()
            if not cand or cand in seen:
                continue
            seen.add(cand)

            plan_cost = None
            plan_err = None
            for plan_attempt in range(2):
                try:
                    plan_cost = int(
                        self.selectPlan(
                            token=cand,
                            priority_1=priority_1,
                            priority_2=priority_2,
                        )
                    )
                    plan_err = None
                    break
                except Exception as e:
                    plan_err = e
                    if plan_attempt == 0 and self._is_transient_error(e):
                        print(
                            f"[nardeban] selectPlan موقت برای {cand}، یک بار دیگر: {e}"
                        )
                        time.sleep(1.0 + random.uniform(0.15, 0.65))
                        continue
                    break
            if plan_cost is None:
                err_human = self._humanize_payment_error("selectPlan", plan_err)
                if self._error_kind(plan_err, err_human) == "login":
                    print(f"[nardeban] توقف لاگین {number} (selectPlan): {err_human[:120]}")
                    return [3, number, err_human]
                self._mark_token_failed(
                    chatid,
                    number,
                    cand,
                    reason=str(plan_err).strip() or "selectPlan",
                )
                skipped += 1
                last_fail = [0, cand, err_human]
                continue

            result = self._run_nardeban_pipeline(chatid, number, cand, plan_cost)
            if result[0] != 1:
                err_text = str(result[2] if len(result) > 2 else "")
                failed_stage = result[3] if len(result) > 3 else None
                # [audit] فقط اگر خطا قبل از مرحلهٔ pay بود دوباره امتحان کن؛
                # تکرار کل pipeline بعد از pay/promote یعنی سفارش و پرداخت دوم (ریسک دوبار کسر پول).
                if self._is_transient_error(err_text) and failed_stage in ("createOrderID", "createCheckOut"):
                    print(
                        f"[nardeban] خطای موقت برای {cand}، یک بار دیگر: {err_text[:120]}"
                    )
                    time.sleep(1.2 + random.uniform(0.2, 0.8))
                    result = self._run_nardeban_pipeline(
                        chatid, number, cand, plan_cost
                    )
                    err_text = str(result[2] if len(result) > 2 else "")
            if result[0] == 1:
                if skipped:
                    print(
                        f"[nardeban] پس از رد {skipped} آگهی، نردبان موفق: {cand}"
                    )
                return result

            err_text = str(result[2] if len(result) > 2 else result)
            if self._error_kind(err_text, err_text) == "login":
                print(f"[nardeban] توقف لاگین {number}: {err_text[:120]}")
                return [3, number, err_text]

            self._mark_token_failed(
                chatid,
                number,
                cand,
                reason=str(result[2] if len(result) > 2 else result),
            )
            skipped += 1
            last_fail = result

        if last_fail is not None:
            if skipped > 1:
                tail = str(last_fail[2] if len(last_fail) > 2 else "")
                last_fail = [
                    0,
                    last_fail[1],
                    f"{skipped} آگهی رد شد؛ آخرین خطا: {tail}",
                ]
            return last_fail
        return [2, "هیچ اگهی قابل نردبان برای این شماره یافت نشد."]

    def sendNardeban(self, number, chatid, priority_1=None, priority_2=None):
        from .tokens_manager import get_tokens_from_json

        tokens = get_tokens_from_json(chatid=chatid, phone=int(number), status="pending")
        return self._try_nardeban_tokens(
            chatid, number, tokens, priority_1=priority_1, priority_2=priority_2
        )

    def sendNardebanWithToken(
        self,
        number,
        chatid,
        token,
        require_pending=True,
        priority_1=None,
        priority_2=None,
    ):
        """نردبان؛ توکن درخواستی اول امتحان می‌شود، خطا → بلافاصله pending بعدی."""
        if require_pending:
            pending_tokens = self.curd.get_pending_tokens_by_phone(phone=number, chatid=chatid)
            if token not in pending_tokens:
                return [0, token, "این توکن قبلاً نردبان شده است"]

        from .tokens_manager import get_tokens_from_json

        pending = get_tokens_from_json(chatid=chatid, phone=int(number), status="pending")
        tok = str(token or "").strip()
        ordered = []
        if tok and tok in pending:
            ordered.append(tok)
        for t in pending:
            if t not in ordered:
                ordered.append(t)
        return self._try_nardeban_tokens(
            chatid, number, ordered, priority_1=priority_1, priority_2=priority_2
        )

