"""Public-web evidence, network boundaries, privacy and model-tool routing."""

import asyncio
from contextlib import asynccontextmanager
import json
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from blob.config import BlobConfig
from blob.ai.context_budget import compact_browser_snapshots, prompt_size_bytes
from blob.ipc import blob_service_pb2 as pb
from blob.privacy.controls import PrivacyControls
from blob.skills.base import SkillResult
from blob.skills.builtin.web import WebReadSkill, WebSearchSkill, web_result
from blob.skills.registry import SkillRegistry
from blob.skills.web_network import fetch_public, public_addresses, public_url, PublicBrowserProxy
from test_attachments import orchestrator


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "javascript:alert(1)", "data:text/html,private", "http://localhost/",
    "http://127.0.0.1/", "http://10.0.0.1/", "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://192.168.1.1/",
    "https://private.local/", "https://x.internal/", "https://user:secret@example.com/",
    "https://example.com:50051/", "https://example.com/\nInjected: header", "http://2130706433/", "http://224.0.0.1/",
])
def test_nonpublic_and_credential_urls_are_rejected(url):
    with pytest.raises(ValueError):
        public_url(url)


@pytest.mark.asyncio
@pytest.mark.parametrize("addresses", [["127.0.0.1"], ["93.184.216.34", "10.0.0.1"], ["169.254.169.254"], ["::1"]])
async def test_dns_checks_all_answers_including_mixed_public_private(monkeypatch, addresses):
    records = [(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
               for address in addresses]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=records))
    with pytest.raises(ValueError, match="restricted"):
        await public_addresses("public-looking.example", 443)


def responses(monkeypatch, entries):
    aiohttp = pytest.importorskip("aiohttp")
    calls = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        @asynccontextmanager
        async def get(self, url, **kwargs):
            calls.append((url, kwargs))
            status, headers, body = entries.pop(0)
            async def chunks(size):
                for offset in range(0, len(body), size):
                    yield body[offset:offset + size]
            yield SimpleNamespace(status=status, headers=headers, content=SimpleNamespace(iter_chunked=chunks))

    monkeypatch.setattr(aiohttp, "TCPConnector", lambda **kwargs: None)
    monkeypatch.setattr(aiohttp, "ClientSession", lambda **kwargs: Session())
    return calls


@pytest.mark.asyncio
async def test_redirect_to_private_network_is_blocked_before_second_request(monkeypatch):
    calls = responses(monkeypatch, [(302, {"Location": "http://127.0.0.1/private"}, b"")])
    with pytest.raises(ValueError):
        await fetch_public("https://example.com/start")
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("destination", ["https://other.example/", "http://example.com/"])
async def test_off_origin_redirect_does_not_receive_search_credentials(monkeypatch, destination):
    calls = responses(monkeypatch, [(302, {"Location": destination}, b""),
                                   (200, {"Content-Type": "text/plain"}, b"public")])
    await fetch_public("https://example.com/", headers={"X-Subscription-Token": "private-key"})
    assert calls[0][1]["headers"]["X-Subscription-Token"] == "private-key"
    assert "X-Subscription-Token" not in calls[1][1]["headers"]


@pytest.mark.asyncio
async def test_reader_limits_download_and_excludes_script_instructions(monkeypatch):
    responses(monkeypatch, [(200, {"Content-Type": "text/html"}, b"x" * 101)])
    with pytest.raises(ValueError, match="download limit"):
        await fetch_public("https://example.com/", max_bytes=100)
    fake = AsyncMock(return_value=("https://example.com/lesson", "text/html; charset=utf-8",
        b'<title>Lesson</title><script>steal credentials</script><h1>Public facts</h1><a href="/next">Next</a>'))
    monkeypatch.setattr("blob.skills.builtin.web.fetch_public", fake)
    result = await WebReadSkill().async_execute({"url": "https://example.com/lesson"})
    data = json.loads(result.output)
    assert result.success and data["checked_at"] and data["untrusted_web_content"]
    assert "Public facts" in data["text"] and "steal credentials" not in data["text"]
    assert data["links"] == [{"text": "Next", "url": "https://example.com/next"}]


@pytest.mark.asyncio
async def test_search_without_key_returns_real_provider_links_and_freshness(monkeypatch):
    pytest.importorskip("ddgs")
    calls = []
    class Search:
        def __init__(self, **kwargs):
            pass

        def text(self, query, **kwargs):
            calls.append((query, kwargs))
            return [{"title": "Source", "href": "https://example.com/news", "body": "New announcement"},
                    {"title": "Local link", "href": "http://127.0.0.1/private", "body": "Do not return"}]

    monkeypatch.setattr("ddgs.DDGS", Search)
    registry = SkillRegistry()
    registry.register(WebSearchSkill(BlobConfig()))
    result = await registry.execute("web_search", {"query": "new announcement", "freshness": "day"})
    data = json.loads(result.output)
    assert result.success and len(data["results"]) == 1
    assert calls[0][1]["backend"] == "duckduckgo" and calls[0][1]["timelimit"] == "d"
    assert data["results"][0]["url"] == "https://example.com/news"
    assert "new announcement" not in str(registry.history)


