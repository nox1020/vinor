(function () {
  'use strict';

  const form = document.getElementById('expressForm');
  if (!form) return;

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  let selectedImages = [];
  let mapReady = false;
  let locationMap = null;
  let locationMarker = null;
  let isSubmitting = false;

  const strip = {
    size: $('#stripSize'),
    price: $('#stripPrice'),
    ppm: $('#stripPpm'),
    pct: $('#stripPct'),
    comm: $('#stripComm'),
  };

  function parseDigits(str) {
    if (!str) return 0;
    let s = String(str);
    const fa = '۰۱۲۳۴۵۶۷۸۹';
    for (let i = 0; i < fa.length; i++) s = s.split(fa[i]).join(String(i));
    s = s.replace(/[^\d]/g, '');
    return parseInt(s, 10) || 0;
  }

  function fmt(n) {
    return n > 0 ? n.toLocaleString('fa-IR') : '—';
  }

  function rawFrom(el) {
    if (!el) return 0;
    const v = el.dataset.rawValue || el.value || '';
    return parseDigits(v);
  }

  function recalc() {
    const size = rawFrom($('input[name="size"]', form));
    const price = rawFrom($('input[name="price_total"]', form));
    const pct = parseFloat($('#express_commission_pct')?.value || '0') || 0;
    const ppm = size > 0 && price > 0 ? Math.round(price / size) : 0;
    const comm = price > 0 && pct > 0 ? Math.round(price * (pct / 100)) : 0;

    if (strip.size) strip.size.textContent = size > 0 ? fmt(size) + ' م' : '—';
    if (strip.price) strip.price.textContent = price > 0 ? fmt(price) : '—';
    if (strip.ppm) strip.ppm.textContent = ppm > 0 ? fmt(ppm) : '—';
    if (strip.pct) strip.pct.textContent = pct > 0 ? pct + '٪' : '—';
    if (strip.comm) strip.comm.textContent = comm > 0 ? fmt(comm) : '—';

    const ppmEl = $('#price_per_meter', form);
    if (ppmEl) {
      ppmEl.dataset.rawValue = ppm > 0 ? String(ppm) : '';
      ppmEl.value = ppm > 0 ? fmt(ppm) : '';
    }
    const commEl = $('#express_commission_amount', form);
    if (commEl) {
      commEl.dataset.rawValue = comm > 0 ? String(comm) : '';
      commEl.value = comm > 0 ? fmt(comm) : '';
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
      recalc();
    });
    el.addEventListener('blur', () => {
      const n = parseDigits(el.value);
      el.dataset.rawValue = n ? String(n) : '';
      el.value = n ? fmt(n) : '';
      recalc();
    });
  }

  $$('[data-format-int]', form).forEach(hookIntInput);
  $('#express_commission_pct', form)?.addEventListener('input', recalc);

  // Images
  const dropzone = $('#dropzone', form);
  const imagesInput = $('#imagesInput', form);
  const preview = $('#imagePreview', form);

  function syncImageInput() {
    if (!imagesInput || typeof DataTransfer === 'undefined') return;
    const dt = new DataTransfer();
    selectedImages.forEach((f) => dt.items.add(f));
    imagesInput.files = dt.files;
  }

  function renderPreviews() {
    if (!preview) return;
    preview.innerHTML = '';
    selectedImages.forEach((file, index) => {
      const url = URL.createObjectURL(file);
      const div = document.createElement('div');
      div.className = 'relative aspect-square rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700';
      div.innerHTML =
        '<img src="' + url + '" alt="" class="w-full h-full object-cover">' +
        '<button type="button" data-idx="' + index + '" class="img-rm absolute top-1 left-1 w-6 h-6 rounded-full bg-red-500 text-white text-xs">×</button>';
      preview.appendChild(div);
      div.querySelector('img').onload = () => URL.revokeObjectURL(url);
    });
  }

  function addImages(files) {
    selectedImages = selectedImages.concat(Array.from(files)).slice(0, 12);
    syncImageInput();
    renderPreviews();
  }

  dropzone?.addEventListener('click', () => imagesInput?.click());
  dropzone?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      imagesInput?.click();
    }
  });
  imagesInput?.addEventListener('change', (e) => {
    if (e.target.files?.length) addImages(e.target.files);
  });
  preview?.addEventListener('click', (e) => {
    const btn = e.target.closest('.img-rm');
    if (!btn) return;
    const idx = parseInt(btn.getAttribute('data-idx'), 10);
    selectedImages.splice(idx, 1);
    syncImageInput();
    renderPreviews();
  });

  // Payment / installments
  const pm = $('#payment_method', form);
  const instBox = $('#installmentsBox', form);
  const instRows = $('#installmentsRows', form);
  const addInst = $('#addInstallmentRow', form);

  function instRowHtml(m, a) {
    return (
      '<div class="installment-row grid grid-cols-[1fr_1fr_auto] gap-2 items-end">' +
      '<div><label class="text-[10px] text-gray-500">ماه</label>' +
      '<input type="number" min="1" name="installment_months[]" value="' + (m || '') + '" class="ad-inp text-sm"></div>' +
      '<div><label class="text-[10px] text-gray-500">مبلغ</label>' +
      '<input type="text" inputmode="numeric" name="installment_amounts[]" value="' + (a || '') + '" class="ad-inp text-sm"></div>' +
      '<button type="button" class="remove-installment w-9 h-9 rounded-lg border border-gray-200 dark:border-gray-700 text-red-500"><i class="fa-solid fa-trash text-xs"></i></button></div>'
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

  // Lazy map
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
    if (!latEl?.value) updateCoords(lat, lon);
    locationMap.on('click', (e) => {
      locationMarker.setLatLng(e.latlng);
      updateCoords(e.latlng.lat, e.latlng.lng);
    });
    locationMarker.on('dragend', (e) => {
      const p = e.target.getLatLng();
      updateCoords(p.lat, p.lng);
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
    const btn = $('#getCurrentLocationBtn');
    if (!navigator.geolocation) {
      alert('مرورگر از موقعیت پشتیبانی نمی‌کند.');
      return;
    }
    $('#mapWrap')?.classList.remove('hidden');
    await ensureMap();
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

  // Submit
  form.addEventListener('submit', (e) => {
    if (isSubmitting) {
      e.preventDefault();
      return;
    }
    const title = $('input[name="title"]', form)?.value.trim();
    const location = $('input[name="location"]', form)?.value.trim();
    const city = $('select[name="city"]', form)?.value.trim();
    const sizeEl = $('input[name="size"]', form);
    const priceEl = $('input[name="price_total"]', form);
    const sizeNum = rawFrom(sizeEl);
    const priceNum = rawFrom(priceEl);
    const paymentMethod = (pm?.value || '').trim();
    const contact = $('input[name="vinor_contact"]', form)?.value.trim();

    if (!title || !location || !city || !sizeNum || !priceNum) {
      e.preventDefault();
      alert('عنوان، شهر، موقعیت، متراژ و قیمت الزامی است.');
      return;
    }
    if (!paymentMethod) {
      e.preventDefault();
      alert('نحوه پرداخت را انتخاب کنید.');
      return;
    }
    if (!contact) {
      e.preventDefault();
      alert('شماره تماس پشتیبانی الزامی است.');
      return;
    }
    if (paymentMethod === 'اقساطی') {
      const ok = $$('.installment-row', instRows).some((r) => {
        const m = parseDigits($('input[name="installment_months[]"]', r)?.value);
        const a = parseDigits($('input[name="installment_amounts[]"]', r)?.value);
        return m > 0 && a > 0;
      });
      if (!ok) {
        e.preventDefault();
        alert('حداقل یک قسط معتبر وارد کنید.');
        return;
      }
    }

    sizeEl.value = String(sizeNum);
    priceEl.value = String(priceNum);
    const ppmEl = $('#price_per_meter', form);
    if (ppmEl && sizeNum > 0) ppmEl.value = String(Math.round(priceNum / sizeNum));
    syncImageInput();

    isSubmitting = true;
    document.querySelectorAll('#submitBtn, #submitBtnMobile').forEach((btn) => {
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin ml-1"></i> در حال ثبت…';
    });
  });

  recalc();
})();
