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
  var saved = 'ko';
  try { saved = localStorage.getItem('babdoduk-lang') || 'ko'; } catch (e) {}
  applyLang(saved === 'en' ? 'en' : 'ko');
  var langBtnEl = document.getElementById('langToggle');
  if (langBtnEl) {
    langBtnEl.addEventListener('click', function () {
      applyLang(window.babdodukGetLang() === 'ko' ? 'en' : 'ko');
    });
  }

  // Scroll progress.
  var bar = document.getElementById('scrollProgressBar');
  var wrap = bar && bar.parentElement;
  function onScroll() {
    if (!bar) return;
    var el = document.documentElement;
    var total = el.scrollHeight - el.clientHeight;
    var pct = total <= 0 ? 0 : (el.scrollTop / total) * 100;
    bar.style.width = pct + '%';
    if (wrap) wrap.setAttribute('aria-valuenow', String(Math.round(pct)));
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll);
  onScroll();

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
