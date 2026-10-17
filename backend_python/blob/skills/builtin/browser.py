"""Temporary public-web browser for reading and lookup forms, mediated by Blob."""

import asyncio
import os
import re
import time

from blob.privacy.controls import PrivacyBlocked
from blob.skills.base import SkillInterface, SkillResult
from blob.skills.builtin.web import web_result
from blob.skills.contracts import object_schema
from blob.skills.web_network import PublicBrowserProxy, public_url


class BrowserSkill(SkillInterface):
    name = "browser"
    description = ("Interact with a temporary public-web browser. Actions: open(url), snapshot, click(ref), "
                   "fill(ref,text), select(ref,text), press(ref,key), close. Use refs from the latest snapshot. "
                   "For lookups only; no sign-in, file uploads, purchases or messages. No desktop browser access.")
    triggers = ["browser", "website", "availability"]
    permissions = ("network.http", "browser.public")
    requires_cloud = True
    timeout_seconds = 40
    argument_schema = object_schema({
        "action": {"type": "string", "enum": ["open", "snapshot", "click", "fill", "select", "press", "close"]},
        "url": {"type": "string", "maxLength": 2048},
        "ref": {"type": "string", "maxLength": 30},
        "text": {"type": "string", "maxLength": 500},
        "key": {"type": "string", "enum": ["Enter", "Tab", "Escape", "ArrowDown", "ArrowUp"]},
    }, required=("action",))

    def __init__(self):
        self.controls = None
        self._lock = asyncio.Lock()
        self._driver = self._browser = self._context = self._page = self._proxy = self._monitor = None
        self._refs = {}
        self._snapshot_id = 0
        self._last_used = 0

    def execute(self, args):
        raise NotImplementedError("Use async_execute")

    def _check(self):
        if self.controls:
            self.controls.check(cloud=True)
            if self.name in self.controls.state["disabled_skills"]:
                raise PrivacyBlocked("The browser skill is disabled.")

    async def _watch(self):
        try:
            while True:
                await asyncio.sleep(0.25)
                self._check()
                if time.monotonic() - self._last_used > 120:
                    break
        except PrivacyBlocked:
            pass
        except asyncio.CancelledError:
            return
        await self.close()

    async def _start(self):
        from playwright.async_api import async_playwright
        self._check()
        self._proxy = PublicBrowserProxy(self._check)
        proxy_url = await self._proxy.start()
        self._driver = await async_playwright().start()
        self._browser = await self._driver.chromium.launch(
            headless=True, chromium_sandbox=True, proxy={"server": proxy_url, "bypass": "<-loopback>"},
            env={key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "XDG_RUNTIME_DIR") if key in os.environ},
            args=["--disable-quic", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"])
        self._context = await self._browser.new_context(accept_downloads=False, service_workers="block", permissions=[])
        self._context.set_default_timeout(5000)
        self._context.set_default_navigation_timeout(20000)

        async def route_request(route):
            try:
                self._check()
                public_url(route.request.url)
            except (ValueError, PrivacyBlocked):
                await route.abort()
            else:
                await route.continue_()

        async def block_socket(socket):
            await socket.close()

        await self._context.route("**/*", route_request)
        await self._context.route_web_socket("**/*", block_socket)
        self._page = await self._context.new_page()
        self._page.on("dialog", lambda dialog: asyncio.create_task(dialog.dismiss()))
        self._page.on("popup", lambda popup: asyncio.create_task(popup.close()))
        self._last_used = time.monotonic()
        self._monitor = asyncio.create_task(self._watch())

    async def _snapshot(self):
        self._check()
        url = public_url(self._page.url)
        text = await self._page.locator("body").inner_text(timeout=5000)
        title = await self._page.title()
        self._refs = {}
        self._snapshot_id += 1
        elements = []
        candidates = self._page.locator("a[href], button, input, select, textarea, [role=button], [role=link]")
        total = await candidates.count()
        for index in range(min(total, 80)):
            locator = candidates.nth(index)
            if not await locator.is_visible():
                continue
            handle = await locator.element_handle()
            if handle is None:
                continue
            info = await handle.evaluate("""e => {
                const label=e.labels?.[0]?.cloneNode(true);
                label?.querySelectorAll('input,select,textarea,button').forEach(n=>n.remove());
                return {tag:e.tagName.toLowerCase(), type:e.type||'',
                    name:(e.getAttribute('aria-label')||label?.textContent||e.innerText||e.placeholder||e.name||'').trim().slice(0,100),
                    options:e.tagName==='SELECT' ? Array.from(e.options).slice(0,25).map(o=>({label:o.label.slice(0,100),value:o.value.slice(0,100)})) : undefined};
            }""")
            ref = f"s{self._snapshot_id}e{index + 1}"
            self._refs[ref] = (handle, info)
            elements.append({"ref": ref, **info})
            if len(elements) == 30:
                break
        body = text.encode("utf-8")
        return web_result({"url": url, "title": title[:160],
            "text": body[:3000].decode("utf-8", errors="ignore"),
            "elements": elements, "truncated": len(body) > 3000 or total > len(elements),
            "note": "Use only current refs. If a result is still loading, request snapshot again. Login/CAPTCHA or blocked sites require manual checking."})

    async def async_execute(self, args):
        async with self._lock:
            action = args["action"]
            try:
                if action == "close":
                    await self.close()
                    return SkillResult("Closed the temporary browser and cleared its session.", True)
                self._check()
                self._last_used = time.monotonic()
                if action == "open":
                    url = public_url(args.get("url", ""))
                    if self._page is None:
                        await self._start()
                    response = await self._page.goto(url, wait_until="domcontentloaded")
                    if response is not None and response.status >= 400:
                        raise ValueError(f"The website returned HTTP {response.status}; availability was not verified.")
                elif self._page is None:
                    raise ValueError("Open a public website first.")
                elif action != "snapshot":
                    ref = args.get("ref", "")
                    if ref not in self._refs:
                        raise ValueError("That element ref is missing or stale. Request a fresh snapshot.")
                    handle, info = self._refs[ref]
                    if not await handle.is_visible() or not await handle.is_enabled():
                        raise ValueError("That element is unavailable. Request a fresh snapshot.")
                    if info["type"] in {"password", "file"}:
                        raise ValueError("Sign-in and file uploads require manual interaction outside this temporary browser.")
                    if action in {"click", "press"} and re.search(
                            r"\b(?:buy|purchase|pay|checkout|place order|book now|send|delete|subscribe|sign in|log in)\b", info["name"], re.I):
                        raise ValueError("This browser supports lookups. Complete transactions or account actions manually.")
                    if action == "click":
                        await handle.click()
                    elif action == "fill":
                        if "text" not in args:
                            raise ValueError("fill requires text.")
                        await handle.fill(args["text"])
                    elif action == "select":
                        if "text" not in args:
                            raise ValueError("select requires an option value or label in text.")
                        options = info.get("options", [])
                        value = next((option["value"] for option in options if args["text"] in {option["value"], option["label"]}), None)
                        if value is None:
                            raise ValueError("Choose an option value or label from the latest snapshot.")
                        await handle.select_option(value=value)
                    elif action == "press":
                        if "key" not in args:
                            raise ValueError("press requires an allowed key.")
                        await handle.press(args["key"])
                    self._refs = {}
                    try:
                        await self._page.wait_for_load_state("domcontentloaded", timeout=3000)
                    except Exception:
                        pass
                self._check()
                return await self._snapshot()
            except asyncio.CancelledError:
                await self.close()
                raise
            except ImportError:
                await self.close()
                return SkillResult("Install backend_python[web], then run python -m playwright install chromium.", False, "WORRIED")
            except (ValueError, PrivacyBlocked) as exc:
                return SkillResult(str(exc), False, "CONFUSED")
            except Exception:
                await self.close()
                return SkillResult("The browser could not complete that step. Check Chromium installation or retry the site; no result was verified.", False, "WORRIED")

    async def close(self):
        monitor, self._monitor = self._monitor, None
        if monitor is not None and monitor is not asyncio.current_task():
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        browser, driver, proxy = self._browser, self._driver, self._proxy
        self._browser = self._driver = self._context = self._page = self._proxy = None
        self._refs = {}
        if proxy:
            await proxy.close()
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        if driver:
            await driver.stop()
