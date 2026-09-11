# -*- coding: utf-8 -*-
"""Rebuild index.html from food.html (UTF-8). Run: python rebuild_index.py"""
from pathlib import Path

from patch_site import insert_nav_foodlog, patch_popup

ROOT = Path(__file__).resolve().parent
FOOD = ROOT / "food.html"
INDEX = ROOT / "index.html"

# 프로필 + 캐러셀 (인스타 → 지도 → 유튜브 → 카카오)
LANDING_BLOCK = """
  <section class="profile profile--hero">
    <p class="hero-eyebrow" data-i18n="hero.eyebrow">KAIST FOOD &amp; COMMUNITY</p>
    <div class="badge-row">
      <span class="chip chip--tagline">🍚 = World = 🌎</span>
    </div>
    <div class="avatar">
      <div class="avatar-inner">
        <!-- 인스타 프로필 사진 (images/profile-instagram.jpg) — 만료 시 프로필 페이지 og:image 로 갱신 가능 -->
        <img id="profileAvatarImg" src="images/profile-instagram.jpg" alt="밥도둑 Babdoduk 프로필" width="76" height="76" loading="eager" decoding="async" />
      </div>
    </div>
    <h1 class="title" id="profileTitle" data-i18n-html="profile.titleHtml">밥도둑 <span class="title-en">Babdoduk</span></h1>
    <p class="subtitle" data-i18n="profile.subtitle">카이스트 기계과 먹방1티어 학생의 먹방일기</p>
    <div class="hero-actions">
      <a class="btn btn-primary" href="#heroCarousel" data-i18n="hero.ctaExplore">둘러보기</a>
      <a class="btn btn-secondary" href="https://www.instagram.com/babdodukms/" target="_blank" rel="noopener" data-i18n="hero.ctaInsta">Instagram</a>
    </div>
  </section>

  <!--
    사진 넣기: 각 .slide-media 의 style 에
    background-image: url('images/인스타.jpg'), linear-gradient(...);
    처럼 url()을 맨 앞에 두면 사진이 우선됩니다.
  -->
  <section class="hero-carousel" id="heroCarousel" aria-label="밥도둑 주요 링크">
    <div class="carousel-viewport" id="carouselViewport" tabindex="0" aria-roledescription="carousel">
      <div class="carousel-track" id="carouselTrack">
        <a class="carousel-slide" href="https://www.instagram.com/babdodukms/" target="_blank" rel="noopener" data-slide="0">
          <div class="slide-media slide-media--insta" style="background-image: url('images/history-t1.png');" role="img" aria-hidden="true"></div>
          <div class="slide-copy">
            <span class="slide-eyebrow">Instagram</span>
            <h2 class="slide-title" data-i18n="slide.insta.title">밥도둑 인스타그램</h2>
            <p class="slide-desc" data-i18n="slide.insta.desc">@babdodukms · 일상과 레시피를 만나 보세요</p>
          </div>
        </a>
        <a class="carousel-slide" href="https://naver.me/5NeqUPzI" target="_blank" rel="noopener" data-slide="1">
          <div class="slide-media" style="background-image: url('images/carousel-naver-map.png');" role="img" aria-hidden="true"></div>
          <div class="slide-copy">
            <span class="slide-eyebrow">Map</span>
            <h2 class="slide-title" data-i18n="slide.map.title">밥도둑의 맛집 지도</h2>
            <p class="slide-desc" data-i18n="slide.map.desc">네이버 지도에서 정리한 맛집 리스트</p>
          </div>
        </a>
        <a class="carousel-slide" href="#" data-slide="2" id="slideYoutube">
          <div class="slide-media" style="background-image: url('images/carousel-youtube.png');" role="img" aria-hidden="true"></div>
          <div class="slide-copy">
            <span class="slide-eyebrow">YouTube</span>
            <h2 class="slide-title" data-i18n="slide.yt.title">유튜브</h2>
            <p class="slide-desc" data-i18n="slide.yt.desc">영상으로 밥도둑을 만나 보세요</p>
          </div>
        </a>
        <a class="carousel-slide" href="#" data-slide="3" id="slideKakao">
          <div class="slide-media" style="background-image: url('images/carousel-kakao.png');" role="img" aria-hidden="true"></div>
          <div class="slide-copy">
            <span class="slide-eyebrow">KakaoTalk</span>
            <h2 class="slide-title" data-i18n="slide.kakao.title">카카오톡 문의 채널</h2>
            <p class="slide-desc" data-i18n="slide.kakao.desc">채널에서 편하게 문의해 주세요</p>
          </div>
        </a>
      </div>
    </div>
    <div class="carousel-dots" role="tablist" data-i18n-aria-key="carousel.tablist" aria-label="슬라이드 위치">
      <button type="button" class="carousel-dot is-active" data-index="0" data-i18n-aria-key="carousel.dot1" aria-label="슬라이드 1"></button>
      <button type="button" class="carousel-dot" data-index="1" data-i18n-aria-key="carousel.dot2" aria-label="슬라이드 2"></button>
      <button type="button" class="carousel-dot" data-index="2" data-i18n-aria-key="carousel.dot3" aria-label="슬라이드 3"></button>
      <button type="button" class="carousel-dot" data-index="3" data-i18n-aria-key="carousel.dot4" aria-label="슬라이드 4"></button>
    </div>
  </section>

"""


