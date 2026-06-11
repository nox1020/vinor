(function () {
  'use strict';

  const form = document.getElementById('expressEditForm');
  if (!form) return;

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  let selectedImages = [];
  let mapReady = false;
  let locationMap = null;
  let locationMarker = null;
  let isSubmitting = false;

  function parseDigits(str) {
    if (!str) return 0;
    let s = String(str);
    const fa = '۰۱۲۳۴۵۶۷۸۹';
    for (let i = 0; i < fa.length; i++) s = s.split(fa[i]).join(String(i));
    s = s.replace(/[^\d]/g, '');
    return parseInt(s, 10) || 0;
  }

  function fmt(n) {
    return n > 0 ? n.toLocaleString('fa-IR') : '';
  }

  function rawFrom(el) {
    if (!el) return 0;
    const v = el.dataset.rawValue || el.value || '';
    return parseDigits(v);
  }

  function recalcPpm() {
    const size = rawFrom($('input[name="size"]', form));
    const price = rawFrom($('input[name="price_total"]', form));
    const ppm = size > 0 && price > 0 ? Math.round(price / size) : 0;
    const ppmEl = $('#price_per_meter', form);
    if (ppmEl) {
      ppmEl.dataset.rawValue = ppm > 0 ? String(ppm) : '';
      ppmEl.value = ppm > 0 ? fmt(ppm) : '';
    }
  }

  function hookIntInput(el) {
    el.addEventListener('input', () => {
      const digits = (el.value || '').replace(/[^\d۰-۹]/g, '');
      let cleaned = digits;
      const fa = '۰۱۲۳۴۵۶۷۸۹';
      for (let i = 0; i < fa.length; i++) cleaned = cleaned.split(fa[i]).join(String(i));
      cleaned = cleaned.replace(/[^\d]/g, '');
      el.dataset.rawValue = cleaned;
      el.value = digits;
      recalcPpm();
    });
    el.addEventListener('blur', () => {
      const n = parseDigits(el.value);
      el.dataset.rawValue = n ? String(n) : '';
      el.value = n ? fmt(n) : '';
      recalcPpm();
    });
  }

  $$('[data-format-int]', form).forEach(hookIntInput);

  const dropzone = $('#dropzone', form);
  const imagesInput = $('#imagesInput', form);
  const preview = $('#imagePreview', form);

  function syncImageInput() {
    if (!imagesInput || typeof DataTransfer === 'undefined') return;
    const dt = new DataTransfer();
    selectedImages.forEach((f) => dt.items.add(f));
    imagesInput.files = dt.files;
  }

  function renderNewPreviews() {
    if (!preview) return;
    preview.innerHTML = '';
    selectedImages.forEach((file, index) => {
      const url = URL.createObjectURL(file);
      const div = document.createElement('div');
      div.className = 'relative aspect-square rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700';
      div.innerHTML =
        '<img src="' + url + '" alt="" class="w-full h-full object-cover">' +
        '<button type="button" data-idx="' + index + '" class="img-rm absolute top-1 left-1 w-6 h-6 rounded-full bg-red-500 text-white text-xs">×</button>' +
        '<span class="absolute bottom-1 right-1 rounded bg-black/50 px-1 text-[10px] text-white">جدید</span>';
      preview.appendChild(div);
      div.querySelector('img').onload = () => URL.revokeObjectURL(url);
    });
  }

  function addImages(files) {
    selectedImages = selectedImages.concat(Array.from(files)).slice(0, 12);
    syncImageInput();
    renderNewPreviews();
  }

  dropzone?.addEventListener('click', () => imagesInput?.click());
  imagesInput?.addEventListener('change', (e) => {
    if (e.target.files?.length) addImages(e.target.files);
  });
  preview?.addEventListener('click', (e) => {
    const btn = e.target.closest('.img-rm');
    if (!btn) return;
    const idx = parseInt(btn.getAttribute('data-idx'), 10);
    selectedImages.splice(idx, 1);
    syncImageInput();
    renderNewPreviews();
  });

  const pm = $('#payment_method', form);
  const instBox = $('#installmentsBox', form);
  const instRows = $('#installmentsRows', form);
  const addInst = $('#addInstallmentRow', form);

  function instRowHtml(m, a) {
    return (
      '<div class="installment-row bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg p-3">' +
      '<div class="grid grid-cols-12 gap-2 items-end">' +
      '<div class="col-span-5"><label class="block text-xs text-gray-600 dark:text-gray-400 mb-1">تعداد ماه</label>' +
      '<input type="number" min="1" name="installment_months[]" value="' + (m || '') + '" class="w-full border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-2 bg-white dark:bg-gray-900 text-sm"></div>' +
      '<div class="col-span-6"><label class="block text-xs text-gray-600 dark:text-gray-400 mb-1">مبلغ (تومان)</label>' +
      '<input type="text" inputmode="numeric" name="installment_amounts[]" value="' + (a || '') + '" class="w-full border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-2 bg-white dark:bg-gray-900 text-sm"></div>' +
      '<div class="col-span-1 flex justify-end"><button type="button" class="remove-installment w-9 h-9 rounded-lg border border-gray-200 dark:border-gray-700 text-red-500"><i class="fa-solid fa-trash text-xs"></i></button></div>' +
      '</div></div>'
    );
  }

  function toggleInst() {
    const v = (pm?.value || '').trim();
    if (!instBox) return;
    if (v === 'اقساطی') {
      instBox.classList.remove('hidden');
      if (!instRows.querySelector('.installment-row')) instRows.insertAdjacentHTML('beforeend', instRowHtml('', ''));
    } else {
      instBox.classList.add('hidden');
    }
  }

  pm?.addEventListener('change', toggleInst);
  addInst?.addEventListener('click', () => instRows.insertAdjacentHTML('beforeend', instRowHtml('', '')));
  instRows?.addEventListener('click', (e) => {
    const btn = e.target.closest('.remove-installment');
    if (btn) btn.closest('.installment-row')?.remove();
  });
  toggleInst();

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      if (document.querySelector('script[src="' + src + '"]')) {
        resolve();
        return;
      }
      const s = document.createElement('script');
      s.src = src;
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  function loadCss(href) {
    if (document.querySelector('link[href="' + href + '"]')) return;
    const l = document.createElement('link');
    l.rel = 'stylesheet';
    l.href = href;
    document.head.appendChild(l);
  }

  async function ensureMap() {
    if (mapReady && locationMap) {
      locationMap.invalidateSize();
      return;
    }
    const css = form.dataset.leafletCss;
    const js = form.dataset.leafletJs;
    if (css) loadCss(css);
    if (js) await loadScript(js);
    initMap();
  }

  function updateCoords(lat, lon) {
    const latEl = $('#latitude', form);
    const lonEl = $('#longitude', form);
    if (latEl) latEl.value = lat.toFixed(6);
    if (lonEl) lonEl.value = lon.toFixed(6);
  }

  function initMap() {
    if (mapReady || !$('#locationMap') || typeof L === 'undefined') return;
    const latEl = $('#latitude', form);
    const lonEl = $('#longitude', form);
    let lat = parseFloat(latEl?.value) || 35.6892;
    let lon = parseFloat(lonEl?.value) || 51.389;
    locationMap = L.map('locationMap').setView([lat, lon], 13);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(locationMap);
    locationMarker = L.marker([lat, lon], { draggable: true }).addTo(locationMap);
    locationMap.on('click', (e) => {
      locationMarker.setLatLng(e.latlng);
      updateCoords(e.latlng.lat, e.latlng.lng);
    });
    locationMarker.on('dragend', (e) => {
      const p = e.target.getLatLng();
      updateCoords(p.lat, p.lng);
    });
    latEl?.addEventListener('change', () => {
      const la = parseFloat(latEl.value);
      const lo = parseFloat(lonEl?.value) || lon;
      if (!isNaN(la) && !isNaN(lo)) {
        locationMarker.setLatLng([la, lo]);
        locationMap.setView([la, lo], locationMap.getZoom());
      }
    });
    lonEl?.addEventListener('change', () => {
      const la = parseFloat(latEl?.value) || lat;
      const lo = parseFloat(lonEl.value);
      if (!isNaN(la) && !isNaN(lo)) {
        locationMarker.setLatLng([la, lo]);
        locationMap.setView([la, lo], locationMap.getZoom());
      }
    });
    mapReady = true;
    setTimeout(() => locationMap.invalidateSize(), 80);
  }

  $('#toggleMapBtn')?.addEventListener('click', async () => {
    const wrap = $('#mapWrap');
    if (wrap.classList.contains('hidden')) {
      wrap.classList.remove('hidden');
      await ensureMap();
    } else {
      wrap.classList.add('hidden');
    }
  });

  $('#getCurrentLocationBtn')?.addEventListener('click', async () => {
    if (!navigator.geolocation) {
      alert('مرورگر از موقعیت پشتیبانی نمی‌کند.');
      return;
    }
    $('#mapWrap')?.classList.remove('hidden');
    await ensureMap();
    const btn = $('#getCurrentLocationBtn');
    btn.disabled = true;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;
        locationMarker?.setLatLng([lat, lon]);
        locationMap?.setView([lat, lon], 15);
        updateCoords(lat, lon);
        btn.disabled = false;
      },
      () => {
        alert('دریافت موقعیت ناموفق بود.');
        btn.disabled = false;
      },
      { enableHighAccuracy: true, timeout: 8000 }
    );
  });

  if ($('#latitude', form)?.value && $('#longitude', form)?.value) {
    $('#mapWrap')?.classList.remove('hidden');
    ensureMap();
  }

  form.addEventListener('submit', (e) => {
    if (isSubmitting) {
      e.preventDefault();
      return;
    }
    const sizeEl = $('input[name="size"]', form);
    const priceEl = $('input[name="price_total"]', form);
    sizeEl.value = String(rawFrom(sizeEl));
    priceEl.value = String(rawFrom(priceEl));
    const ppmEl = $('#price_per_meter', form);
    if (ppmEl) ppmEl.value = String(rawFrom(ppmEl) || 0);
    syncImageInput();
    isSubmitting = true;
    const btn = form.querySelector('button[type="submit"]');
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin text-xs"></i> در حال ذخیره…';
    }
  });

  recalcPpm();
})();
