/**
 * Onboarding Tour System - Divar Style
 * سیستم تور راهنمای کاربران به سبک دیوار
 *
 * نسخه ۳: هم‌تراز با IA فعلی (خانه / AI / پروفایل)
 * تورهای قدیمی با سلکتورهای مرده (help / routine / files) پاک می‌شوند.
 */

class OnboardingTour {
  constructor() {
    this.currentStep = 0;
    this.tour = null;
    this.overlay = null;
    this.tooltip = null;
    this.isActive = false;
    this.tourData = [];
    this.tourVersion = OnboardingTour.TOUR_VERSION;
  }

  static TOUR_VERSION = '2026-07-ia-v4';
  static FILES_PATH = '/express/partner/home';
  static HOME_PATH = '/express/partner/home';
  static DEAD_SELECTORS = [
    'routine-link',
    'help-link',
    'support-link',
    'notifications-link',
  ];

  // Avoid showing the tour on authentication pages (login/OTP)
  isAuthPage() {
    const path = window.location.pathname || '';
    return (
      path.includes('/login') ||
      path.includes('/verify') ||
      path.includes('/auth/')
    );
  }

  isHomePath(path = window.location.pathname) {
    const p = (path || '').replace(/\/+$/, '') || '/';
    return p === '/express/partner/home' || p === '/express/partner' || p === '/express/partner/';
  }

  /** صفحه لیست فایل‌ها (قالب dashboard.html روی /files) */
  isFilesPath(path = window.location.pathname) {
    return false;
  }

  /** سازگاری با نام قدیمی */
  isDashboardPath(path = window.location.pathname) {
    return this.isHomePath(path);
  }

  isLandDetailPath(path = window.location.pathname) {
    return path.includes('/lands/') || path.includes('/land_detail');
  }

  tourDataLooksStale(tourData) {
    if (!Array.isArray(tourData) || !tourData.length) return true;
    const blob = JSON.stringify(tourData);
    if (blob.includes('/express/partner/dashboard') && !blob.includes('/express/partner/home')) {
      return true;
    }
    return OnboardingTour.DEAD_SELECTORS.some((key) => blob.includes(`data-tour="${key}"`) || blob.includes(`"${key}"`));
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
    sessionStorage.setItem('vinor_tour_version', this.tourVersion);
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
    sessionStorage.removeItem('vinor_tour_version');
  }

  init() {
    if (this.isAuthPage()) return;

    const storedVersion = sessionStorage.getItem('vinor_tour_version');
    const tourStep = sessionStorage.getItem('vinor_tour_step');
    const tourDataRaw = sessionStorage.getItem('vinor_tour_data');

    // تورهای قدیمی / گیرکرده را بی‌صدا پاک کن
    if (tourStep !== null || tourDataRaw || sessionStorage.getItem('vinor_start_full_tour')) {
      if (storedVersion !== this.tourVersion) {
        this.clearTourSession();
        sessionStorage.removeItem('vinor_tour_land_url');
        return;
      }
    }

    if (tourStep !== null && tourDataRaw) {
      let parsed;
      try {
        parsed = JSON.parse(tourDataRaw);
      } catch (e) {
        console.warn('Invalid tour session data, clearing.', e);
        this.clearTourSession();
        return;
      }
      if (this.tourDataLooksStale(parsed)) {
        this.clearTourSession();
        sessionStorage.removeItem('vinor_tour_land_url');
        return;
      }
      this.tourData = parsed;
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
      if (!this.isHomePath()) {
        sessionStorage.setItem('vinor_tour_version', this.tourVersion);
        sessionStorage.setItem('vinor_start_full_tour', 'true');
        window.location.href = OnboardingTour.HOME_PATH;
        return;
      }
    } else {
      const path = window.location.pathname;
      if (this.isHomePath(path)) {
        this.tourData = this.getHomeTour();
      } else if (this.isFilesPath(path)) {
        this.tourData = this.getFilesTour();
      } else if (this.isLandDetailPath(path)) {
        this.tourData = this.getLandDetailTour();
      } else if (path.includes('/commissions')) {
        this.tourData = this.getCommissionsTour();
      } else if (path.includes('/profile/edit') || path.includes('/home')) {
        this.tourData = path.includes('/profile/edit') ? this.getProfileTour() : this.getHomeTour();
      } else {
        this.tourData = this.getHomeTour();
      }
    }

    if (this.tourData.length === 0) {
      this.isActive = false;
      return;
    }

    sessionStorage.setItem('vinor_tour_version', this.tourVersion);
    this.createOverlay();
    this.showStep(0);
  }

