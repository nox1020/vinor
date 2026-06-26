(function () {
  'use strict';

  const form = document.getElementById('expressForm');
  if (!form) return;

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  const MAX_IMAGES = 12;
  const uploadUrl = form.dataset.uploadUrl || '';
  const csrfToken = () =>
    $('input[name="csrf_token"]', form)?.value ||
    document.querySelector('meta[name="csrf-token"]')?.content ||
    '';

  /** @type {Array<{id:string,file:File,previewUrl:string,path?:string,url?:string,status:'uploading'|'done'|'error',error?:string}>} */
  let imageItems = [];
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

  // Images — آپلود فوری مثل دیوار
  const dropzone = $('#dropzone', form);
  const imagesInput = $('#imagesInput', form);
  const preview = $('#imagePreview', form);
  const hiddenFields = $('#uploadedImagesFields', form);

  function newImageId() {
    return 'img_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
  }

  function syncHiddenImageFields() {
    if (!hiddenFields) return;
    hiddenFields.innerHTML = '';
    imageItems
      .filter((item) => item.status === 'done' && item.path)
      .forEach((item) => {
        const inp = document.createElement('input');
        inp.type = 'hidden';
        inp.name = 'images';
        inp.value = item.path;
        hiddenFields.appendChild(inp);
      });
  }

  function displaySrc(item) {
    if (item.status === 'done' && item.url) return item.url;
    return item.previewUrl;
  }

  function renderPreviews() {
    if (!preview) return;
    preview.innerHTML = '';
    imageItems.forEach((item) => {
      const div = document.createElement('div');
      div.className =
        'dv-thumb' +
        (item.status === 'uploading' ? ' is-uploading' : '') +
        (item.status === 'error' ? ' is-error' : '');
      div.dataset.id = item.id;

      const img = document.createElement('img');
      img.src = displaySrc(item);
      img.alt = '';
      img.className = 'w-full h-full object-cover';
      div.appendChild(img);

      if (item.status === 'uploading') {
        const overlay = document.createElement('div');
        overlay.className = 'dv-thumb-overlay';
        overlay.innerHTML = '<i class="fa-solid fa-spinner fa-spin text-lg"></i>';
        div.appendChild(overlay);
      } else if (item.status === 'error') {
        const overlay = document.createElement('div');
        overlay.className = 'dv-thumb-overlay';
        overlay.innerHTML =
          '<button type="button" class="img-retry text-[10px] font-bold px-2 py-1 rounded-full bg-white dark:bg-gray-900 text-red-600 shadow">تلاش مجدد</button>';
        div.appendChild(overlay);
      } else if (item.status === 'done') {
        const badge = document.createElement('span');
        badge.className = 'dv-thumb-badge';
        badge.textContent = 'آپلود شد';
        div.appendChild(badge);
      }

      const rm = document.createElement('button');
      rm.type = 'button';
      rm.className =
        'img-rm absolute top-1 left-1 w-6 h-6 rounded-full bg-black/55 text-white text-xs grid place-items-center';
      rm.setAttribute('data-id', item.id);
      rm.innerHTML = '×';
      div.appendChild(rm);

      preview.appendChild(div);
    });
  }

  function removeImage(id) {
    const idx = imageItems.findIndex((x) => x.id === id);
    if (idx < 0) return;
    const item = imageItems[idx];
    if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
    imageItems.splice(idx, 1);
    syncHiddenImageFields();
    renderPreviews();
  }

  async function uploadImageItem(item) {
    if (!uploadUrl) {
      item.status = 'error';
      item.error = 'آدرس آپلود تنظیم نشده';
      renderPreviews();
      return;
    }
    item.status = 'uploading';
    item.error = '';
    renderPreviews();

    const fd = new FormData();
    fd.append('file', item.file);
    const token = csrfToken();
    if (token) fd.append('csrf_token', token);

    try {
      const res = await fetch(uploadUrl, {
        method: 'POST',
        body: fd,
        credentials: 'same-origin',
        headers: token ? { 'X-CSRFToken': token } : {},
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        throw new Error(data.error || 'آپلود ناموفق بود');
      }
      item.status = 'done';
      item.path = data.path;
      item.url = data.url || data.path;
      syncHiddenImageFields();
    } catch (err) {
      item.status = 'error';
      item.error = err && err.message ? err.message : 'خطا در آپلود';
    }
    renderPreviews();
  }

  function queueImages(files) {
    const list = Array.from(files || []).filter((f) => f && f.type && f.type.startsWith('image/'));
    if (!list.length) return;

    const slots = MAX_IMAGES - imageItems.length;
    if (slots <= 0) {
      alert('حداکثر ' + MAX_IMAGES + ' تصویر مجاز است.');
      return;
    }

    list.slice(0, slots).forEach((file) => {
      const item = {
        id: newImageId(),
        file,
        previewUrl: URL.createObjectURL(file),
        status: 'uploading',
      };
      imageItems.push(item);
      uploadImageItem(item);
    });

    if (list.length > slots) {
      alert('فقط ' + slots + ' تصویر دیگر قابل افزودن است.');
    }

    renderPreviews();
  }

  function hasPendingUploads() {
    return imageItems.some((item) => item.status === 'uploading');
  }

  function hasUploadErrors() {
    return imageItems.some((item) => item.status === 'error');
  }

  dropzone?.addEventListener('click', () => imagesInput?.click());
  dropzone?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      imagesInput?.click();
    }
  });
  dropzone?.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('ring-2', 'ring-blue-400');
  });
  dropzone?.addEventListener('dragleave', () => {
    dropzone.classList.remove('ring-2', 'ring-blue-400');
  });
  dropzone?.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('ring-2', 'ring-blue-400');
    if (e.dataTransfer?.files?.length) queueImages(e.dataTransfer.files);
  });

  imagesInput?.addEventListener('change', (e) => {
    if (e.target.files?.length) queueImages(e.target.files);
    e.target.value = '';
  });

  preview?.addEventListener('click', (e) => {
    const rm = e.target.closest('.img-rm');
    if (rm) {
      removeImage(rm.getAttribute('data-id'));
      return;
    }
    const retry = e.target.closest('.img-retry');
    if (retry) {
      const wrap = retry.closest('[data-id]');
      const id = wrap?.getAttribute('data-id');
      const item = imageItems.find((x) => x.id === id);
      if (item) uploadImageItem(item);
    }
  });

  // Video & documents — Divar-style pickers
  let videoObjectUrl = null;

  function bindDocPick(pickBtn) {
    const inputId = pickBtn.getAttribute('data-input');
    const input = inputId ? document.getElementById(inputId) : null;
    if (!input) return;

    const nameEl = pickBtn.querySelector('.doc-pick-name');
    const actionEl = pickBtn.querySelector('.doc-pick-action');
    const clearEl = pickBtn.querySelector('.doc-pick-clear');

    function setEmpty() {
      pickBtn.classList.remove('has-file');
      if (nameEl) {
        nameEl.textContent = '';
        nameEl.classList.add('hidden');
      }
      if (actionEl) actionEl.textContent = 'انتخاب';
      if (clearEl) clearEl.classList.add('hidden');
    }

    function setFile(file) {
      if (!file) {
        setEmpty();
        return;
      }
      pickBtn.classList.add('has-file');
      if (nameEl) {
        nameEl.textContent = file.name;
        nameEl.classList.remove('hidden');
      }
      if (actionEl) actionEl.textContent = 'تغییر';
      if (clearEl) clearEl.classList.remove('hidden');
    }

    pickBtn.addEventListener('click', (e) => {
      if (e.target.closest('.doc-pick-clear')) return;
      input.click();
    });

    clearEl?.addEventListener('click', (e) => {
      e.stopPropagation();
      input.value = '';
      setEmpty();
    });
    clearEl?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        e.stopPropagation();
        input.value = '';
        setEmpty();
      }
    });

    input.addEventListener('change', () => {
      setFile(input.files?.[0] || null);
    });
  }

  $$('.doc-pick', form).forEach(bindDocPick);

  const videoPick = $('#videoPick', form);
  const videoInput = $('#videoInput', form);
  const videoFileName = $('#videoFileName');
  const videoPickAction = $('#videoPickAction');
  const videoClear = $('#videoClear');
  const videoPreviewWrap = $('#videoPreviewWrap');
  const videoPreview = $('#videoPreview');

  function clearVideo() {
    if (videoObjectUrl) {
      URL.revokeObjectURL(videoObjectUrl);
      videoObjectUrl = null;
    }
    if (videoInput) videoInput.value = '';
    videoPick?.classList.remove('has-file');
    videoFileName?.classList.add('hidden');
    if (videoFileName) videoFileName.textContent = '';
    if (videoPickAction) videoPickAction.textContent = 'انتخاب';
    videoClear?.classList.add('hidden');
    videoPreviewWrap?.classList.add('hidden');
    if (videoPreview) videoPreview.removeAttribute('src');
  }

  videoPick?.addEventListener('click', (e) => {
    if (e.target.closest('#videoClear')) return;
    videoInput?.click();
  });

  videoClear?.addEventListener('click', (e) => {
    e.stopPropagation();
    clearVideo();
  });
  videoClear?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      e.stopPropagation();
      clearVideo();
    }
  });

  videoInput?.addEventListener('change', () => {
    const file = videoInput.files?.[0];
    if (!file) {
      clearVideo();
      return;
    }
    videoPick?.classList.add('has-file');
    if (videoFileName) {
      videoFileName.textContent = file.name;
      videoFileName.classList.remove('hidden');
    }
    if (videoPickAction) videoPickAction.textContent = 'تغییر';
    videoClear?.classList.remove('hidden');
    if (videoObjectUrl) URL.revokeObjectURL(videoObjectUrl);
    videoObjectUrl = URL.createObjectURL(file);
    if (videoPreview) videoPreview.src = videoObjectUrl;
    videoPreviewWrap?.classList.remove('hidden');
  });

  // Payment / installments
  const pm = $('#payment_method', form);
  const instBox = $('#installmentsBox', form);
  const instRows = $('#installmentsRows', form);
  const addInst = $('#addInstallmentRow', form);

  function instRowHtml(m, a) {
    return (
      '<div class="installment-row grid grid-cols-[1fr_1fr_auto] gap-2 items-end p-2 rounded-lg bg-gray-50 dark:bg-gray-950 border border-gray-100 dark:border-gray-800">' +
      '<div><label class="text-[10px] text-gray-500">ماه</label>' +
      '<input type="number" min="1" name="installment_months[]" value="' + (m || '') + '" class="dv-inp ad-inp text-sm !border !border-gray-200 dark:!border-gray-700 !rounded-lg !px-2 !py-1.5 !bg-white dark:!bg-gray-900"></div>' +
      '<div><label class="text-[10px] text-gray-500">مبلغ</label>' +
      '<input type="text" inputmode="numeric" name="installment_amounts[]" value="' + (a || '') + '" class="dv-inp ad-inp text-sm !border !border-gray-200 dark:!border-gray-700 !rounded-lg !px-2 !py-1.5 !bg-white dark:!bg-gray-900"></div>' +
      '<button type="button" class="remove-installment w-9 h-9 rounded-lg border border-gray-200 dark:border-gray-700 text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30"><i class="fa-solid fa-trash text-xs"></i></button></div>'
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
    const btn = $('#toggleMapBtn');
    if (wrap.classList.contains('hidden')) {
      wrap.classList.remove('hidden');
      if (btn) btn.textContent = 'بستن نقشه';
      await ensureMap();
    } else {
      wrap.classList.add('hidden');
      if (btn) btn.textContent = 'نمایش نقشه';
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
    if (hasPendingUploads()) {
      e.preventDefault();
      alert('لطفاً تا پایان آپلود تصاویر صبر کنید.');
      return;
    }
    if (hasUploadErrors()) {
      e.preventDefault();
      alert('برخی تصاویر آپلود نشده‌اند. آن‌ها را حذف کنید یا دوباره تلاش کنید.');
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
    syncHiddenImageFields();

    isSubmitting = true;
    document.querySelectorAll('#submitBtn, #submitBtnMobile').forEach((btn) => {
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin ml-1"></i> در حال ثبت…';
    });
  });

  recalc();
})();