def strip_food_script(s: str) -> str:
    sig = "      function parseISODate(iso) {"
    ix = s.find(sig)
    if ix == -1:
        return s
    script_open = s.rfind("  <script>", 0, ix)
    script_close = s.find("  </script>", ix)
    if script_open == -1 or script_close == -1:
        return s
    script_close += len("  </script>")
    return s[:script_open] + s[script_close:]


def ensure_carousel_autoplay(s: str) -> str:
    if "carouselHover" in s:
        return s
    needle = """        window.addEventListener('resize', function () {
          layout();
        });

        var sn = slideNodes();"""
    insert = """        window.addEventListener('resize', function () {
          layout();
        });

        var carouselHover = false;
        carouselViewport.addEventListener('pointerenter', function () {
          carouselHover = true;
        });
        carouselViewport.addEventListener('pointerleave', function () {
          carouselHover = false;
        });
        setInterval(function () {
          if (document.hidden || carouselHover || animLock) return;
          goNext();
        }, 10000);

        var sn = slideNodes();"""
    if needle not in s:
        return s
    return s.replace(needle, insert, 1)


def ensure_nav_home_handler(s: str) -> str:
    old = """      var navHome = document.getElementById('navHome');
      if (navHome) {
        navHome.addEventListener('click', function (e) {
          e.preventDefault();
          window.scrollTo({ top: 0, behavior: 'smooth' });
        });
      }"""
    new = """      var navHome = document.getElementById('navHome');
      if (navHome) {
        navHome.addEventListener('click', function (e) {
          if (navHome.getAttribute('href') === '#') {
            e.preventDefault();
            window.scrollTo({ top: 0, behavior: 'smooth' });
          }
        });
      }"""
    if old in s:
        s = s.replace(old, new, 1)
    return s


def ensure_design_css(s: str) -> str:
    """Keep the post-redesign stylesheets even if food.html inline CSS is copied."""
    if 'href="css/site.css"' not in s:
        s = s.replace(
            "</head>",
            '  <link rel="stylesheet" href="css/site.css" />\n'
            '  <link rel="stylesheet" href="css/app.css" />\n</head>',
            1,
        )
    if 'href="css/index.css"' not in s:
        if 'href="css/app.css" />' in s:
            s = s.replace(
                'href="css/app.css" />',
                'href="css/app.css" />\n  <link rel="stylesheet" href="css/index.css" />',
                1,
            )
        else:
            s = s.replace(
                "</head>",
                '  <link rel="stylesheet" href="css/index.css" />\n</head>',
                1,
            )
    return s


def main() -> None:
    s = FOOD.read_text(encoding="utf-8")

    # 메인에서 가계부 카드/배너용 CSS 블록 제거
    m_start = s.find("    /* ── 먹방 가계부")
    m_end = s.find("    /* ── 가로 캐러셀")
    if m_start == -1 or m_end == -1:
        raise SystemExit("CSS markers not found in food.html")
    # 메인에서는 가계부 카드/배너 제거 → 캐러셀 CSS만 유지
    s = s[:m_start] + s[m_end:]

    # 랜딩(프로필+캐러셀) 삽입
    marker = '  <div class="food-tracker-wrap">'
    if marker not in s:
        raise SystemExit("food-tracker-wrap not found")
    if "profile profile--hero" not in s:
        s = s.replace(marker, LANDING_BLOCK.strip() + "\n\n" + marker, 1)

    # 가계부 UI 섹션 제거(진입은 food.html·내비) — 푸터(site-footer)부터 유지
    f0 = s.find('  <div class="food-tracker-wrap">')
    f1 = s.find('  <footer class="site-footer"', f0)
    if f0 == -1 or f1 == -1:
        raise SystemExit("food-tracker-wrap or site-footer not found")
    s = s[:f0] + s[f1:]

    s = insert_nav_foodlog(s)
    s = s.replace(
        '<a href="index.html" id="navHome"',
        '<a href="#" id="navHome"',
        1,
    )

    s = strip_food_script(s)
    s = ensure_carousel_autoplay(s)
    s = ensure_nav_home_handler(s)
    s = patch_popup(s)
    s = ensure_design_css(s)

    s = s.replace(
        "      navJumpToSlide(document.getElementById('navMegaKakao'), 1);\n      navJumpToSlide(document.getElementById('navMegaYoutube'), 0);",
        "      navJumpToSlide(document.getElementById('navMegaKakao'), 3);\n      navJumpToSlide(document.getElementById('navMegaYoutube'), 2);",
        1,
    )

    # 브라우저·프록시가 charset 을 놓칠 때 보조 (UTF-8 명시)
    if 'http-equiv="Content-Type"' not in s:
        s = s.replace(
            '  <meta charset="UTF-8" />\n',
            '  <meta charset="UTF-8" />\n'
            '  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />\n',
            1,
        )

    raw = s.encode("utf-8")
    if "밥도둑".encode("utf-8") not in raw:
        raise SystemExit("출력에 한글(밥도둑)이 없습니다. food.html 인코딩을 확인하세요.")
    INDEX.write_bytes(raw)
    print("Wrote", INDEX, "UTF-8 bytes:", len(raw))


if __name__ == "__main__":
    main()