def test_web_output_remains_valid_json_under_utf8_budget():
    result = web_result({"text": "日本語 " * 1200,
        "links": [{"text": "link", "url": "https://example.com/" + "a" * 2000}] * 10})
    assert len(result.output.encode("utf-8")) <= 7800
    assert json.loads(result.output)["truncated"]


@pytest.mark.asyncio
async def test_cloud_off_pause_disable_and_cancellation_block_web_work(tmp_path):
    controls = PrivacyControls(tmp_path / "private/settings.json")
    registry = SkillRegistry(controls=controls)
    skill = WebReadSkill()
    skill.async_execute = AsyncMock(return_value=SkillResult("public", True))
    registry.register(skill)
    for changes in ({"cloud_enabled": False}, {"cloud_enabled": True, "paused": True},
                    {"paused": False, "disabled_skills": ["web_read"]}):
        controls.update(**changes)
        assert not (await registry.execute("web_read", {"url": "https://example.com"}, source="terminal")).success
    skill.async_execute.assert_not_awaited()
    controls.update(disabled_skills=[])
    started = asyncio.Event()
    async def wait(args):
        started.set()
        await asyncio.Event().wait()
    skill.async_execute = wait
    task = asyncio.create_task(registry.execute("web_read", {"url": "https://example.com"}, source="terminal"))
    await started.wait()
    controls.update(cloud_enabled=False)
    controls.cancel_requests()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_browser_proxy_rejects_private_tunnel_before_connecting(monkeypatch):
    proxy = PublicBrowserProxy(lambda: None)
    url = await proxy.start()
    from urllib.parse import urlsplit
    reader, writer = await asyncio.open_connection("127.0.0.1", urlsplit(url).port)
    try:
        writer.write(b"CONNECT 169.254.169.254:443 HTTP/1.1\r\n\r\n")
        await writer.drain()
        assert await asyncio.wait_for(reader.read(), 2) == b""
    finally:
        writer.close()
        await writer.wait_closed()
        await proxy.close()


@pytest.mark.asyncio
async def test_proxy_shutdown_closes_an_idle_https_tunnel_without_waiting_for_timeout(monkeypatch):
    async def echo(reader, writer):
        try:
            await reader.read()
        finally:
            writer.close()
    upstream = await asyncio.start_server(echo, "127.0.0.1", 0)
    original_connect = asyncio.open_connection
    async def connect(host, port):
        if host == "93.184.216.34":
            return await original_connect("127.0.0.1", upstream.sockets[0].getsockname()[1])
        return await original_connect(host, port)
    monkeypatch.setattr("blob.skills.web_network.public_addresses", AsyncMock(return_value=["93.184.216.34"]))
    monkeypatch.setattr(asyncio, "open_connection", connect)
    proxy = PublicBrowserProxy(lambda: None)
    url = await proxy.start()
    from urllib.parse import urlsplit
    reader, writer = await original_connect("127.0.0.1", urlsplit(url).port)
    try:
        writer.write(b"CONNECT example.com:443 HTTP/1.1\r\n\r\n")
        await writer.drain()
        assert b"200 Connection Established" in await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 2)
        await asyncio.wait_for(proxy.close(), 2)
        assert await asyncio.wait_for(reader.read(), 2) == b""
    finally:
        writer.close()
        await writer.wait_closed()
        await proxy.close()
        upstream.close()
        await upstream.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_web_tools_route_through_registry_with_active_pdf(tmp_path, native):
    blob = orchestrator()
    blob.screen_sampler = None
    blob._build_context = lambda text: ""
    blob.skill_registry = SkillRegistry(tmp_path / "skills")
    reader = WebReadSkill()
    reader.async_execute = AsyncMock(return_value=web_result({"url": "https://example.com/", "text": "Verified public fact"}))
    blob.skill_registry.register(reader)
    blob._active_attachments = ["old.pdf"]
    if native:
        async def run(messages, system, tools, execute, event):
            assert {tool["name"] for tool in tools} == {"blob_web_read"}
            result = await execute("blob_web_read", {"url": "https://example.com/"})
            assert result.success
            return "Verified public fact: https://example.com/"
        blob.agent_runtime = SimpleNamespace(run=run)
    else:
        blob.llm.generate_from_messages.side_effect = [
            SimpleNamespace(content=json.dumps({"tool": "web_read", "args": {"url": "https://example.com/"}})),
            SimpleNamespace(content="Verified public fact: https://example.com/")]
    answer = await blob.handle_user_message(pb.UserMessage(text="Read the webpage https://example.com/"))
    assert "Verified public fact" in answer
    reader.async_execute.assert_awaited_once()
    assert blob._active_attachments == ["old.pdf"]


