/**
 * فرم‌های آنبوردینگ بازاریاب روی /api/consultant/*
 * شهرها فقط از GET /api/consultant/cities با شکل { ok, cities: [{ id, label }] }.
 */
(function () {
  "use strict";

  var root = document.getElementById("vnConsultant");
  if (!root) return;

  var citiesUrl = root.getAttribute("data-cities-url") || "";
  var profileUrl = root.getAttribute("data-profile-url") || "";
  var applyUrl = root.getAttribute("data-apply-url") || "";
  var documentsUrl = root.getAttribute("data-documents-url") || "";
  var loginUrl = root.getAttribute("data-login-url") || "";
  var mode = root.getAttribute("data-mode") || "";
  var steps = {
    apply: root.getAttribute("data-step-apply") || "",
    profile: root.getAttribute("data-step-profile") || "",
    documents: root.getAttribute("data-step-documents") || "",
    status: root.getAttribute("data-step-status") || "",
    dashboard: root.getAttribute("data-step-dashboard") || "",
  };

  function go(step) {
    var url = steps[step] || steps.status || steps.apply;
    if (!url) return;
    if (typeof window.vinorExpressNavigate === "function") {
      window.vinorExpressNavigate(url);
    } else {
      window.location.assign(url);
    }
  }

  function box() {
    return document.getElementById("vnConsultError");
  }

  function clearFieldErrors() {
    var nodes = root.querySelectorAll("[data-field-error]");
    for (var i = 0; i < nodes.length; i++) nodes[i].textContent = "";
  }

  function showError(message, fields) {
    clearFieldErrors();
    var el = box();
    if (el) {
      el.textContent = message || "اطلاعات واردشده معتبر نیست.";
      el.hidden = false;
    }
    if (!fields) return;
    Object.keys(fields).forEach(function (key) {
      var slot = root.querySelector('[data-field-error="' + key + '"]');
      if (slot) slot.textContent = String(fields[key] || "");
    });
  }

  function hideError() {
    clearFieldErrors();
    var el = box();
    if (!el) return;
    el.hidden = true;
    el.textContent = "";
  }

  async function callApi(url, options) {
    var res = await fetch(url, options);
    var data = {};
    try {
      data = await res.json();
    } catch (err) {
      data = { ok: false, message: "پاسخ سرور نامعتبر بود." };
    }
    if (res.status === 401 && loginUrl) {
      window.location.assign(loginUrl);
      return null;
    }
    return { status: res.status, data: data };
  }

  function isCityRow(row) {
    return !!(row && typeof row.id === "string" && row.id && typeof row.label === "string" && row.label);
  }

  async function loadCities() {
    var select = document.getElementById("vnConsultCity");
    var hint = document.getElementById("vnConsultCityHint");
    var retry = document.getElementById("vnConsultCityRetry");
    if (!select || !citiesUrl) return;
    select.disabled = true;
    if (hint) hint.textContent = "در حال دریافت شهرها…";
    if (retry) retry.hidden = true;
    var result;
    try {
      result = await callApi(citiesUrl, {
        method: "GET",
        credentials: "include",
        headers: { Accept: "application/json" },
      });
    } catch (err) {
      result = { data: { ok: false, message: "فهرست شهرها بارگذاری نشد." } };
    }
    if (!result) return;
    var payload = result.data || {};
    if (payload.ok !== true || !Array.isArray(payload.cities)) {
      if (hint) hint.textContent = payload.message || "فهرست شهرها بارگذاری نشد.";
      if (retry) retry.hidden = false;
      return;
    }
    var selected = root.getAttribute("data-selected-city") || "";
    select.replaceChildren();
    var placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "انتخاب شهر";
    select.appendChild(placeholder);
    var count = 0;
    payload.cities.forEach(function (row) {
      if (!isCityRow(row)) return;
      count += 1;
      var opt = document.createElement("option");
      opt.value = row.id;
      opt.textContent = row.label;
      if (row.id === selected) opt.selected = true;
      select.appendChild(opt);
    });
    select.disabled = false;
    if (!count) {
      if (hint) hint.textContent = "شهری برای انتخاب نیست.";
      if (retry) retry.hidden = false;
      return;
    }
    if (hint) hint.textContent = "";
  }

  function selectedSpecialties() {
    var found = [];
    var boxes = root.querySelectorAll('input[name="specialty"]:checked:not(:disabled)');
    for (var i = 0; i < boxes.length; i++) {
      var value = boxes[i].value;
      if ((value === "buy" || value === "sell") && found.indexOf(value) < 0) found.push(value);
    }
    return found;
  }

  async function submitApply(event) {
    event.preventDefault();
    hideError();
    var btn = document.getElementById("vnConsultSubmit");
    if (btn) btn.disabled = true;
    try {
      var result = await callApi(applyUrl, {
        method: "POST",
        credentials: "include",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: "{}",
      });
      if (!result) return;
      if (!result.data || result.data.ok !== true) {
        showError((result.data && result.data.message) || "ثبت درخواست انجام نشد.");
        if (btn) btn.disabled = false;
        return;
      }
      go(result.data.next_step || "profile");
    } catch (err) {
      showError("ارتباط برقرار نشد. دوباره تلاش کنید.");
      if (btn) btn.disabled = false;
    }
  }

  async function submitProfile(event) {
    event.preventDefault();
    hideError();
    var nameInput = document.getElementById("vnConsultName");
    var citySelect = document.getElementById("vnConsultCity");
    var name = String((nameInput && nameInput.value) || "").replace(/\s+/g, " ").trim();
    var city = String((citySelect && citySelect.value) || "").trim();
    var specialties = selectedSpecialties();
    if (name.length < 2 || name.length > 40) {
      showError("نام باید بین ۲ تا ۴۰ نویسه باشد.", { name: "نام باید بین ۲ تا ۴۰ نویسه باشد." });
      return;
    }
    if (!city) {
      showError("شهر را از فهرست انتخاب کنید.", { city: "شهر را از فهرست انتخاب کنید." });
      return;
    }
    if (!specialties.length) {
      showError("حداقل یک تخصص (خرید یا فروش) را انتخاب کنید.", {
        specialties: "حداقل یک تخصص (خرید یا فروش) را انتخاب کنید.",
      });
      return;
    }
    var btn = document.getElementById("vnConsultSubmit");
    if (btn) btn.disabled = true;
    try {
      var result = await callApi(profileUrl, {
        method: "PATCH",
        credentials: "include",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ name: name, city: city, specialties: specialties }),
      });
      if (!result) return;
      if (!result.data || result.data.ok !== true) {
        showError((result.data && result.data.message) || "ذخیره پروفایل انجام نشد.", result.data && result.data.fields);
        if (btn) btn.disabled = false;
        return;
      }
      go(result.data.next_step || "documents");
    } catch (err) {
      showError("ارتباط برقرار نشد. دوباره تلاش کنید.");
      if (btn) btn.disabled = false;
    }
  }

  function fileTooBig(file) {
    return !!(file && file.size > 5 * 1024 * 1024);
  }

  async function submitDocuments(event) {
    event.preventDefault();
    hideError();
    var national = document.getElementById("vnConsultNationalId");
    var license = document.getElementById("vnConsultLicense");
    var nationalFile = national && national.files && national.files[0];
    var licenseFile = license && license.files && license.files[0];
    if (!nationalFile) {
      showError("بارگذاری تصویر کارت ملی الزامی است.", { national_id: "بارگذاری تصویر کارت ملی الزامی است." });
      return;
    }
    if (fileTooBig(nationalFile) || fileTooBig(licenseFile)) {
      showError("حجم هر فایل حداکثر ۵ مگابایت است.", { national_id: "حجم هر فایل حداکثر ۵ مگابایت است." });
      return;
    }
    var body = new FormData();
    body.append("national_id", nationalFile);
    if (licenseFile) body.append("license", licenseFile);
    var btn = document.getElementById("vnConsultSubmit");
    if (btn) btn.disabled = true;
    try {
      var result = await callApi(documentsUrl, {
        method: "POST",
        credentials: "include",
        headers: { Accept: "application/json" },
        body: body,
      });
      if (!result) return;
      if (!result.data || result.data.ok !== true) {
        showError((result.data && result.data.message) || "بارگذاری مدرک انجام نشد.", result.data && result.data.fields);
        if (btn) btn.disabled = false;
        return;
      }
      go(result.data.next_step || "status");
    } catch (err) {
      showError("ارتباط برقرار نشد. دوباره تلاش کنید.");
      if (btn) btn.disabled = false;
    }
  }

  var form = document.getElementById("vnConsultForm");
  if (mode === "apply" && form) form.addEventListener("submit", submitApply);
  if (mode === "profile") {
    loadCities();
    var retry = document.getElementById("vnConsultCityRetry");
    if (retry) retry.addEventListener("click", loadCities);
    if (form) form.addEventListener("submit", submitProfile);
  }
  if (mode === "documents" && form) form.addEventListener("submit", submitDocuments);
})();
