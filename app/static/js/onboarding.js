/**
 * Onboarding Tour System - Divar Style
 * سیستم تور راهنمای کاربران به سبک دیوار
 */

class OnboardingTour {
  constructor() {
    this.currentStep = 0;
    this.tour = null;
    this.overlay = null;
    this.tooltip = null;
    this.isActive = false;
    this.tourData = [];
  }

  // Avoid showing the tour on authentication pages (login/OTP)
  isAuthPage() {
    const path = window.location.pathname || '';
    return (
      path.includes('/login') ||
      path.includes('/verify') ||
      path.includes('/auth/')
    );
  }

  isDashboardPath(path = window.location.pathname) {
    return path.includes('/dashboard') || path === '/express/partner/' || path === '/express/partner';
  }

  isLandDetailPath(path = window.location.pathname) {
    return path.includes('/lands/') || path.includes('/land_detail');
  }

  findTourElement(selector) {
    const nodes = document.querySelectorAll(selector);
    for (const el of nodes) {
      const rect = el.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) return el;
    }
    return nodes.length ? nodes[0] : null;
  }

  persistTourNavigation(nextStepIndex, targetUrl) {
    sessionStorage.setItem('vinor_tour_step', nextStepIndex.toString());
    sessionStorage.setItem('vinor_tour_data', JSON.stringify(this.tourData));
    if (targetUrl && this.isLandDetailPath(targetUrl)) {
      sessionStorage.setItem('vinor_tour_land_url', targetUrl);
    }
    window.location.href = targetUrl;
  }

  clearTourSession() {
    sessionStorage.removeItem('vinor_tour_step');
    sessionStorage.removeItem('vinor_tour_data');
    sessionStorage.removeItem('vinor_start_full_tour');
  }

  init() {
    if (this.isAuthPage()) return;

    // بررسی اینکه آیا تور از sessionStorage باید ادامه یابد
    const tourStep = sessionStorage.getItem('vinor_tour_step');
    const tourData = sessionStorage.getItem('vinor_tour_data');
    
    if (tourStep !== null && tourData) {
      try {
        this.tourData = JSON.parse(tourData);
      } catch (e) {
        console.warn('Invalid tour session data, clearing.', e);
        this.clearTourSession();
        return;
      }
      this.currentStep = parseInt(tourStep, 10);
      if (Number.isNaN(this.currentStep)) {
        this.clearTourSession();
        return;
      }
      this.isActive = true;

      setTimeout(() => {
        this.createOverlay();
        this.showStep(this.currentStep);
      }, 500);
      return;
    }

    const startFullTour = sessionStorage.getItem('vinor_start_full_tour');
    if (startFullTour === 'true') {
      sessionStorage.removeItem('vinor_start_full_tour');
      setTimeout(() => {
        this.startTour(true);
      }, 800);
    }
  }

  startTour(force = false) {
    if (this.isActive && !force) return;

    if (force && this.isActive) {
      this.removeTourUiImmediate();
      this.isActive = false;
    }

    this.isActive = true;
    this.currentStep = 0;

    if (force) {
      this.tourData = this.getFullTour();
      if (!this.isDashboardPath()) {
        sessionStorage.setItem('vinor_start_full_tour', 'true');
        window.location.href = '/express/partner/dashboard';
        return;
      }
    } else {
      const path = window.location.pathname;
      if (this.isDashboardPath(path)) {
        this.tourData = this.getDashboardTour();
      } else if (this.isLandDetailPath(path)) {
        this.tourData = this.getLandDetailTour();
      } else if (path.includes('/commissions')) {
        this.tourData = this.getCommissionsTour();
      } else if (path.includes('/notes')) {
        this.tourData = this.getNotesTour();
      } else if (path.includes('/profile')) {
        this.tourData = this.getProfileTour();
      } else if (path.includes('/support')) {
        this.tourData = this.getSupportTour();
      } else {
        this.tourData = this.getDashboardTour();
      }
    }

    if (this.tourData.length === 0) return;

    this.createOverlay();
    this.showStep(0);
  }

  getDashboardTour() {
    return [
      {
        element: '[data-tour="dashboard-header"]',
        title: 'خوش آمدید! 👋',
        description: 'این پنل همکاران وینور اکسپرس است. در اینجا می‌توانید فایل‌های اختصاص داده شده را مشاهده کنید.',
        position: 'bottom'
      },
      {
        element: '[data-tour="dashboard-filters"]',
        title: 'فیلترهای سریع',
        description: 'با این چیپ‌ها و دسته‌های زیرین می‌توانید آگهی‌ها را محدود کنید؛ مثلاً استخر، جنگلی، زمین و باغ یا فوری.',
        position: 'bottom'
      },
      {
        element: '[data-tour="land-card"]',
        title: 'کارت فایل',
        description: 'هر کارت یک فایل اختصاص داده شده به شماست. روی کارت کلیک کنید تا جزئیات را ببینید.',
        position: 'top'
      },
      {
        element: '[data-tour="bottom-nav"]',
        title: 'منوی پایین',
        description: 'از این منو می‌توانید به بخش‌های مختلف پنل دسترسی داشته باشید: داشبورد، پورسانت‌ها، یادداشت‌ها و پروفایل.',
        position: 'top'
      }
    ];
  }

  getLandDetailTour() {
    return [
      {
        element: '[data-tour="land-image"]',
        title: 'تصویر فایل',
        description: 'تصویر اصلی فایل را اینجا می‌بینید. می‌توانید گالری تصاویر را هم مشاهده کنید.',
        position: 'bottom'
      },
      {
        element: '[data-tour="land-info"]',
        title: 'اطلاعات فایل',
        description: 'تمام اطلاعات مهم فایل مانند قیمت، اندازه، موقعیت و کمیسیون در این بخش نمایش داده می‌شود.',
        position: 'top'
      },
      {
        element: '[data-tour="transaction-btn"]',
        title: 'دکمه معامله',
        description: 'اگر مشتری پیدا کردید، روی این دکمه کلیک کنید تا وضعیت فایل را به "در حال معامله" تغییر دهید.',
        position: 'top'
      },
      {
        element: '[data-tour="share-btn"]',
        title: 'اشتراک‌گذاری',
        description: 'می‌توانید لینک فایل را با مشتریان به اشتراک بگذارید. با کلیک روی این دکمه، لینک کپی می‌شود.',
        position: 'top'
      },
      {
        element: '[data-tour="contact-btn"]',
        title: 'تماس',
        description: 'برای تماس با مالک فایل، روی این دکمه کلیک کنید.',
        position: 'top'
      }
    ];
  }

  getCommissionsTour() {
    return [
      {
        element: '[data-tour="commissions-stats"]',
        title: 'آمار پورسانت‌ها',
        description: 'در این بخش می‌توانید کل درآمد، درآمد در انتظار و تعداد فروش‌های موفق را مشاهده کنید.',
        position: 'bottom'
      },
      {
        element: '[data-tour="commission-item"]',
        title: 'لیست پورسانت‌ها',
        description: 'تمام پورسانت‌های شما در اینجا نمایش داده می‌شود. وضعیت هر پورسانت (در انتظار، تأیید شده، پرداخت شده) مشخص است.',
        position: 'top'
      }
    ];
  }

  getNotesTour() {
    return [
      {
        element: '[data-tour="notes-header"]',
        title: 'یادداشت‌های خصوصی 📝',
        description: 'در این صفحه می‌توانید یادداشت‌های شخصی خود را ثبت و مدیریت کنید. این یادداشت‌ها فقط برای شما قابل مشاهده است.',
        position: 'bottom'
      },
      {
        element: '[data-tour="notes-add-button"]',
        title: 'افزودن یادداشت',
        description: 'برای افزودن یادداشت جدید، روی دکمه + در هدر کلیک کنید. سپس می‌توانید یادداشت خود را بنویسید و ذخیره کنید.',
        position: 'bottom',
        action: 'click',
        actionMessage: 'لطفاً روی دکمه + کلیک کنید تا فرم افزودن یادداشت نمایش داده شود.'
      },
      {
        element: '[data-tour="notes-input"]',
        title: 'ثبت یادداشت',
        description: 'یادداشت خود را در این فیلد بنویسید. می‌توانید هر چیزی که می‌خواهید به خاطر بسپارید را اینجا ثبت کنید.',
        position: 'bottom',
        waitForElement: true
      },
      {
        element: '[data-tour="notes-grid"]',
        title: 'یادداشت‌های شما',
        description: 'تمام یادداشت‌های شما در اینجا نمایش داده می‌شود. می‌توانید هر یادداشت را با hover کردن و کلیک روی آیکون سطل زباله حذف کنید.',
        position: 'top'
      }
    ];
  }

  getProfileTour() {
    return [
      {
        element: '[data-tour="profile-section"]',
        title: 'پروفایل شما 👤',
        description: 'در این بخش اطلاعات حساب کاربری شما شامل نام، شماره تماس و نقش نمایش داده می‌شود. همچنین می‌توانید از اینجا از حساب خود خارج شوید.',
        position: 'bottom'
      },
      {
        element: '[data-tour="notes-link"]',
        title: 'یادداشت‌های خصوصی 📝',
        description: 'یادداشت‌های شخصی خود را اینجا ثبت و مدیریت کنید. این یادداشت‌ها فقط برای شما قابل مشاهده است و می‌توانید از آن‌ها برای یادآوری اطلاعات مهم استفاده کنید.',
        position: 'top'
      },
      {
        element: '[data-tour="notifications-link"]',
        title: 'اعلان‌ها 🔔',
        description: 'تمام اعلان‌های مهم مانند تایید پورسانت، فایل‌های جدید و پیام‌های سیستم در این بخش نمایش داده می‌شود. تعداد اعلان‌های خوانده نشده روی آیکون نمایش داده می‌شود.',
        position: 'top'
      },
      {
        element: '[data-tour="top-sellers-link"]',
        title: 'فروشنده‌های برتر 🏆',
        description: 'رتبه‌بندی همکاران برتر را مشاهده کنید و ببینید چه کسانی بیشترین فروش را داشته‌اند. این می‌تواند انگیزه‌بخش باشد!',
        position: 'top'
      },
      {
        element: '[data-tour="support-link"]',
        title: 'تماس با پشتیبانی 💬',
        description: 'از این بخش با پشتیبانی تماس بگیرید، راهنمای پلتفرم را بخوانید و در صورت نیاز تور راهنما را دوباره اجرا کنید.',
        position: 'top'
      },
      {
        element: '[data-tour="bottom-nav"]',
        title: 'منوی پایین 📱',
        description: 'از این منو می‌توانید به بخش‌های اصلی پنل دسترسی سریع داشته باشید: فایل‌ها، پورسانت‌ها، اعلان‌ها و پروفایل.',
        position: 'top'
      }
    ];
  }

  getSupportTour() {
    return [
      {
        element: '[data-tour="help-link"]',
        title: 'راهنمای استفاده 📚',
        description: 'راهنمای کامل استفاده از پلتفرم را از اینجا مطالعه کنید.',
        position: 'top'
      },
      {
        element: '[data-tour="restart-tour"]',
        title: 'اجرای تور راهنما 🔄',
        description: 'برای مشاهدهٔ آموزش‌های پلتفرم از ابتدا، روی این دکمه بزنید.',
        position: 'top'
      },
      {
        element: '[data-tour="bottom-nav"]',
        title: 'منوی پایین 📱',
        description: 'از این منو می‌توانید به بخش‌های اصلی پنل دسترسی سریع داشته باشید.',
        position: 'top'
      }
    ];
  }

  getFullTour() {
    // تور کامل که از dashboard شروع می‌شود و تمام صفحات را پوشش می‌دهد
    return [
      // مرحله 1: Dashboard - معرفی
      {
        element: '[data-tour="dashboard-header"]',
        title: 'خوش آمدید! 👋',
        description: 'این پنل همکاران وینور اکسپرس است. در اینجا می‌توانید فایل‌های اختصاص داده شده را مشاهده کنید.',
        position: 'bottom',
        page: 'dashboard'
      },
      // مرحله 2: فیلترها
      {
        element: '[data-tour="dashboard-filters"]',
        title: 'فیلترهای سریع',
        description: 'با این چیپ‌ها و دسته‌های زیرین می‌توانید آگهی‌ها را محدود کنید؛ مثلاً استخر، جنگلی، زمین و باغ یا فوری.',
        position: 'bottom',
        page: 'dashboard'
      },
      // مرحله 3: کارت فایل
      {
        element: '[data-tour="land-card"]',
        title: 'کارت فایل',
        description: 'هر کارت یک فایل اختصاص داده شده به شماست. می‌توانید روی کارت کلیک کنید تا جزئیات را ببینید.',
        position: 'top',
        page: 'dashboard',
        action: 'auto-navigate',
        actionMessage: 'در حال انتقال به صفحه جزئیات فایل...',
        nextUrl: null // به صورت خودکار از کارت اول گرفته می‌شود
      },
      // مرحله 4: جزئیات فایل - تصویر
      {
        element: '[data-tour="land-image"]',
        title: 'تصویر فایل',
        description: 'تصویر اصلی فایل را اینجا می‌بینید. می‌توانید گالری تصاویر را هم مشاهده کنید.',
        position: 'bottom',
        page: 'land_detail',
        waitForElement: true // منتظر بمان تا المنت پیدا شود
      },
      // مرحله 5: اطلاعات فایل
      {
        element: '[data-tour="land-info"]',
        title: 'اطلاعات فایل',
        description: 'تمام اطلاعات مهم فایل مانند قیمت، اندازه، موقعیت و کمیسیون در این بخش نمایش داده می‌شود.',
        position: 'top',
        page: 'land_detail'
      },
      // مرحله 6: دکمه معامله
      {
        element: '[data-tour="transaction-btn"]',
        title: 'دکمه معامله',
        description: 'اگر مشتری پیدا کردید، روی این دکمه کلیک کنید تا وضعیت فایل را به "در حال معامله" تغییر دهید.',
        position: 'top',
        page: 'land_detail'
      },
      // مرحله 7: دکمه اشتراک
      {
        element: '[data-tour="share-btn"]',
        title: 'اشتراک‌گذاری',
        description: 'می‌توانید لینک فایل را با مشتریان به اشتراک بگذارید. با کلیک روی این دکمه، لینک کپی می‌شود.',
        position: 'top',
        page: 'land_detail'
      },
      // مرحله 8: دکمه تماس
      {
        element: '[data-tour="contact-btn"]',
        title: 'تماس',
        description: 'برای تماس با مالک فایل، روی این دکمه کلیک کنید.',
        position: 'top',
        page: 'land_detail',
        action: 'navigate',
        actionMessage: 'حالا به منوی پایین بروید و روی "پورسانت" کلیک کنید. بعد از رفتن به صفحه پورسانت، تور ادامه می‌یابد.',
        nextUrl: '/express/partner/commissions'
      },
      // مرحله 9: پورسانت‌ها - آمار
      {
        element: '[data-tour="commissions-stats"]',
        title: 'آمار پورسانت‌ها',
        description: 'در این بخش می‌توانید کل درآمد، درآمد در انتظار و تعداد فروش‌های موفق را مشاهده کنید.',
        position: 'bottom',
        page: 'commissions'
      },
      // مرحله 10: لیست پورسانت‌ها
      {
        element: '[data-tour="commission-item"]',
        title: 'لیست پورسانت‌ها',
        description: 'تمام پورسانت‌های شما در اینجا نمایش داده می‌شود. وضعیت هر پورسانت (در انتظار، تأیید شده، پرداخت شده) مشخص است.',
        position: 'top',
        page: 'commissions',
        action: 'navigate',
        actionMessage: 'حالا به منوی پایین بروید و روی "یادداشت‌ها" کلیک کنید. بعد از رفتن به صفحه یادداشت‌ها، تور ادامه می‌یابد.',
        nextUrl: '/express/partner/notes'
      },
      // مرحله 11: یادداشت‌ها - هدر
      {
        element: '[data-tour="notes-header"]',
        title: 'یادداشت‌های خصوصی 📝',
        description: 'در این صفحه می‌توانید یادداشت‌های شخصی خود را ثبت و مدیریت کنید. این یادداشت‌ها فقط برای شما قابل مشاهده است.',
        position: 'bottom',
        page: 'notes'
      },
      // مرحله 12: دکمه افزودن یادداشت
      {
        element: '[data-tour="notes-add-button"]',
        title: 'افزودن یادداشت',
        description: 'برای افزودن یادداشت جدید، روی دکمه + در هدر کلیک کنید. سپس می‌توانید یادداشت خود را بنویسید و ذخیره کنید.',
        position: 'bottom',
        page: 'notes',
        action: 'auto-navigate',
        actionMessage: 'در حال نمایش فرم افزودن یادداشت...'
      },
      // مرحله 13: فیلد ثبت یادداشت
      {
        element: '[data-tour="notes-input"]',
        title: 'ثبت یادداشت',
        description: 'یادداشت خود را در این فیلد بنویسید. می‌توانید هر چیزی که می‌خواهید به خاطر بسپارید را اینجا ثبت کنید.',
        position: 'bottom',
        page: 'notes',
        waitForElement: true
      },
      // مرحله 14: یادداشت‌های شما
      {
        element: '[data-tour="notes-grid"]',
        title: 'یادداشت‌های شما',
        description: 'تمام یادداشت‌های شما در اینجا نمایش داده می‌شود. می‌توانید هر یادداشت را با hover کردن و کلیک روی آیکون سطل زباله حذف کنید.',
        position: 'top',
        page: 'notes',
        action: 'navigate',
        actionMessage: 'حالا به منوی پایین بروید و روی "من" کلیک کنید. بعد از رفتن به صفحه پروفایل، تور ادامه می‌یابد.',
        nextUrl: '/express/partner/profile'
      },
      // مرحله 13: پروفایل
      {
        element: '[data-tour="profile-section"]',
        title: 'پروفایل شما 👤',
        description: 'در این بخش اطلاعات حساب کاربری شما شامل نام، شماره تماس و نقش نمایش داده می‌شود. همچنین می‌توانید از اینجا از حساب خود خارج شوید.',
        position: 'bottom',
        page: 'profile'
      },
      // مرحله 14: لینک یادداشت‌ها در پروفایل
      {
        element: '[data-tour="notes-link"]',
        title: 'یادداشت‌های خصوصی 📝',
        description: 'یادداشت‌های شخصی خود را اینجا ثبت و مدیریت کنید. این یادداشت‌ها فقط برای شما قابل مشاهده است و می‌توانید از آن‌ها برای یادآوری اطلاعات مهم استفاده کنید.',
        position: 'top',
        page: 'profile'
      },
      // مرحله 15: اعلان‌ها
      {
        element: '[data-tour="notifications-link"]',
        title: 'اعلان‌ها 🔔',
        description: 'تمام اعلان‌های مهم مانند تایید پورسانت، فایل‌های جدید و پیام‌های سیستم در این بخش نمایش داده می‌شود. تعداد اعلان‌های خوانده نشده روی آیکون نمایش داده می‌شود.',
        position: 'top',
        page: 'profile'
      },
      // مرحله 16: فروشنده‌های برتر
      {
        element: '[data-tour="top-sellers-link"]',
        title: 'فروشنده‌های برتر 🏆',
        description: 'رتبه‌بندی همکاران برتر را مشاهده کنید و ببینید چه کسانی بیشترین فروش را داشته‌اند. این می‌تواند انگیزه‌بخش باشد!',
        position: 'top',
        page: 'profile'
      },
      // مرحله 17: پشتیبانی (پروفایل)
      {
        element: '[data-tour="support-link"]',
        title: 'تماس با پشتیبانی 💬',
        description: 'برای تماس با پشتیبانی، مطالعهٔ راهنما و اجرای مجدد تور، روی این گزینه بزنید تا وارد صفحه پشتیبانی شوید.',
        position: 'top',
        page: 'profile',
        action: 'navigate',
        actionMessage: 'روی «تماس با پشتیبانی» بزنید. تور در همان صفحه ادامه می‌یابد.',
        nextUrl: '/express/partner/support'
      },
      // مرحله 18: راهنما (صفحه پشتیبانی)
      {
        element: '[data-tour="help-link"]',
        title: 'راهنمای استفاده 📚',
        description: 'راهنمای کامل استفاده از پلتفرم را از اینجا مطالعه کنید.',
        position: 'top',
        page: 'support',
        waitForElement: true
      },
      // مرحله 19: اجرای مجدد تور (صفحه پشتیبانی)
      {
        element: '[data-tour="restart-tour"]',
        title: 'اجرای مجدد تور راهنما 🔄',
        description: 'برای مشاهدهٔ دوبارهٔ آموزش‌ها از ابتدا، روی این دکمه بزنید.',
        position: 'top',
        page: 'support',
        waitForElement: true
      },
      // مرحله 20: منوی پایین
      {
        element: '[data-tour="bottom-nav"]',
        title: 'منوی پایین 📱',
        description: 'از این منو می‌توانید به بخش‌های اصلی پنل دسترسی سریع داشته باشید: فایل‌ها، پورسانت‌ها، اعلان‌ها و پروفایل.',
        position: 'top',
        page: 'support'
      }
    ];
  }

  createOverlay() {
    if (this.overlay || this.tooltip) {
      this.removeTourUiImmediate();
    }

    // ایجاد overlay
    this.overlay = document.createElement('div');
    this.overlay.className = 'onboarding-overlay';
    this.overlay.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(0, 0, 0, 0.5);
      z-index: 9998;
      pointer-events: none;
      transition: opacity 0.3s;
    `;
    document.body.appendChild(this.overlay);

    // ایجاد tooltip (موبایل محور)
    const isMobile = window.innerWidth < 640;
    this.tooltip = document.createElement('div');
    this.tooltip.className = 'onboarding-tooltip';
    this.tooltip.style.cssText = `
      position: fixed;
      z-index: 9999;
      background: white;
      border: 1px solid #e5e7eb;
      border-radius: ${isMobile ? '16px' : '12px'};
      padding: ${isMobile ? '20px 16px' : '16px'};
      max-width: ${isMobile ? 'calc(100vw - 16px)' : '320px'};
      min-width: ${isMobile ? 'calc(100vw - 16px)' : '280px'};
      width: ${isMobile ? 'calc(100vw - 16px)' : 'auto'};
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.15), 0 4px 6px -2px rgba(0, 0, 0, 0.1);
      font-family: 'Vazirmatn', sans-serif;
      direction: rtl;
      opacity: 0;
      transform: scale(0.95);
      transition: opacity 0.3s ease, transform 0.3s ease;
      animation: tooltipFadeIn 0.3s ease forwards;
    `;
    // اضافه کردن کلاس dark mode
    if (document.documentElement.classList.contains('dark')) {
      this.tooltip.style.background = '#111827';
      this.tooltip.style.borderColor = '#374151';
      this.tooltip.style.color = '#f9fafb';
    }
    
    // اضافه کردن استایل انیمیشن (موبایل محور)
    if (!document.getElementById('onboarding-animations')) {
      const style = document.createElement('style');
      style.id = 'onboarding-animations';
      style.textContent = `
        @keyframes tooltipFadeIn {
          from {
            opacity: 0;
            transform: scale(0.95) translateY(-10px);
          }
          to {
            opacity: 1;
            transform: scale(1) translateY(0);
          }
        }
        @keyframes highlightPulse {
          0%, 100% {
            outline-color: #2563EB;
          }
          50% {
            outline-color: #3B82F6;
          }
        }
        .onboarding-highlight {
          animation: highlightPulse 2s ease-in-out infinite;
        }
        .onboarding-overlay {
          pointer-events: none !important;
        }
        .onboarding-tooltip,
        .onboarding-tooltip * {
          pointer-events: none !important;
        }
        .onboarding-tooltip button {
          pointer-events: auto !important;
          touch-action: manipulation;
        }
        /* استایل‌های موبایل */
        @media (max-width: 640px) {
          .onboarding-tooltip {
            max-width: calc(100vw - 16px) !important;
            min-width: calc(100vw - 16px) !important;
            width: calc(100vw - 16px) !important;
            padding: 20px 16px !important;
            border-radius: 16px !important;
            font-size: 14px !important;
          }
          .onboarding-tooltip h3 {
            font-size: 16px !important;
            margin-bottom: 8px !important;
          }
          .onboarding-tooltip p {
            font-size: 14px !important;
            line-height: 1.6 !important;
          }
          .onboarding-tooltip button {
            padding: 12px 16px !important;
            font-size: 14px !important;
            min-height: 44px !important;
            touch-action: manipulation;
          }
          .onboarding-tooltip .fa-times {
            font-size: 16px !important;
          }
          .onboarding-overlay {
            background: rgba(0, 0, 0, 0.6) !important;
          }
        }
        /* بهبود touch targets برای موبایل */
        @media (pointer: coarse) {
          .onboarding-tooltip button {
            min-height: 44px;
            min-width: 44px;
          }
        }
      `;
      document.head.appendChild(style);
    }
    
    document.body.appendChild(this.tooltip);
  }

  showStep(index) {
    if (index >= this.tourData.length) {
      this.completeTour();
      return;
    }

    this.currentStep = index;
    const step = this.tourData[index];
    
    // بررسی اینکه آیا در صفحه صحیح هستیم
    if (step.page) {
      const currentPath = window.location.pathname;
      const isOnCorrectPage = this.isOnCorrectPage(currentPath, step.page);

      if (!isOnCorrectPage) {
        const expectedPath = this.getExpectedPath(step.page);
        if (!expectedPath) {
          console.warn(`Tour step ${index + 1}: skipping — page unavailable (${step.page})`);
          setTimeout(() => this.showStep(index + 1), 300);
          return;
        }
        sessionStorage.setItem('vinor_tour_step', index.toString());
        sessionStorage.setItem('vinor_tour_data', JSON.stringify(this.tourData));
        window.location.href = expectedPath;
        return;
      }
    }

    this.clearTourSession();

    let element = this.findTourElement(step.element);
    
    // اگر المنت پیدا نشد و waitForElement فعال است، منتظر بمان
    if (!element && step.waitForElement) {
      let attempts = 0;
      const maxAttempts = 20; // 10 ثانیه
      const checkElement = setInterval(() => {
        element = this.findTourElement(step.element);
        attempts++;
        if (element || attempts >= maxAttempts) {
          clearInterval(checkElement);
          if (!element) {
            console.warn(`Tour step ${index + 1}: Element not found after waiting: ${step.element}`);
            this.showStep(index + 1);
            return;
          }
          this.renderStep(index, element, step);
        }
      }, 500);
      return;
    }

    if (!element) {
      console.warn(`Tour step ${index + 1}: Element not found: ${step.element}`);
      setTimeout(() => this.showStep(index + 1), 300);
      return;
    }

    this.renderStep(index, element, step);
  }

  renderStep(index, element, step) {
    const rect = element.getBoundingClientRect();
    const position = this.calculatePosition(rect, step.position);

    // تنظیم tooltip
    let actionHtml = '';
    if (step.action === 'click') {
      actionHtml = `<div class="mt-2 p-2 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded text-xs text-blue-700 dark:text-blue-300">${step.actionMessage || 'لطفاً روی المنت کلیک کنید.'}</div>`;
    } else if (step.action === 'navigate') {
      actionHtml = `<div class="mt-2 p-2 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded text-xs text-blue-700 dark:text-blue-300">${step.actionMessage || 'لطفاً به صفحه بعدی بروید.'}</div>`;
    } else if (step.action === 'auto-navigate') {
      actionHtml = `<div class="mt-2 p-2 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded text-xs text-blue-700 dark:text-blue-300">${step.actionMessage || 'در حال انتقال...'}</div>`;
    }

    // بررسی dark mode
    const isDark = document.documentElement.classList.contains('dark');
    const bgColor = isDark ? '#111827' : 'white';
    const textColor = isDark ? '#f9fafb' : '#111827';
    const borderColor = isDark ? '#374151' : '#e5e7eb';
    const textSecondary = isDark ? '#d1d5db' : '#4b5563';

    this.tooltip.style.background = bgColor;
    this.tooltip.style.borderColor = borderColor;
    this.tooltip.style.color = textColor;

    const isMobile = window.innerWidth < 640;
    const closeButtonSize = isMobile ? 'w-9 h-9' : 'w-7 h-7';
    const closeButtonIconSize = isMobile ? 'text-sm' : 'text-xs';
    const titleSize = isMobile ? 'text-lg' : 'text-base';
    const descSize = isMobile ? 'text-base' : 'text-sm';
    const buttonPadding = isMobile ? 'px-4 py-2.5' : 'px-3 py-1.5';
    const buttonTextSize = isMobile ? 'text-sm' : 'text-xs';
    const counterTextSize = isMobile ? 'text-sm' : 'text-xs';
    
    this.tooltip.innerHTML = `
      <div class="relative">
        <!-- دکمه بستن -->
        <button onclick="window.onboardingTour.closeTour()" 
                class="absolute top-0 left-0 ${closeButtonSize} flex items-center justify-center rounded-full hover:bg-gray-100 dark:hover:bg-gray-800 active:bg-gray-200 dark:active:bg-gray-700 transition-colors touch-manipulation"
                style="color: ${textSecondary}"
                aria-label="بستن تور">
          <i class="fas fa-times ${closeButtonIconSize}"></i>
        </button>
        <div class="mb-4 ${isMobile ? 'pr-10' : 'pr-7'}">
          <h3 class="${titleSize} font-semibold mb-2" style="color: ${textColor}">${step.title}</h3>
          <p class="${descSize} leading-relaxed" style="color: ${textSecondary}">${step.description}</p>
          ${actionHtml}
        </div>
      </div>
      <div class="flex items-center justify-between gap-2 pt-3" style="border-top: 1px solid ${borderColor}">
        <div class="${counterTextSize} font-medium" style="color: ${textSecondary}">
          ${index + 1} از ${this.tourData.length}
        </div>
        <div class="flex items-center gap-2 flex-wrap">
          ${index > 0 ? `
            <button onclick="window.onboardingTour.prevStep()" class="${buttonPadding} ${buttonTextSize} font-medium border rounded-lg hover:opacity-80 active:opacity-60 transition touch-manipulation" style="border-color: ${borderColor}; color: ${textColor}; min-height: ${isMobile ? '44px' : 'auto'}">
              قبلی
            </button>
          ` : ''}
          ${step.action === 'navigate' && step.nextUrl ? `
            <button onclick="window.onboardingTour.navigateToNext('${step.nextUrl}')" class="${buttonPadding} ${buttonTextSize} font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 active:bg-blue-800 transition touch-manipulation" style="min-height: ${isMobile ? '44px' : 'auto'}">
              برو به صفحه بعدی
            </button>
          ` : step.action === 'auto-navigate' ? `
            <button onclick="window.onboardingTour.autoNavigateToNext(${index})" class="${buttonPadding} ${buttonTextSize} font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 active:bg-blue-800 transition touch-manipulation" style="min-height: ${isMobile ? '44px' : 'auto'}">
              ادامه
            </button>
          ` : step.action === 'click' ? `
            <button onclick="window.onboardingTour.nextStep()" class="${buttonPadding} ${buttonTextSize} font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 active:bg-blue-800 transition opacity-50 cursor-not-allowed touch-manipulation" disabled style="min-height: ${isMobile ? '44px' : 'auto'}">
              روی المنت کلیک کنید
            </button>
          ` : `
            <button onclick="window.onboardingTour.nextStep()" class="${buttonPadding} ${buttonTextSize} font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 active:bg-blue-800 transition touch-manipulation" style="min-height: ${isMobile ? '44px' : 'auto'}">
              ${index === this.tourData.length - 1 ? 'پایان' : 'بعدی'}
            </button>
          `}
        </div>
      </div>
    `;

    this.tooltip.style.left = position.left + 'px';
    this.tooltip.style.top = position.top + 'px';
    if (position.width) {
      this.tooltip.style.width = position.width + 'px';
      this.tooltip.style.maxWidth = position.width + 'px';
    }

    // ایجاد highlight برای المنت
    this.highlightElement(element);

    // اگر action === 'click' است، listener برای کلیک اضافه کن
    if (step.action === 'click') {
      const clickHandler = (e) => {
        e.preventDefault();
        e.stopPropagation();
        
        // حذف listener
        element.removeEventListener('click', clickHandler);
        
        // اگر المنت یک لینک یا دکمه است، href را بگیر
        let targetUrl = null;
        if (element.tagName === 'A') {
          targetUrl = element.getAttribute('href');
        } else if (element.getAttribute('data-href')) {
          targetUrl = element.getAttribute('data-href');
        } else {
          // اگر المنت یک کارت است، href را از data-href بگیر
          const cardLink = element.closest('[data-href]');
          if (cardLink) {
            targetUrl = cardLink.getAttribute('data-href');
          }
        }

        if (targetUrl) {
          this.persistTourNavigation(index + 1, targetUrl);
        } else {
          // اگر المنت یک دکمه است که فرم را نمایش می‌دهد (مثل دکمه + در notes)
          // بررسی اینکه آیا المنت onclick دارد که فرم را نمایش می‌دهد
          const onclickAttr = element.getAttribute('onclick');
          if (onclickAttr && (onclickAttr.includes('addNoteForm') || onclickAttr.includes('classList.toggle'))) {
            // اجرای onclick
            try {
              eval(onclickAttr);
            } catch (e) {
              console.warn('Error executing onclick:', e);
            }
            // ذخیره وضعیت تور و منتظر ماندن برای نمایش فرم
            sessionStorage.setItem('vinor_tour_step', (index + 1).toString());
            sessionStorage.setItem('vinor_tour_data', JSON.stringify(this.tourData));
            // بعد از 300ms به مرحله بعد برو
            setTimeout(() => {
              this.showStep(index + 1);
            }, 300);
          } else {
            // اگر href پیدا نشد، به مرحله بعد برو
            setTimeout(() => {
              this.nextStep();
            }, 500);
          }
        }
      };
      
      // اضافه کردن listener
      element.addEventListener('click', clickHandler, { once: true });
      
      // اگر المنت یک کارت است، روی کل کارت listener اضافه کن
      const card = element.closest('[data-href]');
      if (card && card !== element) {
        card.addEventListener('click', clickHandler, { once: true });
      }
    }
  }

  getExpectedPath(page) {
    if (page === 'land_detail') {
      const landUrl = sessionStorage.getItem('vinor_tour_land_url');
      return landUrl && this.isLandDetailPath(landUrl) ? landUrl : null;
    }

    const paths = {
      'dashboard': '/express/partner/dashboard',
      'commissions': '/express/partner/commissions',
      'notes': '/express/partner/notes',
      'profile': '/express/partner/profile',
      'support': '/express/partner/support'
    };
    return paths[page] || '/express/partner/dashboard';
  }

  isOnCorrectPage(currentPath, expectedPage) {
    if (expectedPage === 'dashboard') {
      return this.isDashboardPath(currentPath);
    } else if (expectedPage === 'land_detail') {
      return this.isLandDetailPath(currentPath);
    } else if (expectedPage === 'commissions') {
      return /\/commissions\/?$/.test(currentPath);
    } else if (expectedPage === 'notes') {
      return /\/notes\/?$/.test(currentPath);
    } else if (expectedPage === 'profile') {
      return currentPath.includes('/profile') && !currentPath.includes('/profile/');
    } else if (expectedPage === 'support') {
      return currentPath.includes('/support');
    }
    return true;
  }

  navigateToNext(url) {
    this.persistTourNavigation(this.currentStep + 1, url);
  }

  autoNavigateToNext(stepIndex) {
    const step = this.tourData[stepIndex];
    const element = this.findTourElement(step.element);
    
    if (!element) {
      // اگر المنت پیدا نشد، به مرحله بعد برو
      this.nextStep();
      return;
    }

    // اگر المنت یک دکمه است که فرم را نمایش می‌دهد (مثل دکمه + در notes)
    const onclickAttr = element.getAttribute('onclick');
    if (onclickAttr && (onclickAttr.includes('addNoteForm') || onclickAttr.includes('classList.toggle'))) {
      // اجرای onclick برای نمایش فرم
      try {
        eval(onclickAttr);
      } catch (e) {
        console.warn('Error executing onclick:', e);
      }
      // بعد از 300ms به مرحله بعد برو (منتظر نمایش فرم)
      setTimeout(() => {
        this.showStep(stepIndex + 1);
      }, 300);
      return;
    }

    // تلاش برای پیدا کردن URL از المنت
    let targetUrl = null;
    
    // اگر المنت خودش data-href دارد
    if (element.getAttribute('data-href')) {
      targetUrl = element.getAttribute('data-href');
    } else {
      // اگر المنت یک کارت است، href را از data-href بگیر
      const cardLink = element.closest('[data-href]');
      if (cardLink) {
        targetUrl = cardLink.getAttribute('data-href');
      }
    }

    if (targetUrl) {
      this.persistTourNavigation(stepIndex + 1, targetUrl);
    } else {
      console.warn('Could not find URL for auto-navigate, proceeding to next step');
      this.nextStep();
    }
  }

  calculatePosition(rect, position) {
    // محاسبه اندازه tooltip بر اساس محتوا (موبایل محور)
    const isMobile = window.innerWidth < 640;
    const tooltipMaxWidth = isMobile ? window.innerWidth - 16 : Math.min(320, window.innerWidth - 32);
    const tooltipMinWidth = isMobile ? window.innerWidth - 16 : 280;
    const tooltipWidth = Math.max(tooltipMinWidth, tooltipMaxWidth);
    const tooltipHeight = isMobile ? Math.min(300, window.innerHeight * 0.5) : Math.min(250, window.innerHeight * 0.4);
    const padding = isMobile ? 8 : 16;
    const actualPadding = padding;
    let left, top;

    switch (position) {
      case 'top':
        if (isMobile) {
          // در موبایل tooltip را در وسط صفحه قرار بده
          left = actualPadding;
          top = Math.max(actualPadding, (window.innerHeight - tooltipHeight) / 2);
        } else {
          left = rect.left + (rect.width / 2) - (tooltipWidth / 2);
          top = rect.top - tooltipHeight - actualPadding;
          // اگر فضا برای بالا نیست، به پایین ببر
          if (top < actualPadding) {
            top = rect.bottom + actualPadding;
          }
        }
        break;
      case 'bottom':
        if (isMobile) {
          // در موبایل tooltip را در پایین صفحه قرار بده
          left = actualPadding;
          top = window.innerHeight - tooltipHeight - actualPadding - 80; // فاصله از bottom nav
        } else {
          left = rect.left + (rect.width / 2) - (tooltipWidth / 2);
          top = rect.bottom + actualPadding;
          // اگر فضا برای پایین نیست، به بالا ببر
          if (top + tooltipHeight > window.innerHeight - actualPadding) {
            top = rect.top - tooltipHeight - actualPadding;
          }
        }
        break;
      case 'left':
        left = rect.left - tooltipWidth - actualPadding;
        top = rect.top + (rect.height / 2) - (tooltipHeight / 2);
        // اگر فضا برای چپ نیست، به راست ببر
        if (left < actualPadding) {
          left = rect.right + actualPadding;
        }
        break;
      case 'right':
        left = rect.right + actualPadding;
        top = rect.top + (rect.height / 2) - (tooltipHeight / 2);
        // اگر فضا برای راست نیست، به چپ ببر
        if (left + tooltipWidth > window.innerWidth - actualPadding) {
          left = rect.left - tooltipWidth - actualPadding;
        }
        break;
      default:
        left = rect.left + (rect.width / 2) - (tooltipWidth / 2);
        top = rect.bottom + actualPadding;
    }

    // اطمینان از اینکه tooltip در viewport است (با در نظر گیری responsive)
    if (left < actualPadding) left = actualPadding;
    if (left + tooltipWidth > window.innerWidth - actualPadding) {
      left = window.innerWidth - tooltipWidth - actualPadding;
    }
    if (top < actualPadding) top = actualPadding;
    if (top + tooltipHeight > window.innerHeight - actualPadding) {
      top = window.innerHeight - tooltipHeight - actualPadding;
    }

    return { left, top, width: tooltipWidth };
  }

  highlightElement(element) {
    // حذف highlight قبلی
    document.querySelectorAll('.onboarding-highlight').forEach(el => {
      el.classList.remove('onboarding-highlight');
      el.style.outline = '';
      el.style.outlineOffset = '';
    });

    // اضافه کردن highlight با انیمیشن
    element.classList.add('onboarding-highlight');
    element.style.outline = '3px solid #2563EB';
    element.style.outlineOffset = '4px';
    element.style.zIndex = '9999';
    element.style.position = 'relative';
    element.style.transition = 'outline-color 0.3s ease';
    
    // اضافه کردن backdrop برای بهتر دیده شدن
    if (!document.querySelector('.onboarding-backdrop')) {
      const backdrop = document.createElement('div');
      backdrop.className = 'onboarding-backdrop';
      backdrop.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(37, 99, 235, 0.1);
        z-index: 9997;
        pointer-events: none;
        opacity: 0;
        transition: opacity 0.3s ease;
      `;
      document.body.appendChild(backdrop);
      setTimeout(() => {
        backdrop.style.opacity = '1';
      }, 10);
    }

    // اسکرول به المنت (بهینه برای موبایل)
    const isMobile = window.innerWidth < 640;
    if (isMobile) {
      // در موبایل با offset بیشتر اسکرول کن تا tooltip دیده شود
      const elementTop = element.getBoundingClientRect().top + window.pageYOffset;
      const offset = 100; // فاصله از بالا برای نمایش tooltip
      window.scrollTo({
        top: elementTop - offset,
        behavior: 'smooth'
      });
    } else {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }

  nextStep() {
    // حذف highlight
    document.querySelectorAll('.onboarding-highlight').forEach(el => {
      el.classList.remove('onboarding-highlight');
      el.style.outline = '';
      el.style.outlineOffset = '';
      el.style.zIndex = '';
      el.style.position = '';
      el.style.transition = '';
    });

    this.showStep(this.currentStep + 1);
  }

  prevStep() {
    // حذف highlight
    document.querySelectorAll('.onboarding-highlight').forEach(el => {
      el.classList.remove('onboarding-highlight');
      el.style.outline = '';
      el.style.outlineOffset = '';
      el.style.zIndex = '';
      el.style.position = '';
      el.style.transition = '';
    });

    if (this.currentStep > 0) {
      this.showStep(this.currentStep - 1);
    }
  }

  removeTourUiImmediate() {
    const backdrop = document.querySelector('.onboarding-backdrop');
    if (backdrop) backdrop.remove();

    if (this.overlay) {
      this.overlay.remove();
      this.overlay = null;
    }
    if (this.tooltip) {
      this.tooltip.remove();
      this.tooltip = null;
    }

    document.querySelectorAll('.onboarding-highlight').forEach(el => {
      el.classList.remove('onboarding-highlight');
      el.style.outline = '';
      el.style.outlineOffset = '';
      el.style.zIndex = '';
      el.style.position = '';
      el.style.transition = '';
    });
  }

  closeTour() {
    this.completeTour();
  }

  completeTour() {
    const backdrop = document.querySelector('.onboarding-backdrop');
    if (backdrop) {
      backdrop.style.opacity = '0';
      setTimeout(() => backdrop.remove(), 300);
    }

    if (this.overlay) {
      this.overlay.style.opacity = '0';
      const overlay = this.overlay;
      setTimeout(() => overlay.remove(), 300);
      this.overlay = null;
    }
    if (this.tooltip) {
      this.tooltip.style.opacity = '0';
      this.tooltip.style.transform = 'scale(0.95) translateY(-10px)';
      const tooltip = this.tooltip;
      setTimeout(() => tooltip.remove(), 300);
      this.tooltip = null;
    }

    document.querySelectorAll('.onboarding-highlight').forEach(el => {
      el.classList.remove('onboarding-highlight');
      el.style.outline = '';
      el.style.outlineOffset = '';
      el.style.zIndex = '';
      el.style.position = '';
      el.style.transition = '';
    });

    sessionStorage.removeItem('vinor_tour_land_url');
    this.clearTourSession();
    this.isActive = false;
  }

  restartTour() {
    if (this.isActive) {
      this.removeTourUiImmediate();
      this.isActive = false;
    }

    sessionStorage.removeItem('vinor_tour_land_url');

    if (!this.isDashboardPath()) {
      sessionStorage.setItem('vinor_start_full_tour', 'true');
      window.location.href = '/express/partner/dashboard';
    } else {
      setTimeout(() => this.startTour(true), 200);
    }
  }
}

// ایجاد instance جهانی
window.onboardingTour = new OnboardingTour();

// بارگذاری اسکریپت — تور فقط با درخواست کاربر (صفحه پشتیبانی) شروع می‌شود
if (document.readyState === 'complete') {
  window.onboardingTour.init();
} else {
  window.addEventListener('load', () => window.onboardingTour.init(), { once: true });
}

