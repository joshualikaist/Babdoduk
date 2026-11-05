/* What every page shares: the language switch, the scroll progress bar, the home link that scrolls
   to the top on the home page, and the "more" menu of the navigation.

   The page's translation table comes first, as window.BABDODUK_STR = { ko: {...}, en: {...} },
   written into each page by scripts/sync_site_chrome.py from i18n/ko.json and i18n/en.json (plus
   data/content/), and this script runs right after it, before the page's own scripts. Changing
   the language rewrites every [data-i18n] text, [data-i18n-html] fragment, [data-i18n-aria-key]
   label and [data-i18n-alt] text, the document title, and then announces `babdoduk-lang` on the
   document for the page's own scripts. */
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
  // The lab's own pages answer 404 on every host but babdoduk-lab (vercel.json), so the public pages
  // carry no link to them. On babdoduk-lab, and only there, the "more" menu of every page lists them
  // too, so the lab is reachable from its home page (owner 2026-11-01). The pages' HTML is the same on
  // both branches; the lab pages already carry these links (scripts/sync_site_chrome.py LAB_LINKS).
  var LAB_HOST = 'babdoduk-lab.vercel.app';
  var LAB_LINKS = [['lab.html', 'nav.lab', '실험실'], ['lab-ggongbab.html', 'nav.labFeed', '꽁밥 실험'],
                   ['cardnews.html', 'nav.labCards', '카드뉴스']];
  var morePanel = document.getElementById('navMorePanel');
  if (location.hostname === LAB_HOST && morePanel && !morePanel.querySelector('a[href="lab.html"]')) {
    LAB_LINKS.forEach(function (link) {
      var a = document.createElement('a');
      a.className = 'nav-mega-link';
      a.href = link[0];
      a.setAttribute('data-i18n', link[1]);
      a.textContent = link[2];
      morePanel.appendChild(a);
    });
  }

  var saved = 'ko';
  try { saved = localStorage.getItem('babdoduk-lang') || 'ko'; } catch (e) {}
  applyLang(saved === 'en' ? 'en' : 'ko');

  // Phones: the menu button opens the links as a panel from the left, under the bar (css/site.css).
  // A dimmed backdrop, Escape, a link or focus leaving the panel closes it; Escape and the backdrop
  // give focus back to the button.
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

  // Scroll progress.
  var bar = document.getElementById('scrollProgressBar');
  var wrap = bar && bar.parentElement;
  // At most once a frame however many scroll events arrive; the attribute only when its number changes.
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

  // On the home page the wordmark links to "#": it scrolls back to the top.
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

  // The navigation's "more" menu: one open at a time, closed by a click elsewhere or Escape.
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
