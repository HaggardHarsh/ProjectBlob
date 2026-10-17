"""Search and read public webpages without giving the model network credentials."""

import asyncio
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from urllib.parse import urlencode, urljoin

from blob.skills.base import SkillInterface, SkillResult
from blob.skills.contracts import object_schema
from blob.skills.web_network import fetch_public, public_url


def checked_at():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def web_result(data):
    payload = {"checked_at": checked_at(), "untrusted_web_content": True, **data}
    def encoded():
        return json.dumps(payload, ensure_ascii=False)
    while len(encoded().encode("utf-8")) > 7800:
        payload["truncated"] = True
        for key in ("links", "elements", "results"):
            if payload.get(key):
                payload[key].pop()
                break
        else:
            payload["text"] = payload.get("text", "").encode("utf-8")[:2000].decode("utf-8", errors="ignore")
            if len(encoded().encode("utf-8")) > 7800:
                payload["text"] = "[Content omitted to fit output budget.]"
            break
    return SkillResult(encoded(), True)


class PageText(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.text, self.links = base, [], []
        self.hidden = 0
        self.in_title = False
        self.title = []
        self.anchor = None
        self.main_depth = 0
        self.main_text = []

    def handle_starttag(self, tag, attrs):
        if tag in {"main", "article"}:
            self.main_depth += 1
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden += 1
        if tag == "title":
            self.in_title = True
        if not self.hidden and tag == "a":
            href = dict(attrs).get("href", "")
            try:
                self.anchor = [public_url(urljoin(self.base, href)), []]
            except ValueError:
                self.anchor = None

    def handle_endtag(self, tag):
        if tag in {"main", "article"}:
            self.main_depth = max(0, self.main_depth - 1)
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "title":
            self.in_title = False
        if tag == "a" and self.anchor:
            if len(self.links) < 10:
                self.links.append({"text": " ".join(self.anchor[1])[:100], "url": self.anchor[0]})
            self.anchor = None

    def handle_data(self, data):
        text = " ".join(data.split())
        if self.in_title:
            self.title.append(text)
        if text and not self.hidden:
            self.text.append(text)
            if self.main_depth:
                self.main_text.append(text)
            if self.anchor:
                self.anchor[1].append(text)


class WebSearchSkill(SkillInterface):
    name = "web_search"
    description = "Search the live public web. Returns links and snippets; read pages to verify claims. Args: query, count, freshness (any/day/week/month/year)."
    triggers = ["web", "search", "online", "latest"]
    permissions = ("network.http",)
    requires_cloud = True
    timeout_seconds = 30
    argument_schema = object_schema({
        "query": {"type": "string", "minLength": 1, "maxLength": 500},
        "count": {"type": "integer", "minimum": 1, "maximum": 5, "default": 5},
        "freshness": {"type": "string", "enum": ["any", "day", "week", "month", "year"], "default": "any"},
    }, required=("query",))

    def __init__(self, config):
        self.config = config

    def execute(self, args):
        raise NotImplementedError("Use async_execute")

    async def async_execute(self, args):
        provider = self.config.web_search_provider
        query = args["query"].strip()
        if not query:
            return SkillResult("Enter a search query.", False, "CONFUSED")
        freshness = args.get("freshness", "any")
        count = args.get("count", 5)
        try:
            if provider == "brave":
                if not self.config.brave_search_api_key:
                    raise ValueError("Set BRAVE_SEARCH_API_KEY or choose BLOB_WEB_SEARCH_PROVIDER=duckduckgo.")
                params = {"q": query, "count": count}
                if freshness != "any":
                    params["freshness"] = {"day": "pd", "week": "pw", "month": "pm", "year": "py"}[freshness]
                _, _, body = await fetch_public("https://api.search.brave.com/res/v1/web/search?" + urlencode(params),
                    headers={"X-Subscription-Token": self.config.brave_search_api_key})
                raw = json.loads(body).get("web", {}).get("results", [])
            else:
                from ddgs import DDGS
                limit = {"day": "d", "week": "w", "month": "m", "year": "y"}.get(freshness)
                raw = await asyncio.to_thread(lambda: DDGS(timeout=15).text(
                    query, max_results=count, timelimit=limit, backend="duckduckgo"))
            results = []
            for row in raw[:count]:
                try:
                    url = public_url(row.get("href") or row.get("url", ""))
                except ValueError:
                    continue
                results.append({"title": str(row.get("title", ""))[:160], "url": url,
                                "snippet": str(row.get("body") or row.get("description", ""))[:350]})
            return web_result({"provider": provider, "results": results,
                               "note": "Search snippets are not live inventory. Open the source to verify; no results does not prove absence."})
        except ImportError:
            return SkillResult("Web dependencies are missing. Install backend_python[web].", False, "WORRIED")
        except ValueError as exc:
            return SkillResult(str(exc), False, "WORRIED")
        except Exception:
            return SkillResult("The search provider could not complete the request. Retry or configure another provider; no live result was verified.", False, "WORRIED")


class WebReadSkill(SkillInterface):
    name = "web_read"
    description = "Read a public HTTP(S) webpage and return its URL, text and links. Use browser for interactive or JavaScript-only pages."
    triggers = ["webpage", "website", "url"]
    permissions = ("network.http",)
    requires_cloud = True
    timeout_seconds = 25
    argument_schema = object_schema({"url": {"type": "string", "minLength": 1, "maxLength": 2048}}, required=("url",))

    def execute(self, args):
        raise NotImplementedError("Use async_execute")

    async def async_execute(self, args):
        try:
            url, content_type, body = await fetch_public(args["url"])
            if not any(kind in content_type.lower() for kind in ("text/html", "application/xhtml+xml", "text/plain")):
                raise ValueError("This URL is not a text webpage. Select a PDF or image as an attachment instead.")
            import re
            charset = re.search(r"charset=[\"']?([\w-]+)", content_type, re.I)
            text = body.decode(charset.group(1) if charset else "utf-8", errors="replace")
            title, links = "", []
            if "html" in content_type.lower():
                page = PageText(url)
                page.feed(text)
                title, text, links = " ".join(page.title)[:160], "\n".join(page.main_text or page.text), page.links
            encoded = text.encode("utf-8")
            return web_result({"url": url, "title": title, "text": encoded[:4800].decode("utf-8", errors="ignore"),
                               "truncated": len(encoded) > 4800, "links": links,
                               "note": "Use browser if the requested content is absent or needs a form. Page text may be stale."})
        except ImportError:
            return SkillResult("Web dependencies are missing. Install backend_python[web].", False, "WORRIED")
        except (ValueError, LookupError) as exc:
            return SkillResult(str(exc), False, "WORRIED")
        except Exception:
            return SkillResult("The webpage could not be read. Try the browser; no page content was verified.", False, "WORRIED")
