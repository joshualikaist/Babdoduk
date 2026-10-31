# -*- coding: utf-8 -*-
"""Instagram and reader-tip sources on the food hub and the home calendar (owner decision 2026-10-31).

Synthetic snapshots on a routed host: an Instagram post is credited and linked only through its
canonical permalink, a reader tip is credited and never linked, and mail stays as it was.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HOST = "source-origin.invalid"
NOW = "2026-10-01T09:00:00+09:00"
POST = "https://www.instagram.com/p/DfCRCEskwzw/"
PLACE = {"name": "창의학습관(E11) 101호", "building": "창의학습관(E11)", "room": "101호"}


def ev(event_id, hour, sources, **extra):
    event = {"id": event_id, "title": f"{event_id} 간식", "summary": "", "startAt": f"2026-10-01T{hour}:00:00+09:00",
             "endAt": f"2026-10-01T{hour}:50:00+09:00", "dateText": "", "timeText": "", "location": dict(PLACE),
             "food": {"provided": "true", "type": "snack", "description": "간식"}, "organizer": "", "eligibility": "",
             "registration": {"required": "unknown", "deadline": None, "url": ""}, "confidence": 0.95, "sources": sources}
    event.update(extra)
    return event


INSTAGRAM = ev("insta", "12", [{"type": "dooray", "name": "Dooray"}, {"type": "instagram", "name": "Instagram", "url": POST}])
FORGED = ev("forged", "13", [{"type": "instagram", "name": "Instagram", "url": POST + "?igsh=abc"}])
TIP = ev("tip", "14", [{"type": "tip", "name": "제보", "url": "https://example.com/tip"}])
MAIL = ev("mail", "15", [{"type": "dooray", "name": "Dooray"}])
LIVE = {"schemaVersion": 1, "generatedAt": "2026-10-01T08:30:00+09:00", "timezone": "Asia/Seoul", "count": 4,
        "events": [INSTAGRAM, FORGED, TIP, MAIL]}
PAST = dict(ev("past", "12", [{"type": "instagram", "name": "Instagram", "url": POST}]),
            startAt="2026-09-29T12:00:00+09:00", endAt="2026-09-29T13:00:00+09:00")
for key in ("registration", "confidence"):
    PAST.pop(key)
ARCHIVE = {"schemaVersion": 1, "generatedAt": "2026-10-01T08:30:00+09:00", "windowDays": 30, "events": [PAST]}


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        chrome = pw.chromium.launch(channel="chrome", headless=True)
        yield chrome
        chrome.close()


def open_page(browser, page_name, lang="ko"):
    context = browser.new_context(viewport={"width": 390, "height": 844}, timezone_id="Asia/Seoul",
                                  service_workers="block")
    context.add_init_script(f"localStorage.setItem('babdoduk-lang', '{lang}');")

    def handle(route):
        url = urlparse(route.request.url)
        if url.hostname != HOST:
            return route.abort()          # no live public feed, CDN or deployment
        path = unquote(url.path).lstrip("/")
        if path == "data/ggongbab/latest.json":
            return route.fulfill(json=LIVE)
        if path == "data/ggongbab/archive/index.json":
            return route.fulfill(json=ARCHIVE)
        if path.startswith("data/"):
            return route.fulfill(status=404, body="")
        file = (ROOT / path).resolve()
        if file.is_file() and ROOT in file.parents:
            return route.fulfill(path=str(file))
        return route.fulfill(status=404, body="")

    context.route("**/*", handle)
    page = context.new_page()
    page.clock.set_fixed_time(NOW)
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"https://{HOST}/{page_name}", wait_until="domcontentloaded")
    return context, page, errors


def card(page, event_id):
    return page.locator(f'.gg-card[data-id="{event_id}"]')


def links(locator):
    return locator.locator("a.gg-btn").evaluate_all("els => els.map(a => [a.getAttribute('href'), a.target, a.rel, a.textContent])")


def test_the_food_hub_credits_and_links_an_instagram_post_and_credits_a_tip(browser):
    context, page, errors = open_page(browser, "ggongbab.html")
    card(page, "insta").wait_for()
    assert card(page, "insta").locator(".gg-source").inner_text() == "인스타그램"
    assert links(card(page, "insta")) == [[POST, "_blank", "noopener", "인스타그램 원문"]]
    assert card(page, "forged").locator(".gg-source").inner_text() == "인스타그램"
    assert links(card(page, "forged")) == []                       # not the canonical permalink: no link
    assert card(page, "tip").locator(".gg-source").inner_text() == "제보"
    assert links(card(page, "tip")) == []                          # a tip never links, whatever the data holds
    assert card(page, "mail").locator(".gg-source").inner_text() == "KAIST 메일"
    past = page.locator('.gg-past[data-past-id="past"]')
    past.wait_for()
    assert past.locator("a").get_attribute("href") == POST
    assert past.locator("a").inner_text().startswith("당시 인스타그램 게시물 보기")
    assert "인스타그램" in past.locator(".gg-past-note").inner_text()

    page.locator("#langToggle").click()
    assert card(page, "insta").locator(".gg-source").inner_text() == "Instagram"
    assert card(page, "insta").locator("a.gg-btn").inner_text() == "Instagram post"
    assert card(page, "tip").locator(".gg-source").inner_text() == "Reader tip"
    assert past.locator("a").inner_text().startswith("View the Instagram post")
    assert not errors
    context.close()


def test_the_home_calendar_links_the_post_and_names_a_tip(browser):
    context, page, errors = open_page(browser, "index.html")
    page.wait_for_function("document.getElementById('homeCal').dataset.state !== 'loading'")
    for button in page.locator(".hc-ev-btn").all():
        button.click()
    day = page.locator("#homeCalDay")
    hrefs = day.locator("a").evaluate_all("els => els.map(a => [a.getAttribute('href'), a.rel])")
    assert hrefs == [[POST, "noopener"]]                           # the post only: no forged link, no tip link
    assert day.locator("a.hc-ev-link").inner_text().startswith("인스타그램 원문 보기")
    sources = day.locator(".hc-ev-src").all_inner_texts()
    assert sources == ["출처 · 인스타그램", "출처 · 제보", "출처 · KAIST 메일"]
    page.locator("#langToggle").click()
    assert day.locator("a.hc-ev-link").inner_text().startswith("View on Instagram")
    assert "Reader tip" in " ".join(day.locator(".hc-ev-src").all_inner_texts())
    assert not errors
    context.close()
