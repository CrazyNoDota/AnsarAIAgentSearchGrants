"""
SSRF guard for operator-supplied URLs (Phase 7 custom sources).

Custom sources let an operator point the scraper at an arbitrary URL. Even though
those routes require auth, we defend in depth: before fetching, every URL (and
every redirect hop) is resolved and rejected if it points at a non-public address
— loopback, private/RFC1918, link-local (incl. the 169.254.169.254 cloud
metadata endpoint), reserved, multicast or unspecified ranges.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    """Raised when a URL is not allowed to be fetched (bad scheme or private IP)."""


def _ip_is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    # Allow ONLY globally-routable addresses. ``is_global`` already excludes
    # private/loopback/link-local/reserved/unspecified AND non-routable ranges
    # such as CGNAT 100.64.0.0/10 that the individual flags miss. The explicit
    # multicast/unspecified checks are belt-and-suspenders across versions.
    return addr.is_global and not (addr.is_multicast or addr.is_unspecified)


def _resolve_ips(host: str) -> list[str]:
    """Resolve a host to its IP literals (IPv4 + IPv6). Empty on failure."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return []
    return [info[4][0] for info in infos]


def _check(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsafeURLError(f"unsupported or malformed URL: {url!r}")

    host = parsed.hostname
    # A bare IP literal is checked directly (no DNS); otherwise resolve the name
    # and require EVERY resolved address to be public (guards DNS-rebinding-ish
    # multi-record hosts).
    try:
        ipaddress.ip_address(host)
        ips = [host]
    except ValueError:
        ips = _resolve_ips(host)
        if not ips:
            raise UnsafeURLError(f"could not resolve host: {host!r}")

    for ip in ips:
        if not _ip_is_public(ip):
            raise UnsafeURLError(
                f"URL resolves to a non-public address ({ip}); refusing to fetch {host!r}"
            )


async def assert_public_url(url: str) -> None:
    """Async wrapper — runs the blocking DNS lookup off the event loop.

    Raises ``UnsafeURLError`` if the URL's scheme is not http(s) or any resolved
    address is non-public.
    """
    await asyncio.to_thread(_check, url)
