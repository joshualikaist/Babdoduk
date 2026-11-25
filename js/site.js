(function () {
  var STR = window.BABDODUK_STR || { ko: {}, en: {} };

  function applyLang(lang) {
    if (lang !== 'en') lang = 'ko';
    document.documentElement.lang = lang;
    try { localStorage.setItem('babdoduk-lang', lang); } catch (e) {}
    var T = STR[lang] || {};
    if (T.docTitle !== undefined) document.title = T.docTitle;
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      var k = el.getAttribute('data-i18n');
      if (T[k] !== undefined) el.textContent = T[k];
    });
    document.querySelectorAll('[data-i18n-html]').forEach(function (el) {
      var k = el.getAttribute('data-i18n-html');
      if (T[k] !== undefined) el.innerHTML = T[k];
    });
    document.querySelectorAll('[data-i18n-aria-key]').forEach(function (el) {
      var k = el.getAttribute('data-i18n-aria-key');
      if (T[k] !== undefined) el.setAttribute('aria-label', T[k]);
    });
    document.querySelectorAll('[data-i18n-alt]').forEach(function (el) {
      var k = el.getAttribute('data-i18n-alt');
      if (T[k] !== undefined) el.setAttribute('alt', T[k]);
    });
    var navInner = document.getElementById('siteNavInner');
    if (navInner && T['nav.navAria']) navInner.setAttribute('aria-label', T['nav.navAria']);
    var sp = document.getElementById('scrollProgressWrap');
    if (sp && T['a11y.scrollProgress']) sp.setAttribute('aria-label', T['a11y.scrollProgress']);
    try {
      document.dispatchEvent(new CustomEvent('babdoduk-lang', { detail: lang }));
    } catch (e) {}
  }
  window.babdodukApplyLang = applyLang;
  window.babdodukGetLang = function () {
    return document.documentElement.lang === 'en' ? 'en' : 'ko';
  };
  var LAB_HOST = 'babdoduk-lab.vercel.app';
  var LAB_LINKS = [['cardnews.html', 'nav.labCards', '카드뉴스']];
  var morePanel = document.getElementById('navMorePanel');
  if (location.hostname === LAB_HOST && morePanel && !morePanel.querySelector('a[href="cardnews.html"]')) {
    LAB_LINKS.forEach(function (link) {
      var a = document.createElement('a');
      a.className = 'nav-mega-link';
      a.href = link[0];
      a.setAttribute('data-i18n', link[1]);
      a.textContent = link[2];
      morePanel.appendChild(a);
    });
  }
  var insta = document.getElementById('navInstagram');
  if (insta && !document.getElementById('navMy')) {
    var signedIn = false;
    try {
      for (var i = 0; i < localStorage.length; i++) {
        if (/^sb-[a-z0-9]+-auth-token$/.test(localStorage.key(i) || '')) signedIn = true;
      }
    } catch (e) {}
    var my = document.createElement('a');
    my.id = 'navMy';
    my.className = 'site-nav-insta site-nav-my';
    my.href = 'my.html';
    my.setAttribute('data-i18n-aria-key', signedIn ? 'nav.myAria' : 'nav.loginAria');
    my.setAttribute('aria-label', signedIn ? '마이 밥도둑' : '로그인');
    if (/\/my\.html$/.test(location.pathname)) my.setAttribute('aria-current', 'page');
    my.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">' +
      '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5c0-4 3.4-6.5 7.5-6.5s7.5 2.5 7.5 6.5"/></svg>';
    insta.insertAdjacentElement('afterend', my);
  }

  var saved = 'ko';
  try { saved = localStorage.getItem('babdoduk-lang') || 'ko'; } catch (e) {}
  applyLang(saved === 'en' ? 'en' : 'ko');

  function visitInfo(loc, nav) {
    if (!/^(www\.babdodukms\.com|babdoduk\.vercel\.app|babdoduk-lab\.vercel\.app)$/.test(loc.hostname)) return null;
    if (nav.webdriver || nav.globalPrivacyControl || nav.doNotTrack === '1' || window.doNotTrack === '1') return null;
    var off = false;
    try {
      var opt = new URLSearchParams(loc.search).get('nocount');
      if (opt === '1') localStorage.setItem('babdoduk-nocount', '1');
      if (opt === '0') localStorage.removeItem('babdoduk-nocount');
      off = localStorage.getItem('babdoduk-nocount') === '1';
    } catch (e) {}
    if (off) return null;
    var page = (loc.pathname.split('/').pop() || 'index').replace(/\.html$/, '') || 'index';
    if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(page)) return null;
    var ua = nav.userAgent || '';
    var tablet = /iPad|Tablet/i.test(ua) || (/Macintosh/.test(ua) && nav.maxTouchPoints > 1) ||
      (/Android/.test(ua) && !/Mobile/.test(ua));
    var device = tablet ? 'tablet' : /Mobi|iPhone|iPod|Android/i.test(ua) ? 'phone' : 'computer';
    return { page: page, lang: document.documentElement.lang === 'en' ? 'en' : 'ko', device: device };
  }
  window.BabdodukVisit = { info: visitInfo };
  var visit = null;
  try { visit = visitInfo(location, navigator); } catch (e) {}
  if (visit && navigator.sendBeacon) {
    var sendVisit = function () {
      try { navigator.sendBeacon('/api/visit', JSON.stringify(visit)); } catch (e) {}
    };
    if (document.readyState === 'complete') sendVisit();
    else window.addEventListener('load', sendVisit, { once: true });
  }

  var drawerBtn = document.getElementById('navDrawerToggle');
  var drawer = document.getElementById('siteNavLinks');
  if (drawerBtn && drawer) {
    var backdrop = document.createElement('div');
    backdrop.className = 'nav-drawer-backdrop';
    backdrop.hidden = true;
    document.body.appendChild(backdrop);
    var isOpen = function () { return drawerBtn.getAttribute('aria-expanded') === 'true'; };
    var setDrawer = function (open, focusBack) {
      var nav = document.querySelector('.site-nav');
      if (open && nav) {
        var top = Math.round(nav.querySelector('.site-nav-inner').getBoundingClientRect().bottom);
        document.documentElement.style.setProperty('--nav-drawer-top', top + 'px');
      }
      document.documentElement.classList.toggle('nav-drawer-open', open);
      backdrop.hidden = !open;
      drawerBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
      var key = open ? 'nav.menuClose' : 'nav.menuOpen';
      drawerBtn.setAttribute('data-i18n-aria-key', key);
      var label = (STR[window.babdodukGetLang()] || {})[key];
      if (label) drawerBtn.setAttribute('aria-label', label);
      if (open) {
        var first = drawer.querySelector('[aria-current="page"]') || drawer.querySelector('a');
        if (first) first.focus();
      } else if (focusBack) {
        drawerBtn.focus();
      }
    };
    drawerBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      setDrawer(!isOpen());
    });
    backdrop.addEventListener('click', function () { setDrawer(false, true); });
    drawer.addEventListener('click', function (e) {
      if (e.target.closest && e.target.closest('a')) setDrawer(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && isOpen()) setDrawer(false, true);
    });
    document.addEventListener('focusin', function (e) {
      if (isOpen() && !drawer.contains(e.target) && e.target !== drawerBtn) setDrawer(false);
    });
    var phone = window.matchMedia ? window.matchMedia('(max-width: 520px)') : null;
    if (phone && phone.addEventListener) {
      phone.addEventListener('change', function () { if (!phone.matches && isOpen()) setDrawer(false); });
    }
  }
  var langBtnEl = document.getElementById('langToggle');
  if (langBtnEl) {
    langBtnEl.addEventListener('click', function () {
      applyLang(window.babdodukGetLang() === 'ko' ? 'en' : 'ko');
    });
  }

  var bar = document.getElementById('scrollProgressBar');
  var wrap = bar && bar.parentElement;
  var queued = false, shownPct = -1;
  function update() {
    queued = false;
    var el = document.documentElement;
    var total = el.scrollHeight - el.clientHeight;
    var pct = total <= 0 ? 0 : (el.scrollTop / total) * 100;
    bar.style.width = pct + '%';
    var rounded = Math.round(pct);
    if (wrap && rounded !== shownPct) { wrap.setAttribute('aria-valuenow', String(rounded)); shownPct = rounded; }
  }
  function onScroll() {
    if (!bar || queued) return;
    queued = true;
    requestAnimationFrame(update);
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll);
  if (bar) update();

  var navHome = document.getElementById('navHome');
  if (navHome) {
    navHome.addEventListener('click', function (e) {
      if (navHome.getAttribute('href') === '#') {
        e.preventDefault();
        var still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        window.scrollTo({ top: 0, behavior: still ? 'auto' : 'smooth' });
      }
    });
  }

  document.querySelectorAll('[data-mega]').forEach(function (mega) {
    mega.addEventListener('click', function (e) {
      e.stopPropagation();
    });
    var trigger = mega.querySelector('.nav-mega-trigger');
    var panel = mega.querySelector('.nav-mega-panel');
    if (!trigger || !panel) return;
    trigger.addEventListener('click', function (e) {
      e.stopPropagation();
      var willOpen = !mega.classList.contains('is-open');
      document.querySelectorAll('[data-mega].is-open').forEach(function (m) {
        m.classList.remove('is-open');
        var t = m.querySelector('.nav-mega-trigger');
        if (t) t.setAttribute('aria-expanded', 'false');
      });
      if (willOpen) {
        mega.classList.add('is-open');
        trigger.setAttribute('aria-expanded', 'true');
      }
    });
  });
  document.addEventListener('click', function () {
    document.querySelectorAll('[data-mega].is-open').forEach(function (m) {
      m.classList.remove('is-open');
      var t = m.querySelector('.nav-mega-trigger');
      if (t) t.setAttribute('aria-expanded', 'false');
    });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    document.querySelectorAll('[data-mega].is-open').forEach(function (m) {
      m.classList.remove('is-open');
      var t = m.querySelector('.nav-mega-trigger');
      if (t) {
        t.setAttribute('aria-expanded', 'false');
        t.focus();
      }
    });
  });
})();