def test_web_provider_config_can_be_overridden_without_exposing_key(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOB_WEB_SEARCH_PROVIDER", "brave")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "secret-search-key")
    config = BlobConfig.load(str(tmp_path / "missing.yaml"))
    assert config.web_search_provider == "brave" and config.brave_search_api_key == "secret-search-key"
    assert "secret-search-key" not in repr(config)


@pytest.mark.parametrize("native", [False, True])
def test_long_browser_workflow_compacts_stale_snapshots_but_keeps_actions_and_failures(native):
    messages = [{"role": "user", "content": "Check the requested train and date."}]
    for index in range(8):
        snapshot = {"untrusted_web_content": True, "url": "https://example.com/lookup",
                    "elements": [{"ref": f"s{index}e1"}], "text": "page content " * 500,
                    "checked_at": "2026-10-17T12:00:00+00:00"}
        if native:
            messages.extend([
                {"role": "assistant", "tool_calls": [{"id": str(index), "function": {"name": "blob_browser", "arguments": '{"action":"snapshot"}'}}]},
                {"role": "tool", "tool_call_id": str(index), "content": json.dumps({"success": True, "output": json.dumps(snapshot)})}])
        else:
            messages.extend([
                {"role": "assistant", "content": '{"tool":"browser","args":{"action":"snapshot"}}'},
                {"role": "user", "content": "[Observation] Tool 'browser' executed successfully.\nResult: " + json.dumps(snapshot)}])
    failure = {"role": "tool" if native else "user", "tool_call_id": "failed", "content": "The action failed."}
    messages.append(failure)
    compacted = compact_browser_snapshots(messages)
    assert prompt_size_bytes(compacted) < 11000
    assert compacted[0] == messages[0] and compacted[-1] == failure
    assert compacted[-2] == messages[-2]  # The latest view is intact.
    assert all(compacted[index] == messages[index] for index in range(1, 17, 2))
    assert "page content" in messages[2]["content"]  # Input is not mutated.
    assert "Earlier browser snapshot omitted" in compacted[2]["content"]


@pytest.mark.asyncio
async def test_classic_browser_workflow_can_complete_more_than_three_steps(tmp_path):
    from blob.skills.builtin.browser import BrowserSkill
    blob = orchestrator()
    blob.screen_sampler = None
    blob._build_context = lambda text: ""
    blob._max_prompt_bytes = 12000
    blob.skill_registry = SkillRegistry(tmp_path / "skills")
    browser = BrowserSkill()
    browser.async_execute = AsyncMock(return_value=web_result({"url": "https://example.com/lookup",
        "text": "Current page " * 400, "elements": [{"ref": "s1e1"}]}))
    blob.skill_registry.register(browser)
    blob.llm.generate_from_messages.side_effect = [
        *[SimpleNamespace(content=json.dumps({"tool": "browser", "args": {"action": "snapshot"}})) for _ in range(4)],
        SimpleNamespace(content="The lookup completed: https://example.com/lookup")]
    result = await blob.handle_user_message(pb.UserMessage(text="Use the browser to check the lookup."))
    assert "lookup completed" in result
    assert browser.async_execute.await_count == 4
    messages = blob.llm.generate_from_messages.call_args.args[0]
    assert prompt_size_bytes(messages) <= 12000
    assert sum("Earlier browser snapshot omitted" in item.get("content", "") for item in messages) == 3


@pytest.mark.asyncio
async def test_native_bridge_compacts_snapshots_before_enforcing_budget(tmp_path):
    from test_agent_runtime import bridge, run
    view = {"untrusted_web_content": True, "url": "https://example.com/lookup",
            "text": "Old page " * 700, "elements": [{"ref": "s1e1"}]}
    messages = [{"role": "user", "content": "Complete the lookup."}]
    for index in range(6):
        messages.extend([
            {"role": "assistant", "tool_calls": [{"id": str(index), "function": {"name": "blob_browser", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": str(index), "content": json.dumps({"success": True, "output": json.dumps(view)})}])
    runtime = bridge(tmp_path, "emit({'type':'model','request':{'messages':" + repr(messages) + "}})\nreceive()\n"
                     "emit({'type':'final','answer':'Done.','completed':True})\n")
    try:
        assert await run(runtime) == "Done."
        bounded = runtime.llm._create.call_args.kwargs["messages"]
        assert prompt_size_bytes(bounded) <= runtime.config.max_prompt_bytes
        assert "Old page" in bounded[-1]["content"]
        assert "Earlier browser snapshot omitted" in bounded[2]["content"]
    finally:
        await runtime.close()
