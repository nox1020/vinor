/**
 * Vinor Control — Internationalization (i18n) first.
 * LanguageProvider: t(), formatters, RTL/LTR, lazy locale load, no hard-coded UI copy.
 */
(function (global) {
  "use strict";

  var STORAGE_KEY = "vinor.control.lang";
  var CACHE = Object.create(null);
  var state = {
    lang: "en",
    dict: null,
    baseUrl: "/static/admin/locales",
    ready: false,
    listeners: [],
  };

  var FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
  var EN_DIGITS = "0123456789";

  function detectBrowserLang() {
    try {
      var nav = (navigator.languages && navigator.languages[0]) || navigator.language || "en";
      return String(nav).toLowerCase().indexOf("fa") === 0 ? "fa" : "en";
    } catch (e) {
      return "en";
    }
  }

  function readStoredLang() {
    try {
      var v = localStorage.getItem(STORAGE_KEY);
      if (v === "fa" || v === "en") return v;
    } catch (e) {}
    return null;
  }

  function resolveLang(preferred) {
    if (preferred === "fa" || preferred === "en") return preferred;
    return readStoredLang() || detectBrowserLang();
  }

  function getByPath(obj, path) {
    if (!obj || !path) return undefined;
    var parts = String(path).split(".");
    var cur = obj;
    for (var i = 0; i < parts.length; i++) {
      if (cur == null || typeof cur !== "object") return undefined;
      cur = cur[parts[i]];
    }
    return cur;
  }

  function interpolate(str, params) {
    if (!params) return str;
    return String(str).replace(/\{\{(\w+)\}\}/g, function (_, k) {
      return params[k] != null ? String(params[k]) : "";
    });
  }

  function toFaDigits(s) {
    return String(s).replace(/[0-9]/g, function (d) {
      return FA_DIGITS[+d];
    });
  }

  function toEnDigits(s) {
    return String(s).replace(/[۰-۹]/g, function (d) {
      return EN_DIGITS[FA_DIGITS.indexOf(d)] || d;
    });
  }

  function t(key, params) {
    var val = getByPath(state.dict, key);
    if (val == null || typeof val === "object") {
      return typeof key === "string" ? key : "";
    }
    return interpolate(String(val), params);
  }

  function formatNumber(value, opts) {
    opts = opts || {};
    var n = Number(value);
    if (!isFinite(n)) return "—";
    var locale = state.lang === "fa" ? "fa-IR" : "en-US";
    var formatted = new Intl.NumberFormat(locale, {
      maximumFractionDigits: opts.maximumFractionDigits != null ? opts.maximumFractionDigits : 2,
      minimumFractionDigits: opts.minimumFractionDigits || 0,
    }).format(n);
    return state.lang === "fa" ? toFaDigits(formatted) : formatted;
  }

  function formatPercent(value, opts) {
    opts = opts || {};
    var n = Number(value);
    if (!isFinite(n)) return "—";
    // accept 0–1 or 0–100
    var ratio = Math.abs(n) <= 1 && !opts.alreadyPercent ? n : n / 100;
    var locale = state.lang === "fa" ? "fa-IR" : "en-US";
    var formatted = new Intl.NumberFormat(locale, {
      style: "percent",
      maximumFractionDigits: opts.maximumFractionDigits != null ? opts.maximumFractionDigits : 0,
    }).format(ratio);
    return state.lang === "fa" ? toFaDigits(formatted) : formatted;
  }

  function formatCurrency(value, opts) {
    opts = opts || {};
    var n = Number(value);
    if (!isFinite(n)) return "—";
    var unit = opts.unit || opts.currencyMode || "auto";
    // AI / USD amounts: always USD-style presentation
    if (unit === "usd" || unit === "USD") {
      var usd = new Intl.NumberFormat(state.lang === "fa" ? "en-US" : "en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: opts.maximumFractionDigits != null ? opts.maximumFractionDigits : 4,
      }).format(n);
      return state.lang === "fa" ? toFaDigits(usd) : usd;
    }
    if (state.lang === "fa" || unit === "toman") {
      var tomans = formatNumber(Math.round(n), { maximumFractionDigits: 0 });
      return tomans + " " + t("currency.toman");
    }
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: opts.currency || "USD",
      maximumFractionDigits: opts.maximumFractionDigits != null ? opts.maximumFractionDigits : 2,
    }).format(n);
  }

  function formatPhone(value) {
    var raw = toEnDigits(String(value || "")).replace(/[^\d+]/g, "");
    if (!raw) return "—";
    if (state.lang === "fa") return toFaDigits(raw);
    return raw;
  }

  function formatDate(value, opts) {
    opts = opts || {};
    if (value == null || value === "") return "—";
    var d = value instanceof Date ? value : new Date(value);
    if (isNaN(d.getTime())) {
      // try "YYYY-MM-DD HH:mm" as UTC-ish
      var s = String(value).replace(" ", "T");
      if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(s) && !/[zZ]|[+-]\d{2}/.test(s)) s += "Z";
      d = new Date(s);
      if (isNaN(d.getTime())) return String(value);
    }
    var options = opts.dateStyle
      ? { dateStyle: opts.dateStyle, timeStyle: opts.timeStyle }
      : {
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: opts.time === false ? undefined : "2-digit",
          minute: opts.time === false ? undefined : "2-digit",
        };
    if (opts.timeZone) options.timeZone = opts.timeZone;
    else options.timeZone = "Asia/Tehran";

    if (state.lang === "fa") {
      try {
        var fa = new Intl.DateTimeFormat("fa-IR-u-ca-persian", options).format(d);
        return toFaDigits(fa);
      } catch (e) {
        return toFaDigits(new Intl.DateTimeFormat("fa-IR", options).format(d));
      }
    }
    return new Intl.DateTimeFormat("en-US", options).format(d);
  }

  function applyDocumentChrome() {
    var html = document.documentElement;
    html.setAttribute("lang", state.lang);
    html.setAttribute("dir", state.lang === "fa" ? "rtl" : "ltr");
    html.classList.toggle("lang-fa", state.lang === "fa");
    html.classList.toggle("lang-en", state.lang === "en");
    try {
      document.body && document.body.setAttribute("dir", state.lang === "fa" ? "rtl" : "ltr");
    } catch (e) {}
  }

  function applyNode(el) {
    if (!el || !el.getAttribute) return;
    var key = el.getAttribute("data-i18n");
    if (key) {
      var params = null;
      var rawParams = el.getAttribute("data-i18n-params");
      if (rawParams) {
        try {
          params = JSON.parse(rawParams);
        } catch (e) {
          params = null;
        }
      }
      var text = t(key, params);
      if (el.getAttribute("data-i18n-html") === "1") el.innerHTML = text;
      else el.textContent = text;
    }
    var attrMap = el.getAttribute("data-i18n-attr");
    if (attrMap) {
      // format: title:common.settings,aria-label:common.menu_open
      attrMap.split(",").forEach(function (pair) {
        var parts = pair.split(":");
        if (parts.length < 2) return;
        var attr = parts[0].trim();
        var k = parts.slice(1).join(":").trim();
        if (attr && k) el.setAttribute(attr, t(k));
      });
    }
    var ph = el.getAttribute("data-i18n-placeholder");
    if (ph) el.setAttribute("placeholder", t(ph));
    var titleKey = el.getAttribute("data-i18n-title");
    if (titleKey) el.setAttribute("title", t(titleKey));
    var ariaKey = el.getAttribute("data-i18n-aria");
    if (ariaKey) el.setAttribute("aria-label", t(ariaKey));

    if (el.hasAttribute("data-i18n-number")) {
      var num = el.getAttribute("data-i18n-number");
      el.textContent = formatNumber(num, {
        maximumFractionDigits: +(el.getAttribute("data-i18n-digits") || 0),
      });
    }
    if (el.hasAttribute("data-i18n-percent")) {
      el.textContent = formatPercent(el.getAttribute("data-i18n-percent"), {
        alreadyPercent: el.getAttribute("data-i18n-percent-mode") === "100",
      });
    }
    if (el.hasAttribute("data-i18n-currency")) {
      el.textContent = formatCurrency(el.getAttribute("data-i18n-currency"), {
        unit: el.getAttribute("data-i18n-currency-unit") || "auto",
        maximumFractionDigits: +(el.getAttribute("data-i18n-digits") || 2),
      });
    }
    if (el.hasAttribute("data-i18n-date")) {
      el.textContent = formatDate(el.getAttribute("data-i18n-date"));
    }
    if (el.hasAttribute("data-i18n-phone")) {
      el.textContent = formatPhone(el.getAttribute("data-i18n-phone"));
    }
  }

  function applyDom(root) {
    var scope = root || document;
    var nodes = scope.querySelectorAll(
      "[data-i18n],[data-i18n-attr],[data-i18n-placeholder],[data-i18n-title],[data-i18n-aria],[data-i18n-number],[data-i18n-percent],[data-i18n-currency],[data-i18n-date],[data-i18n-phone]"
    );
    for (var i = 0; i < nodes.length; i++) applyNode(nodes[i]);

    // document title via data-i18n-page-title on <html> or meta
    var pageTitleKey =
      (document.documentElement && document.documentElement.getAttribute("data-i18n-page-title")) ||
      (document.querySelector("meta[name='vinor-page-title-key']") &&
        document.querySelector("meta[name='vinor-page-title-key']").getAttribute("content"));
    if (pageTitleKey) {
      var suffix = t("meta.title_suffix");
      var title = t(pageTitleKey);
      document.title = title.indexOf(suffix) >= 0 ? title : title + " | " + suffix;
    }

    var metaDesc = document.querySelector("meta[name='description']");
    if (metaDesc && metaDesc.getAttribute("data-i18n")) {
      metaDesc.setAttribute("content", t(metaDesc.getAttribute("data-i18n")));
    }
  }

  function notify() {
    for (var i = 0; i < state.listeners.length; i++) {
      try {
        state.listeners[i](state.lang);
      } catch (e) {}
    }
    try {
      document.dispatchEvent(
        new CustomEvent("vinor:langchange", { detail: { lang: state.lang } })
      );
    } catch (e) {}
  }

  function loadLocale(lang) {
    if (CACHE[lang]) return Promise.resolve(CACHE[lang]);
    var url = state.baseUrl.replace(/\/$/, "") + "/" + lang + ".json";
    return fetch(url, { credentials: "same-origin", cache: "force-cache" })
      .then(function (r) {
        if (!r.ok) throw new Error("locale " + lang);
        return r.json();
      })
      .then(function (json) {
        CACHE[lang] = json;
        return json;
      });
  }

  function setLanguage(lang, opts) {
    opts = opts || {};
    lang = resolveLang(lang);
    return loadLocale(lang).then(function (dict) {
      state.lang = lang;
      state.dict = dict;
      state.ready = true;
      try {
        localStorage.setItem(STORAGE_KEY, lang);
      } catch (e) {}
      applyDocumentChrome();
      if (!opts.skipDom) applyDom(document);
      notify();
      return lang;
    });
  }

  function toggleLanguage() {
    return setLanguage(state.lang === "fa" ? "en" : "fa");
  }

  function onChange(fn) {
    if (typeof fn === "function") state.listeners.push(fn);
    return function () {
      state.listeners = state.listeners.filter(function (x) {
        return x !== fn;
      });
    };
  }

  /** Bilingual command search: match label + aliases from both locales (cached). */
  function searchMatch(query, item) {
    var q = String(query || "")
      .trim()
      .toLowerCase();
    if (!q) return true;
    var hay = [];
    if (item.label) hay.push(String(item.label).toLowerCase());
    if (item.labelKey) {
      hay.push(t(item.labelKey).toLowerCase());
      // also search the other language if cached
      var other = state.lang === "fa" ? "en" : "fa";
      if (CACHE[other]) {
        var ov = getByPath(CACHE[other], item.labelKey);
        if (ov) hay.push(String(ov).toLowerCase());
      }
    }
    if (item.aliases) {
      for (var i = 0; i < item.aliases.length; i++) hay.push(String(item.aliases[i]).toLowerCase());
    }
    if (item.aliasKey) {
      var aliases = getByPath(state.dict, item.aliasKey);
      if (Array.isArray(aliases)) {
        aliases.forEach(function (a) {
          hay.push(String(a).toLowerCase());
        });
      }
      var otherLang = state.lang === "fa" ? "en" : "fa";
      if (CACHE[otherLang]) {
        var oa = getByPath(CACHE[otherLang], item.aliasKey);
        if (Array.isArray(oa)) {
          oa.forEach(function (a) {
            hay.push(String(a).toLowerCase());
          });
        }
      }
    }
    return hay.some(function (h) {
      return h && h.indexOf(q) !== -1;
    });
  }

  function prefetchOther() {
    var other = state.lang === "fa" ? "en" : "fa";
    loadLocale(other).catch(function () {});
  }

  function init(options) {
    options = options || {};
    if (options.baseUrl) state.baseUrl = options.baseUrl;
    var lang = resolveLang(options.lang);
    // prevent FOUC: set dir ASAP
    state.lang = lang;
    applyDocumentChrome();
    return setLanguage(lang).then(function () {
      prefetchOther();
      return state.lang;
    });
  }

  // early paint helper (inline-safe API)
  function bootSyncDir() {
    var lang = resolveLang();
    state.lang = lang;
    applyDocumentChrome();
    return lang;
  }

  var api = {
    init: init,
    bootSyncDir: bootSyncDir,
    setLanguage: setLanguage,
    toggleLanguage: toggleLanguage,
    getLanguage: function () {
      return state.lang;
    },
    isReady: function () {
      return state.ready;
    },
    t: t,
    applyDom: applyDom,
    applyNode: applyNode,
    onChange: onChange,
    formatNumber: formatNumber,
    formatPercent: formatPercent,
    formatCurrency: formatCurrency,
    formatPhone: formatPhone,
    formatDate: formatDate,
    searchMatch: searchMatch,
    toFaDigits: toFaDigits,
    toEnDigits: toEnDigits,
    STORAGE_KEY: STORAGE_KEY,
  };

  global.VinorI18n = api;
  global.t = function (key, params) {
    return api.t(key, params);
  };
  global.formatNumber = function (v, o) {
    return api.formatNumber(v, o);
  };
  global.formatPercent = function (v, o) {
    return api.formatPercent(v, o);
  };
  global.formatCurrency = function (v, o) {
    return api.formatCurrency(v, o);
  };
  global.formatPhone = function (v, o) {
    return api.formatPhone(v, o);
  };
  global.formatDate = function (v, o) {
    return api.formatDate(v, o);
  };
})(typeof window !== "undefined" ? window : globalThis);