  getHomeTour() {
    return [
      {
        element: '[data-tour="home-menu"]',
        title: 'منوی پروفایل',
        description: 'از اینجا کیف پول و تنظیمات حساب را باز کنید.',
        position: 'bottom'
      },
      {
        element: '[data-tour="home-urgent"]',
        title: 'کار بعدی',
        description: 'مهم‌ترین اقدام امروز شما اینجاست — یک اولویت، بدون شلوغی.',
        position: 'bottom'
      },
      {
        element: '[data-tour="home-suggest"]',
        title: 'پیشنهاد امروز',
        description: 'فایل‌های پیشنهادی برای شروع فروش. برای همه فایل‌ها به بخش فایل‌ها بروید.',
        position: 'top'
      },
      {
        element: '[data-tour="ai-fab"]',
        title: 'Vinor AI',
        description: 'سوال بپرسید یا پیام‌های رسمی وینور (پستچی) را از اینجا دنبال کنید.',
        position: 'top'
      },
      {
        element: '[data-tour="bottom-nav"]',
        title: 'منوی پایین',
        description: 'جابه‌جایی سریع بین داشبورد خانه و پروفایل.',
        position: 'top'
      }
    ];
  }

  getFilesTour() {
    return [
      {
        element: '[data-tour="dashboard-header"]',
        title: 'فایل‌های شما',
        description: 'لیست فایل‌های اختصاص‌داده‌شده. جستجو و فیلتر برای پیدا کردن سریع‌تر.',
        position: 'bottom'
      },
      {
        element: '[data-tour="dashboard-filters"]',
        title: 'فیلترهای سریع',
        description: 'با چیپ‌ها و دسته‌ها آگهی‌ها را محدود کنید؛ مثلاً استخر، جنگلی، زمین و باغ یا فوری.',
        position: 'bottom'
      },
      {
        element: '[data-tour="land-card"]',
        title: 'کارت فایل',
        description: 'هر کارت یک فایل است. روی کارت بزنید تا جزئیات، تماس و معامله را ببینید.',
        position: 'top'
      },
      {
        element: '[data-tour="bottom-nav"]',
        title: 'منوی پایین',
        description: 'بازگشت به داشبورد خانه یا رفتن به پروفایل.',
        position: 'top'
      }
    ];
  }

