# -*- coding: utf-8 -*-
"""UTF-8 safe: nav 먹방 가계부, 본문 배너 제거, 팝업 24시간 스누즈 단일 버튼."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def strip_banner_css(s: str) -> str:
    start = s.find("    /* ── 먹방 가계부 배너")
    if start == -1:
        return s
    end = s.find("    /* ── 가로 캐러셀", start)
    if end == -1:
        return s
    return s[:start] + s[end:]


def strip_banner_html(s: str) -> str:
    a = s.find('  <a class="food-banner"')
    if a == -1:
        return s
    b = s.find('  <div class="container">', a)
    if b == -1:
        return s
    return s[:a] + s[b:]


def insert_nav_foodlog(s: str) -> str:
    if 'data-i18n="nav.foodlog"' in s:
        return s
    old = (
        '      <a class="site-nav-item" href="https://naver.me/5NeqUPzI" target="_blank" '
        'rel="noopener" data-i18n="nav.map">맛집 지도</a>\n'
        '      <a href="#" class="site-nav-item" id="navKakao"'
    )
    new = (
        '      <a class="site-nav-item" href="https://naver.me/5NeqUPzI" target="_blank" '
        'rel="noopener" data-i18n="nav.map">맛집 지도</a>\n'
        '      <a class="site-nav-item" href="food.html" data-i18n="nav.foodlog">먹방 가계부</a>\n'
        '      <a href="#" class="site-nav-item" id="navKakao"'
    )
    if old not in s:
        raise SystemExit("nav insert anchor not found")
    return s.replace(old, new, 1)


POPUP_OLD = """      <div class="popup-actions">
        <button type="button" class="popup-btn primary" id="popupCloseBtn" data-i18n="popup.start">시작하기</button>
      </div>
      <div class="popup-dont-list">
        <label class="popup-dont">
          <input type="checkbox" id="popupDontToday" />
          <span data-i18n="popup.snoozeToday">오늘 다시 보지 않기</span>
        </label>
        <label class="popup-dont">
          <input type="checkbox" id="popupDontPermanent" />
          <span data-i18n="popup.snoozeForever">다시 보지 않기</span>
        </label>
      </div>"""

POPUP_NEW = """      <div class="popup-actions">
        <button type="button" class="popup-btn primary" id="popupCloseBtn" data-i18n="popup.start">시작하기</button>
        <button type="button" class="popup-btn secondary" id="popupSnoozeBtn" data-i18n="popup.snooze24h">하루 동안 보지 않기</button>
      </div>"""

POPUP_JS_OLD = """      function todayKey() {
        var d = new Date();
        return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
      }

      function shouldShowWelcome() {
        try {
          if (localStorage.getItem('babdoduk-welcome-dismissed') === '1') return false;
          if (localStorage.getItem('babdoduk-welcome-snooze') === todayKey()) return false;
        } catch (err) {}
        return true;
      }

      var popup = document.getElementById('welcomePopup');
      var closeBtn = document.getElementById('popupCloseBtn');
      var dontToday = document.getElementById('popupDontToday');
      var dontPermanent = document.getElementById('popupDontPermanent');

      function openPopup() {
        popup.classList.add('is-open');
        popup.setAttribute('aria-hidden', 'false');
      }
      function closePopup() {
        popup.classList.remove('is-open');
        popup.setAttribute('aria-hidden', 'true');
        try {
          if (dontPermanent && dontPermanent.checked) {
            localStorage.setItem('babdoduk-welcome-dismissed', '1');
            localStorage.removeItem('babdoduk-welcome-snooze');
          } else if (dontToday && dontToday.checked) {
            localStorage.setItem('babdoduk-welcome-snooze', todayKey());
          }
        } catch (err) {}
      }

      if (shouldShowWelcome()) {
        requestAnimationFrame(function () { openPopup(); });
      }

      closeBtn.addEventListener('click', closePopup);
      popup.addEventListener('click', function (e) {
        if (e.target === popup) closePopup();
      });

      if (dontPermanent && dontToday) {
        dontPermanent.addEventListener('change', function () {
          if (dontPermanent.checked) dontToday.checked = false;
        });
        dontToday.addEventListener('change', function () {
          if (dontToday.checked) dontPermanent.checked = false;
        });
      }"""

POPUP_JS_NEW = """      function shouldShowWelcome() {
        var path = (location.pathname || '').toLowerCase();
        if (path.indexOf('food.html') !== -1) return false;
        try {
          var until = localStorage.getItem('babdoduk-welcome-snooze-until');
          if (until && Date.now() < parseInt(until, 10)) return false;
        } catch (err) {}
        return true;
      }

      var popup = document.getElementById('welcomePopup');
      var closeBtn = document.getElementById('popupCloseBtn');
      var snoozeBtn = document.getElementById('popupSnoozeBtn');

      function openPopup() {
        popup.classList.add('is-open');
        popup.setAttribute('aria-hidden', 'false');
      }
      function closePopup(withSnooze24h) {
        popup.classList.remove('is-open');
        popup.setAttribute('aria-hidden', 'true');
        try {
          if (withSnooze24h) {
            var until = Date.now() + 24 * 60 * 60 * 1000;
            localStorage.setItem('babdoduk-welcome-snooze-until', String(until));
          }
        } catch (err) {}
      }

      if (shouldShowWelcome()) {
        requestAnimationFrame(function () { openPopup(); });
      }

      if (closeBtn) closeBtn.addEventListener('click', function () { closePopup(false); });
      if (snoozeBtn) snoozeBtn.addEventListener('click', function () { closePopup(true); });
      popup.addEventListener('click', function (e) {
        if (e.target === popup) closePopup(false);
      });"""


def patch_popup(s: str) -> str:
    if POPUP_OLD in s:
        s = s.replace(POPUP_OLD, POPUP_NEW, 1)
    elif 'id="popupSnoozeBtn"' not in s:
        raise SystemExit("welcome popup HTML: expected OLD markup or popupSnoozeBtn")

    if POPUP_JS_OLD in s:
        s = s.replace(POPUP_JS_OLD, POPUP_JS_NEW, 1)
    elif "babdoduk-welcome-snooze-until" not in s:
        raise SystemExit("welcome popup JS: expected OLD script or snooze-until key")

    if (
        "          'nav.map': '맛집 지도',\n          'nav.kakao':"
        in s
        and "'nav.foodlog': '먹방 가계부'" not in s
    ):
        s = s.replace(
            "          'nav.map': '맛집 지도',\n          'nav.kakao':",
            "          'nav.map': '맛집 지도',\n          'nav.foodlog': '먹방 가계부',\n          'nav.kakao':",
            1,
        )
    old_ko_popup = (
        "          'popup.start': '시작하기',\n          'popup.snoozeToday': '오늘 다시 보지 않기',\n"
        "          'popup.snoozeForever': '다시 보지 않기',"
    )
    if old_ko_popup in s:
        s = s.replace(
            old_ko_popup,
            "          'popup.start': '시작하기',\n          'popup.snooze24h': '하루 동안 보지 않기',",
            1,
        )

    if (
        "          'nav.map': 'Food map',\n          'nav.kakao':"
        in s
        and "'nav.foodlog': 'Food log'" not in s
    ):
        s = s.replace(
            "          'nav.map': 'Food map',\n          'nav.kakao':",
            "          'nav.map': 'Food map',\n          'nav.foodlog': 'Food log',\n          'nav.kakao':",
            1,
        )
    old_en_popup = (
        "          'popup.start': 'Start',\n          'popup.snoozeToday': \"Don't show again today\",\n"
        "          'popup.snoozeForever': \"Don't show again\","
    )
    if old_en_popup in s:
        s = s.replace(
            old_en_popup,
            "          'popup.start': 'Start',\n          'popup.snooze24h': \"Don't show for 24 hours\",",
            1,
        )

    _welcome_snooze_only = """      function shouldShowWelcome() {
        try {
          var until = localStorage.getItem('babdoduk-welcome-snooze-until');"""
    if _welcome_snooze_only in s and "path.indexOf('food.html')" not in s:
        s = s.replace(
            _welcome_snooze_only,
            """      function shouldShowWelcome() {
        var path = (location.pathname || '').toLowerCase();
        if (path.indexOf('food.html') !== -1) return false;
        try {
          var until = localStorage.getItem('babdoduk-welcome-snooze-until');""",
            1,
        )
    return s


def patch_index(s: str) -> str:
    s = strip_banner_css(s)
    s = strip_banner_html(s)
    s = insert_nav_foodlog(s)
    s = patch_popup(s)
    return s


def patch_food(s: str) -> str:
    s = insert_nav_foodlog(s)
    s = patch_popup(s)
    return s


def write_utf8(path: Path, text: str) -> None:
    raw = text.encode("utf-8")
    path.write_bytes(raw)


def main() -> None:
    idx = ROOT / "index.html"
    food = ROOT / "food.html"
    sf = patch_food(food.read_text(encoding="utf-8"))
    if "밥도둑".encode("utf-8") not in sf.encode("utf-8"):
        raise SystemExit("food lost hangul")
    write_utf8(food, sf)

    si = patch_index(idx.read_text(encoding="utf-8"))
    if "밥도둑".encode("utf-8") not in si.encode("utf-8"):
        raise SystemExit(
            "index lost hangul (encoding broken). Wrote food.html only; run: python rebuild_index.py"
        )
    write_utf8(idx, si)
    print("Patched index.html + food.html")


if __name__ == "__main__":
    main()
