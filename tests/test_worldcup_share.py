"""The world cup's sharing (owner 2026-10-14, docs/WORLDCUP_SHARE.md): a 1080x1920 Instagram story card
drawn when the winner is decided, 스토리 이미지 저장 and 공유하기, the friend challenge link and the
link preview of worldcup.html and event.html. scripts/check_site_ui.py worldcup_share plays it in a browser."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "js/worldcup.js").read_text(encoding="utf-8")
OG_IMAGE = ROOT / "images/worldcup/og-worldcup.jpg"
OG_URL = "https://babdoduk.vercel.app/images/worldcup/og-worldcup.jpg"


def head(name):
    return (ROOT / name).read_text(encoding="utf-8").split("</head>", 1)[0]


def jpeg_size(data: bytes) -> tuple[int, int]:
    assert data[:2] == b"\xff\xd8", "not a JPEG"
    i = 2
    while i < len(data):
        marker, length = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2):
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        i += 2 + length
    raise AssertionError("no frame header")


def test_the_story_card_is_9_16_at_1080_by_1920_only():
    assert "var STORY = { w: 1080, h: 1920, top: 250, bottom: 1670, pad: 72 };" in SCRIPT
    assert "canvas.width = STORY.w;" in SCRIPT and "canvas.height = STORY.h;" in SCRIPT
    assert "1350" not in SCRIPT                                   # the old 4:5 image is gone, no feed size
    # Drawn when the result shows, exported as a PNG, and only from same-origin photos (an untainted canvas).
    assert "prepareStory();" in SCRIPT.split("function renderResult(", 1)[1].split("function renderHistory(", 1)[0]
    assert "canvas.toBlob(resolve, 'image/png')" in SCRIPT and "img.crossOrigin" not in SCRIPT
    assert "img.src = photo.image;" in SCRIPT.split("function loadPhoto(", 1)[1].split("function rounded(", 1)[0]
    # Important content ends inside Instagram's safe zone; only decoration and the credits go below it.
    assert "Math.min(540, 882 - nameH - subH - chipsH)" in SCRIPT


def test_save_and_share_buttons_and_their_copy():
    html = (ROOT / "worldcup.html").read_text(encoding="utf-8")
    result = html.split('id="wcResult"', 1)[1].split("</section>", 1)[0]
    assert '<span data-i18n="wc.save">스토리 이미지 저장</span>' in result and '<span data-i18n="wc.share">공유하기</span>' in result
    assert 'data-i18n="wc.shareHint">인스타 스토리: 공유하기 → Instagram → 스토리</p>' in result
    assert 'class="wc-toast" id="wcShareStatus" role="status" aria-live="polite"' in result
    ko = json.loads((ROOT / "i18n/ko.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "i18n/en.json").read_text(encoding="utf-8"))
    assert (ko["wc.saved"], ko["wc.copied"]) == ("저장했어요", "링크를 복사했어요")
    for key in ("wc.save", "wc.share", "wc.shareHint", "wc.friend", "wc.story.won", "wc.story.cta", "wc.story.final",
                "wc.story.semi", "wc.story.credit", "wc.story.alt", "wc.preparing", "wc.friendCta"):
        assert ko[key] and en[key], key
    assert "{dish}" in ko["wc.friend"] and "{dish}" in en["wc.friend"]
    # Web Share Level 2 with the file, the text and the link on a phone; the text and the link when files
    # cannot be shared; a copied link on a computer.
    share = SCRIPT.split("  function share() {", 1)[1].split("\n  }\n", 1)[0]
    assert "if (!touchDevice() || !navigator.share) { copyLink(url); return; }" in share
    assert "if (canShareFile(file)) data.files = [file];" in share and "{ title: document.title, text: text, url: url }" in share
    assert "navigator.canShare({ files: [file] })" in SCRIPT


def test_the_friend_link_is_this_host_and_never_starts_a_game():
    assert "location.origin + location.pathname + '?from=' + encodeURIComponent(result.id) + '&cat=' + encodeURIComponent(result.category)" in SCRIPT
    challenge = SCRIPT.split("  function challenge() {", 1)[1].split("\n  }\n", 1)[0]
    assert "set.indexOf(id) >= 0 ? id : null" in challenge                      # a dish of the pool, or nothing
    assert "CATEGORIES.indexOf(cat) >= 0 && poolOf(cat).length >= size ? cat : null" in challenge
    assert "go" not in challenge                                                 # only go=1 starts a game
    banner = SCRIPT.split("  function renderFriend() {", 1)[1].split("\n  }\n", 1)[0]
    assert "img.hidden = locked() || !photo;" in banner                          # no photo request before the launch


def test_link_previews_show_the_world_cup_teaser():
    data = OG_IMAGE.read_bytes()
    assert len(data) < 300_000, len(data)
    assert jpeg_size(data) == (1200, 630)
    for name, url in (("worldcup.html", "https://babdoduk.vercel.app/worldcup.html"),
                      ("event.html", "https://babdoduk.vercel.app/event.html")):
        text = head(name)
        og = dict(re.findall(r'<meta property="(og:[\w:]+)" content="([^"]*)"', text))
        tw = dict(re.findall(r'<meta name="(twitter:[\w:]+)" content="([^"]*)"', text))
        assert og["og:title"] and og["og:description"] and og["og:url"] == url, name
        assert og["og:image"] == OG_URL and (og["og:image:width"], og["og:image:height"]) == ("1200", "630"), name
        assert og["og:image:alt"] and f'<link rel="image_src" href="{OG_URL}" />' in text, name
        assert tw == {"twitter:card": "summary_large_image", "twitter:title": og["og:title"],
                      "twitter:description": og["og:description"], "twitter:image": OG_URL}, name


def test_no_kakao_sdk_and_no_external_script():
    for name in ("worldcup.html", "event.html"):
        html = (ROOT / name).read_text(encoding="utf-8")
        for src in re.findall(r'<script[^>]*\bsrc="([^"]+)"', html):
            assert not re.match(r"(https?:)?//", src), (name, src)
        assert not re.search(r"kakao[\w./-]*\.js", html, re.I) and "Kakao.init" not in html, name
    assert "createElement('script')" not in SCRIPT and 'createElement("script")' not in SCRIPT
    assert "kakaocdn" not in SCRIPT and "developers.kakao.com" not in SCRIPT
    # The documented hook for later: a feed template, used once the owner adds the SDK and an app key.
    assert "window.BabdodukWorldcupShare = {" in SCRIPT and "objectType: 'feed'" in SCRIPT
    assert "Kakao" in (ROOT / "docs/WORLDCUP_SHARE.md").read_text(encoding="utf-8")
