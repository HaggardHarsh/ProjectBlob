"""Real Chromium exercises dates, dropdowns and dynamic lookup results offline."""

import asyncio
import json

import pytest
import pytest_asyncio

from blob.privacy.controls import PrivacyControls
from blob.skills.builtin.browser import BrowserSkill


FORM = """<!doctype html><title>Availability fixture</title>
<form id="lookup"><label>Journey date<input type="date" name="date"></label>
<label>Class<select name="class"><option value="SL">Sleeper</option><option value="3A">Third AC</option></select></label>
<button>Check availability</button></form><p id="result">No lookup submitted.</p>
<label>Account password<input type="password" name="password"></label>
<button>Buy now</button>
<script>document.querySelector('#lookup').addEventListener('submit', e => {
 e.preventDefault(); const f=new FormData(e.target);
 document.querySelector('#result').innerText='Fixture availability for '+f.get('date')+' '+f.get('class')+': AVAILABLE 7';
});</script>"""


@pytest_asyncio.fixture
async def browser():
    pytest.importorskip("playwright.async_api")
    skill = BrowserSkill()
    try:
        await skill._start()
        await skill._context.route("https://lookup.example/**", lambda route: route.fulfill(
            status=200, content_type="text/html", body=FORM))
        yield skill
    finally:
        await skill.close()


def ref(result, name):
    assert result.success, result.output
    return next(item["ref"] for item in json.loads(result.output)["elements"] if item["name"] == name)


@pytest.mark.asyncio
async def test_real_browser_fills_date_selects_class_and_reads_dynamic_result(browser):
    result = await browser.async_execute({"action": "open", "url": "https://lookup.example/"})
    old_ref = ref(result, "Journey date")
    result = await browser.async_execute({"action": "fill", "ref": old_ref, "text": "2026-11-01"})
    stale = await browser.async_execute({"action": "fill", "ref": old_ref, "text": "2026-11-02"})
    assert not stale.success and "stale" in stale.output
    result = await browser.async_execute({"action": "select", "ref": ref(result, "Class"), "text": "Third AC"})
    result = await browser.async_execute({"action": "click", "ref": ref(result, "Check availability")})
    data = json.loads(result.output)
    assert result.success and data["url"] == "https://lookup.example/"
    assert "2026-11-01 3A: AVAILABLE 7" in data["text"] and data["checked_at"]
    assert data["untrusted_web_content"]


@pytest.mark.asyncio
async def test_browser_blocks_password_fields_and_transactions(browser):
    result = await browser.async_execute({"action": "open", "url": "https://lookup.example/"})
    password = await browser.async_execute({"action": "fill", "ref": ref(result, "Account password"), "text": "secret"})
    assert not password.success
    buy = await browser.async_execute({"action": "click", "ref": ref(result, "Buy now")})
    assert not buy.success and "transactions" in buy.output
    assert await browser._page.locator('[type=password]').input_value() == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"paused": True}, {"cloud_enabled": False}, {"disabled_skills": ["browser"]}])
async def test_idle_browser_closes_on_privacy_changes(browser, tmp_path, changes):
    browser.controls = PrivacyControls(tmp_path / "private/privacy.json")
    browser.controls.update(cloud_enabled=True)
    await browser.async_execute({"action": "open", "url": "https://lookup.example/"})
    browser.controls.update(**changes)
    for _ in range(30):
        if browser._page is None:
            break
        await asyncio.sleep(0.1)
    assert browser._page is None and not browser._refs
