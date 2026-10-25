"""Outbound HTTP for URL import, with an SSRF guard.

Only http(s) URLs whose host resolves to public IP addresses are fetched; every redirect hop is
re-checked. This keeps a pasted link from reaching the router, the hub, VPN subnets or localhost.
(Remaining gap: DNS could change between the check and the connect. Acceptable for a LAN-only app.)
"""
import hashlib
import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin, urlsplit

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
MAX_REDIRECTS = 5
MAX_HTML_BYTES = 3 * 1024 * 1024


class FetchError(Exception):
    """Message is shown to the user."""


class UnsafeURL(FetchError):
    pass


class Blocked(FetchError):
    pass


Resolver = Callable[[str, int], list]


def _system_resolver(host: str, port: int) -> list:
    return [info[4][0] for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)]


def check_url(url: str, resolver: Optional[Resolver] = None) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsafeURL("Only http:// and https:// links can be imported.")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        addresses = (resolver or _system_resolver)(parts.hostname, port)
    except (socket.gaierror, UnicodeError):
        raise FetchError(f"Couldn't find the site {parts.hostname}.")
    if not addresses:
        raise FetchError(f"Couldn't find the site {parts.hostname}.")
    for addr in addresses:
        ip = ipaddress.ip_address(addr.split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise UnsafeURL("That link points to a private or local address, so it won't be fetched.")


@dataclass
class Response:
    url: str
    status: int
    content_type: str
    body: bytes


def _client() -> httpx.Client:
    return httpx.Client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=False)


def _get(url: str, accept: str, max_bytes: int, sink=None, referer: Optional[str] = None,
         resolver: Optional[Resolver] = None) -> Response:
    """GET with manual, re-checked redirects and a size cap. Streams into `sink` if given."""
    headers = {"Accept": accept}
    if referer:
        headers["Referer"] = referer
    with _client() as client:
        for _ in range(MAX_REDIRECTS + 1):
            check_url(url, resolver)
            try:
                with client.stream("GET", url, headers=headers) as resp:
                    if resp.is_redirect:
                        url = urljoin(url, resp.headers.get("location", ""))
                        continue
                    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                    if resp.status_code >= 400:
                        return Response(str(resp.url), resp.status_code, ctype, b"")
                    declared = resp.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise FetchError("That file is too large to import.")
                    chunks, size = [], 0
                    for chunk in resp.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise FetchError("That file is too large to import.")
                        if sink is not None:
                            sink(chunk)
                        else:
                            chunks.append(chunk)
                    return Response(str(resp.url), resp.status_code, ctype, b"".join(chunks))
            except httpx.TimeoutException:
                raise FetchError("The site took too long to answer.")
            except httpx.HTTPError as exc:
                raise FetchError(f"Couldn't connect to the site ({type(exc).__name__}).")
        raise FetchError("Too many redirects.")


def fetch_page(url: str, resolver: Optional[Resolver] = None) -> Response:
    resp = _get(url, "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8", MAX_HTML_BYTES,
                resolver=resolver)
    if resp.status in (401, 403, 429, 503):
        raise Blocked(f"The store blocked the request (HTTP {resp.status}).")
    if resp.status >= 400:
        raise FetchError(f"The page returned an error (HTTP {resp.status}).")
    return resp


def download_image(url: str, dest: Path, max_bytes: int, referer: Optional[str] = None,
                   resolver: Optional[Resolver] = None) -> str:
    """Stream an image to `dest`; returns its sha256. Pillow validates the content afterwards."""
    h = hashlib.sha256()
    with dest.open("wb") as f:
        def sink(chunk: bytes) -> None:
            h.update(chunk)
            f.write(chunk)

        resp = _get(url, "image/jpeg,image/png;q=0.9,image/webp;q=0.8,image/*;q=0.5", max_bytes,
                    sink=sink, referer=referer, resolver=resolver)
    if resp.status >= 400:
        raise FetchError(f"The image couldn't be downloaded (HTTP {resp.status}).")
    if resp.content_type and not (resp.content_type.startswith("image/")
                                  or resp.content_type == "application/octet-stream"):
        raise FetchError("That link isn't an image (the server sent "
                         f"{resp.content_type}). Use the direct image link.")
    return h.hexdigest()
