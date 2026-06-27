(function () {
  'use strict';

  const form = document.getElementById('expressForm');
  if (!form) return;

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  const MAX_IMAGES = 12;
  const uploadUrl = form.dataset.uploadUrl || '';
  const uploadVideoUrl = form.dataset.uploadVideoUrl || '';
  const uploadDocumentUrl = form.dataset.uploadDocumentUrl || '';
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

  function initIntFieldsFromDom() {
    $$('[data-format-int]', form).forEach((el) => {
      const n = parseDigits(el.value);
      if (n > 0) {
        el.dataset.rawValue = String(n);
        if (!el.readOnly) el.value = fmt(n);
      }
    });
  }
  initIntFieldsFromDom();

  // Images — آپلود فوری مثل دیوار
  const dropzone = $('#dropzone', form);
  const imagesInput = $('#imagesInput', form);
  const preview = $('#imagePreview', form);
  const hiddenFields = $('#uploadedImagesFields', form);

  function newImageId() {
    return 'img_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
  }

  function imageUrlFromPath(path) {
    const p = String(path || '').trim();
    if (!p) return '';
    if (p.includes('://')) return p;
    if (p.startsWith('/')) return p;
    if (p.startsWith('uploads/')) return '/' + p;
    return '/uploads/' + p.replace(/^\/+/, '');
  }

  function restoreImagesFromForm() {
    if (!hiddenFields) return;
    $$('input[name="images"]', hiddenFields).forEach((inp) => {
      const path = (inp.value || '').trim();
      if (!path) return;
      const url = imageUrlFromPath(path);
      imageItems.push({
        id: newImageId(),
        file: null,
        previewUrl: url,
        path,
        url,
        status: 'done',
      });
    });
    if (imageItems.length) renderPreviews();
  }

  restoreImagesFromForm();

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
    if (item.previewUrl && item.file) URL.revokeObjectURL(item.previewUrl);
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
    return (
      imageItems.some((item) => item.status === 'uploading') ||
      mediaUploads.some((m) => m.status === 'uploading')
    );
  }

  function hasUploadErrors() {
    return (
      imageItems.some((item) => item.status === 'error') ||
      mediaUploads.some((m) => m.status === 'error')
    );
  }

  async function postUploadFile(url, file) {
    if (!url) throw new Error('آدرس آپلود تنظیم نشده');
    const fd = new FormData();
    fd.append('file', file);
    const token = csrfToken();
    if (token) fd.append('csrf_token', token);
    const res = await fetch(url, {
      method: 'POST',
      body: fd,
      credentials: 'same-origin',
      headers: token ? { 'X-CSRFToken': token } : {},
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
      throw new Error(data.error || 'آپلود ناموفق بود');
    }
    return data;
  }

  function mediaUrlFromPath(path) {
    const p = String(path || '').trim();
    if (!p) return '';
    if (p.includes('://')) return p;
    if (p.startsWith('/')) return p;
    if (p.startsWith('uploads/')) return '/' + p;
    return p;
  }

  /** @type {Array<{key:string,status:'idle'|'uploading'|'done'|'error',path?:string,url?:string,name?:string,file?:File,error?:string}>} */
  const mediaUploads = [];

  function getMediaState(key) {
    let state = mediaUploads.find((m) => m.key === key);
    if (!state) {
      state = { key, status: 'idle' };
      mediaUploads.push(state);
    }
    return state;
  }

  function setPickerUi(pickBtn, state, displayName) {
    if (!pickBtn) return;
    const nameEl = pickBtn.querySelector('.doc-pick-name') || pickBtn.querySelector('#videoFileName');
    const actionEl = pickBtn.querySelector('.doc-pick-action') || pickBtn.querySelector('#videoPickAction');
    const clearEl = pickBtn.querySelector('.doc-pick-clear') || pickBtn.querySelector('#videoClear');

    pickBtn.classList.remove('has-file', 'is-uploading', 'is-error');

    if (state.status === 'uploading') {
      pickBtn.classList.add('is-uploading');
      if (actionEl) actionEl.innerHTML = '<i class="fa-solid fa-spinner fa-spin text-xs"></i>';
      if (clearEl) clearEl.classList.add('hidden');
      return;
    }

    if (state.status === 'error') {
      pickBtn.classList.add('is-error');
      if (nameEl) {
        nameEl.textContent = state.error || 'خطا در آپلود';
        nameEl.classList.remove('hidden');
      }
      if (actionEl) actionEl.textContent = 'تلاش مجدد';
      if (clearEl) clearEl.classList.remove('hidden');
      return;
    }

    if (state.status === 'done' && state.path) {
      pickBtn.classList.add('has-file');
      if (nameEl) {
        nameEl.textContent = displayName || state.name || state.path;
        nameEl.classList.remove('hidden');
      }
      if (actionEl) actionEl.textContent = 'تغییر';
      if (clearEl) clearEl.classList.remove('hidden');
      return;
    }

    if (nameEl) {
      nameEl.textContent = '';
      nameEl.classList.add('hidden');
    }
    if (actionEl) actionEl.textContent = 'انتخاب';
    if (clearEl) clearEl.classList.add('hidden');
  }

  async function uploadMediaItem(state, pickBtn, hiddenEl, url, file, displayName) {
    state.file = file;
    state.status = 'uploading';
    state.error = '';
    setPickerUi(pickBtn, state, displayName);
    try {
      const data = await postUploadFile(url, file);
      state.status = 'done';
      state.path = data.path;
      state.url = data.url || mediaUrlFromPath(data.path);
      state.name = data.name || file.name;
      if (hiddenEl) hiddenEl.value = data.path;
    } catch (err) {
      state.status = 'error';
      state.error = err && err.message ? err.message : 'خطا در آپلود';
      if (hiddenEl) hiddenEl.value = '';
    }
    setPickerUi(pickBtn, state, displayName || file.name);
    return state;
  }

  function clearMediaItem(state, pickBtn, hiddenEl, inputEl, onClear) {
    state.status = 'idle';
    state.path = '';
    state.url = '';
    state.name = '';
    state.file = null;
    state.error = '';
    if (hiddenEl) hiddenEl.value = '';
    if (inputEl) inputEl.value = '';
    setPickerUi(pickBtn, state);
    if (onClear) onClear();
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

  // Video & documents — آپلود فوری مثل عکس
  let videoObjectUrl = null;

  const videoPick = $('#videoPick', form);
  const videoInput = $('#videoInput', form);
  const uploadedVideoPath = $('#uploadedVideoPath', form);
  const videoPreviewWrap = $('#videoPreviewWrap');
  const videoPreview = $('#videoPreview');
  const videoState = getMediaState('video');

  function clearVideoPreview() {
    if (videoObjectUrl) {
      URL.revokeObjectURL(videoObjectUrl);
      videoObjectUrl = null;
    }
    videoPreviewWrap?.classList.add('hidden');
    if (videoPreview) videoPreview.removeAttribute('src');
  }

  function showVideoPreview(fileOrUrl) {
    if (!videoPreview) return;
    if (videoObjectUrl) {
      URL.revokeObjectURL(videoObjectUrl);
      videoObjectUrl = null;
    }
    if (fileOrUrl instanceof File) {
      videoObjectUrl = URL.createObjectURL(fileOrUrl);
      videoPreview.src = videoObjectUrl;
    } else if (fileOrUrl) {
      videoPreview.src = fileOrUrl;
    }
    videoPreviewWrap?.classList.remove('hidden');
  }

  function restoreVideoFromForm() {
    const path = (uploadedVideoPath?.value || '').trim();
    if (!path) return;
    videoState.status = 'done';
    videoState.path = path;
    videoState.url = mediaUrlFromPath(path);
    videoState.name = path.split('/').pop() || path;
    setPickerUi(videoPick, videoState, videoState.name);
    showVideoPreview(videoState.url);
  }
  restoreVideoFromForm();

  videoPick?.addEventListener('click', (e) => {
    if (e.target.closest('#videoClear') || e.target.closest('.doc-pick-clear')) return;
    if (videoState.status === 'uploading') return;
    if (videoState.status === 'error' && videoState.file) {
      uploadMediaItem(videoState, videoPick, uploadedVideoPath, uploadVideoUrl, videoState.file);
      return;
    }
    videoInput?.click();
  });

  $('#videoClear')?.addEventListener('click', (e) => {
    e.stopPropagation();
    clearMediaItem(videoState, videoPick, uploadedVideoPath, videoInput, clearVideoPreview);
  });
  $('#videoClear')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      e.stopPropagation();
      clearMediaItem(videoState, videoPick, uploadedVideoPath, videoInput, clearVideoPreview);
    }
  });

  videoInput?.addEventListener('change', async () => {
    const file = videoInput.files?.[0];
    if (!file) return;
    showVideoPreview(file);
    await uploadMediaItem(videoState, videoPick, uploadedVideoPath, uploadVideoUrl, file, file.name);
    videoInput.value = '';
    if (videoState.status === 'done' && videoState.url) {
      showVideoPreview(videoState.url);
    }
  });

  function bindDocPick(pickBtn) {
    const inputId = pickBtn.getAttribute('data-input');
    const hiddenId = pickBtn.getAttribute('data-hidden');
    const input = inputId ? document.getElementById(inputId) : null;
    const hiddenEl = hiddenId ? document.getElementById(hiddenId) : null;
    if (!input) return;

    const key = hiddenId || inputId;
    const state = getMediaState(key);
    const clearEl = pickBtn.querySelector('.doc-pick-clear');

    function restoreDocFromForm() {
      const path = (hiddenEl?.value || '').trim();
      if (!path) return;
      state.status = 'done';
      state.path = path;
      state.name = path.replace(/^draft_\d+_/, '') || path.split('/').pop() || path;
      setPickerUi(pickBtn, state, state.name);
    }
    restoreDocFromForm();

    pickBtn.addEventListener('click', (e) => {
      if (e.target.closest('.doc-pick-clear')) return;
      if (state.status === 'uploading') return;
      if (state.status === 'error' && state.file) {
        uploadMediaItem(state, pickBtn, hiddenEl, uploadDocumentUrl, state.file);
        return;
      }
      input.click();
    });

    clearEl?.addEventListener('click', (e) => {
      e.stopPropagation();
      clearMediaItem(state, pickBtn, hiddenEl, input);
    });
    clearEl?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        e.stopPropagation();
        clearMediaItem(state, pickBtn, hiddenEl, input);
      }
    });

    input.addEventListener('change', async () => {
      const file = input.files?.[0];
      if (!file) return;
      await uploadMediaItem(state, pickBtn, hiddenEl, uploadDocumentUrl, file, file.name);
      input.value = '';
    });
  }

  $$('.doc-pick', form).forEach(bindDocPick);

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
      '<input type="text" inputmode="numeric" name="installment_amounts[]" value="' + (a || '') + '" data-format-int class="dv-inp ad-inp text-sm !border !border-gray-200 dark:!border-gray-700 !rounded-lg !px-2 !py-1.5 !bg-white dark:!bg-gray-900"></div>' +
      '<button type="button" class="remove-installment w-9 h-9 rounded-lg border border-gray-200 dark:border-gray-700 text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30"><i class="fa-solid fa-trash text-xs"></i></button></div>'
    );
  }

  function toggleInst() {
    const v = (pm?.value || '').trim();
    if (!instBox) return;
    if (v === 'اقساطی') {
      instBox.classList.remove('hidden');
      if (!instRows.querySelector('.installment-row')) {
        instRows.insertAdjacentHTML('beforeend', instRowHtml('', ''));
        const row = instRows.querySelector('.installment-row');
        const amt = row && $('input[name="installment_amounts[]"]', row);
        if (amt) hookIntInput(amt);
      }
    } else {
      instBox.classList.add('hidden');
    }
  }

  pm?.addEventListener('change', toggleInst);
  addInst?.addEventListener('click', () => {
    instRows.insertAdjacentHTML('beforeend', instRowHtml('', ''));
    const row = instRows.lastElementChild;
    const amt = row && $('input[name="installment_amounts[]"]', row);
    if (amt) hookIntInput(amt);
  });
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
      alert('لطفاً تا پایان آپلود فایل‌ها (تصویر، ویدئو یا مدرک) صبر کنید.');
      return;
    }
    if (hasUploadErrors()) {
      e.preventDefault();
      alert('برخی فایل‌ها آپلود نشده‌اند. آن‌ها را حذف کنید یا دوباره تلاش کنید.');
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
    if (title.length < 10) {
      e.preventDefault();
      alert('عنوان باید حداقل ۱۰ کاراکتر باشد.');
      return;
    }
    if (!paymentMethod) {
      e.preventDefault();
      alert('نحوه پرداخت را انتخاب کنید.');
      return;
    }
    if (!contact || parseDigits(contact).length < 10) {
      e.preventDefault();
      alert('شماره تماس پشتیبانی معتبر نیست.');
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
    const contactEl = $('input[name="vinor_contact"]', form);
    if (contactEl) contactEl.value = String(parseDigits(contact));
    if (paymentMethod === 'اقساطی') {
      $$('.installment-row', instRows).forEach((r) => {
        const aEl = $('input[name="installment_amounts[]"]', r);
        if (aEl) aEl.value = String(parseDigits(aEl.dataset.rawValue || aEl.value));
      });
    }
    syncHiddenImageFields();

    isSubmitting = true;
    document.querySelectorAll('#submitBtn, #submitBtnMobile').forEach((btn) => {
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin ml-1"></i> در حال ثبت…';
    });
  });

  recalc();
})();