  /** سازگاری با کد قدیمی */
  getDashboardTour() {
    return this.getFilesTour();
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
        description: 'اگر مشتری پیدا کردید، روی این دکمه کلیک کنید تا وضعیت فایل را به «در حال معامله» تغییر دهید.',
        position: 'top'
      },
      {
        element: '[data-tour="share-btn"]',
        title: 'اشتراک‌گذاری',
        description: 'می‌توانید لینک فایل را با مشتریان به اشتراک بگذارید.',
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
        description: 'تمام پورسانت‌های شما در اینجا نمایش داده می‌شود. وضعیت هر پورسانت مشخص است.',
        position: 'top'
      }
    ];
  }

  getProfileTour() {
    return [
      {
        element: '[data-tour="profile-section"]',
        title: 'پروفایل شما',
        description: 'اطلاعات حساب، نام و شماره تماس. از اینجا می‌توانید از حساب خارج شوید.',
        position: 'bottom'
      },
      {
        element: '[data-tour="commissions-link"]',
        title: 'کیف پول',
        description: 'موجودی قابل برداشت و تراکنش‌های پورسانت را اینجا ببینید.',
        position: 'top'
      },
      {
        element: '[data-tour="bottom-nav"]',
        title: 'منوی پایین',
        description: 'بازگشت سریع به داشبورد خانه.',
        position: 'top'
      }
    ];
  }

  getFullTour() {
    return [
      {
        element: '[data-tour="home-menu"]',
        title: 'خوش آمدید',
        description: 'داشبورد خانه نقطه شروع شماست. منوی بالا کیف پول و تنظیمات را باز می‌کند.',
        position: 'bottom',
        page: 'home'
      },
      {
        element: '[data-tour="home-urgent"]',
        title: 'کار بعدی',
        description: 'هر روز یک اولویت اصلی اینجا نشان داده می‌شود.',
        position: 'bottom',
        page: 'home'
      },
      {
        element: '[data-tour="ai-fab"]',
        title: 'Vinor AI و پستچی',
        description: 'از دستیار بپرسید؛ پیام‌های رسمی وینور هم در گفتگوی پستچی داخل AI هستند.',
        position: 'top',
        page: 'home'
      },
      {
        element: '[data-tour="home-journey"]',
        title: 'کارت سفر فروش',
        description: 'فایل پیشنهادی و مرحله فروش را اینجا می‌بینید؛ با دکمه پایین مستقیم اقدام کنید.',
        position: 'bottom',
        page: 'home'
      },
      {
        element: '[data-tour="land-image"]',
        title: 'تصویر فایل',
        description: 'تصویر اصلی و گالری فایل.',
        position: 'bottom',
        page: 'land_detail',
        waitForElement: true
      },
      {
        element: '[data-tour="land-info"]',
        title: 'اطلاعات فایل',
        description: 'قیمت، موقعیت، کمیسیون و جزئیات مهم.',
        position: 'top',
        page: 'land_detail'
      },
      {
        element: '[data-tour="transaction-btn"]',
        title: 'دکمه معامله',
        description: 'وقتی مشتری پیدا کردید، وضعیت را به «در حال معامله» تغییر دهید.',
        position: 'top',
        page: 'land_detail'
      },
      {
        element: '[data-tour="share-btn"]',
        title: 'اشتراک‌گذاری',
        description: 'لینک فایل را برای مشتری بفرستید.',
        position: 'top',
        page: 'land_detail'
      },
      {
        element: '[data-tour="contact-btn"]',
        title: 'تماس',
        description: 'تماس با مالک فایل.',
        position: 'top',
        page: 'land_detail',
        action: 'navigate',
        actionMessage: 'حالا کیف پول (پورسانت) را می‌بینیم.',
        nextUrl: '/express/partner/commissions'
      },
      {
        element: '[data-tour="commissions-stats"]',
        title: 'آمار پورسانت‌ها',
        description: 'درآمد کل، در انتظار و فروش‌های موفق.',
        position: 'bottom',
        page: 'commissions'
      },
      {
        element: '[data-tour="commission-item"]',
        title: 'لیست پورسانت‌ها',
        description: 'وضعیت هر پورسانت اینجا مشخص است.',
        position: 'top',
        page: 'commissions',
        action: 'navigate',
        actionMessage: 'در پایان به پروفایل می‌رویم.',
        nextUrl: '/express/partner/home?menu=1'
      },
      {
        element: '[data-tour="profile-section"]',
        title: 'پروفایل شما',
        description: 'اطلاعات حساب و خروج از اینجا.',
        position: 'bottom',
        page: 'profile'
      },
      {
        element: '[data-tour="commissions-link"]',
        title: 'کیف پول',
        description: 'دسترسی سریع به موجودی و تراکنش‌ها از منوی پروفایل.',
        position: 'top',
        page: 'profile'
      },
      {
        element: '[data-tour="bottom-nav"]',
        title: 'منوی پایین',
        description: 'داشبورد خانه و پروفایل — همیشه در دسترس.',
        position: 'top',
        page: 'profile'
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
        sessionStorage.setItem('vinor_tour_version', this.tourVersion);
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
      home: OnboardingTour.HOME_PATH,
      files: OnboardingTour.FILES_PATH,
      dashboard: OnboardingTour.FILES_PATH,
      commissions: '/express/partner/commissions',
      profile: '/express/partner/home?menu=1'
    };
    return paths[page] || OnboardingTour.HOME_PATH;
  }

  isOnCorrectPage(currentPath, expectedPage) {
    if (expectedPage === 'home') {
      return this.isHomePath(currentPath);
    } else if (expectedPage === 'files' || expectedPage === 'dashboard') {
      return this.isFilesPath(currentPath);
    } else if (expectedPage === 'land_detail') {
      return this.isLandDetailPath(currentPath);
    } else if (expectedPage === 'commissions') {
      return /\/commissions\/?$/.test(currentPath);
    } else if (expectedPage === 'notes') {
      return /\/notes\/?$/.test(currentPath);
    } else if (expectedPage === 'profile') {
      // منوی پروفایل روی خانه (کشوی راست)
      return this.isHomePath(currentPath) || currentPath.includes('/profile/edit');
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
    this.clearTourSession();

    if (!this.isHomePath()) {
      sessionStorage.setItem('vinor_tour_version', this.tourVersion);
      sessionStorage.setItem('vinor_start_full_tour', 'true');
      window.location.href = OnboardingTour.HOME_PATH;
    } else {
      setTimeout(() => this.startTour(true), 200);
    }
  }
}

// ایجاد instance جهانی
window.onboardingTour = new OnboardingTour();

// بارگذاری اسکریپت — تور فقط با درخواست صریح (restartTour / startTour) یا ادامهٔ سشن معتبر
if (document.readyState === 'complete') {
  window.onboardingTour.init();
} else {
  window.addEventListener('load', () => window.onboardingTour.init(), { once: true });
}

