"""Bounded public-web access. DNS answers are checked before connecting."""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit


def public_url(url):
    try:
        if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 for c in url):
            raise ValueError
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None:
            raise ValueError
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port != (443 if parsed.scheme == "https" else 80) or "%" in host:
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or host.endswith((".localhost", ".local", ".internal")):
                raise ValueError
        else:
            if not address.is_global or address.is_multicast:
                raise ValueError
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))
    except (ValueError, UnicodeError):
        raise ValueError("Use a public HTTP or HTTPS URL on its standard port; local addresses and credentials are blocked.") from None


async def public_addresses(host, port):
    records = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(record[4][0] for record in records))
    if not addresses or any(not ipaddress.ip_address(address).is_global or ipaddress.ip_address(address).is_multicast
                            for address in addresses):
        raise ValueError("This website resolves to a local or restricted address and was blocked.")
    return addresses


async def fetch_public(url, *, headers=None, max_bytes=1_000_000):
    """Use a checked resolver for every hop, including redirects; ignore env proxies."""
    import aiohttp
    from aiohttp.abc import AbstractResolver

    class PublicResolver(AbstractResolver):
        async def resolve(self, host, port=0, family=socket.AF_INET):
            return [{"hostname": host, "host": address, "port": port,
                     "family": socket.AF_INET6 if ":" in address else socket.AF_INET,
                     "proto": 0, "flags": 0} for address in await public_addresses(host, port)]

        async def close(self):
            pass

    connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False)
    request_headers = {"User-Agent": "Blob/0.1 (public web reader)", "Accept-Encoding": "identity", **(headers or {})}
    original = urlsplit(public_url(url))
    original_origin = (original.scheme, original.netloc.lower())
    async with aiohttp.ClientSession(connector=connector, trust_env=False, auto_decompress=False,
                                    timeout=aiohttp.ClientTimeout(total=20)) as session:
        for _ in range(5):
            url = public_url(url)
            # Never forward a provider token across an off-origin redirect.
            target = urlsplit(url)
            sent_headers = request_headers if (target.scheme, target.netloc.lower()) == original_origin else {
                key: value for key, value in request_headers.items() if key.lower() not in {"authorization", "x-subscription-token"}}
            async with session.get(url, headers=sent_headers, allow_redirects=False) as response:
                if response.status in {301, 302, 303, 307, 308}:
                    from urllib.parse import urljoin
                    url = urljoin(url, response.headers.get("Location", ""))
                    continue
                if response.status >= 400:
                    raise ValueError(f"The website returned HTTP {response.status}; its content was not verified.")
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    raise ValueError("The website ignored the uncompressed response request. Try the browser instead.")
                data = bytearray()
                async for chunk in response.content.iter_chunked(32768):
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise ValueError("The webpage exceeds the download limit. Try a smaller page or the browser.")
                return url, response.headers.get("Content-Type", ""), bytes(data)
    raise ValueError("The webpage redirected too many times.")


class PublicBrowserProxy:
    """Pin browser connections to validated public IPs, including HTTPS tunnels.

    A browser-side URL check alone cannot prevent DNS rebinding. This proxy
    resolves once and connects to that exact IP. No host proxy settings are used.
    """

    def __init__(self, check):
        self.check = check
        self.server = None
        self.tasks = set()

    async def start(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0, limit=16384)
        return f"http://127.0.0.1:{self.server.sockets[0].getsockname()[1]}"

    async def handle(self, reader, writer):
        if self.server is None or len(self.tasks) >= 64:
            writer.close()
            return
        task = asyncio.current_task()
        self.tasks.add(task)
        upstream = None
        try:
            self.check()
            raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            first, *lines = raw.decode("latin1").split("\r\n")
            method, target, version = first.split(" ")
            if method == "CONNECT":
                url = public_url("https://" + target)
            else:
                url = public_url(target)
                if urlsplit(url).scheme != "http":
                    raise ValueError("HTTPS requires a CONNECT tunnel")
            parsed = urlsplit(url)
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            addresses = await public_addresses(parsed.hostname, port)
            self.check()
            remote_reader = None
            for address in addresses:
                try:
                    remote_reader, upstream = await asyncio.wait_for(asyncio.open_connection(address, port), 10)
                    break
                except OSError:
                    continue
            if upstream is None:
                raise ValueError("The public website could not be reached")
            if method == "CONNECT":
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            else:
                path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
                safe_headers = [line for line in lines if line and line.partition(":")[0].lower()
                                not in {"host", "connection", "proxy-connection", "proxy-authorization"}]
                request = f"{method} {path} {version}\r\nHost: {parsed.netloc}\r\nConnection: close\r\n"
                upstream.write((request + "\r\n".join(safe_headers) + "\r\n\r\n").encode("latin1"))
                await upstream.drain()
            await writer.drain()

            async def relay(source, destination):
                while chunk := await source.read(32768):
                    self.check()
                    destination.write(chunk)
                    await destination.drain()

            transfers = [asyncio.create_task(relay(reader, upstream)), asyncio.create_task(relay(remote_reader, writer))]
            try:
                await asyncio.wait(transfers, timeout=60, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for transfer in transfers:
                    transfer.cancel()
                await asyncio.gather(*transfers, return_exceptions=True)
        except (Exception, asyncio.CancelledError):
            # Never include raw URLs, credentials or proxy response bodies in logs.
            pass
        finally:
            if upstream:
                upstream.close()
            writer.close()
            self.tasks.discard(task)

    async def close(self):
        server, self.server = self.server, None
        if server:
            server.close()
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # Python's Server.wait_closed waits for active connections too. Close
        # their handlers first, otherwise idle HTTPS tunnels delay shutdown.
        if server:
            await server.wait_closed()
