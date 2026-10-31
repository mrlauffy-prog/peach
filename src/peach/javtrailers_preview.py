"""JavTrailers preview lookup: prefer its 1080p HLS master over JavDB's 720p.

JavTrailers publishes one public page per title (`/video/<slug>`) and a
three-rendition HLS master on `media.javtrailers.com` (432p / 720p / 1080p).
The page also carries the DVD ID, which is the identity check: never accept a
search hit whose DVD ID differs from the requested code.

Standard JAV codes use a five-digit, zero-padded slug (`MIDA-859` ->
`mida00859`). Non-standard codes fall back to the site search, then every
candidate page is checked by DVD ID.
"""
from __future__ import annotations

import re
from urllib.parse import quote

import httpx

from .peach_proxy import http_client
from .user_agent import USER_AGENT

SITE = "https://javtrailers.com"
MEDIA_HOST = "media.javtrailers.com"

_DVD_ID = re.compile(r"DVD ID:\s*</span>\s*([A-Za-z0-9_-]+)", re.I)
_VIDEO = re.compile(
    r"https://media\.javtrailers\.com/hlsvideo/freepv/[^\"'\s<>]+?\.m3u8", re.I)
_SEARCH_VIDEO = re.compile(r'href="(/video/[a-z0-9]+)"', re.I)
_STANDARD = re.compile(r"^([A-Za-z]+)-?(\d+)$")


def normalized_code(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def standard_slug(code: str) -> str:
    """`MIDA-859` -> `mida00859`; empty for codes JavTrailers does not pad this way."""
    match = _STANDARD.fullmatch(str(code or "").strip())
    if not match:
        return ""
    prefix, number = match.groups()
    return f"{prefix.lower()}{int(number):05d}"


def _get(client: httpx.Client, url: str) -> str:
    try:
        response = client.get(url)
    except httpx.HTTPError:
        return ""
    if response.status_code != 200:
        return ""
    return response.text


def _matches(html: str, code: str) -> bool:
    found = _DVD_ID.search(html)
    return bool(found and normalized_code(found.group(1)) == normalized_code(code))


def _video(html: str) -> str:
    found = _VIDEO.search(html)
    return found.group(0) if found else ""


def _resolve(client: httpx.Client, code: str) -> str:
    slug = standard_slug(code)
    if slug:
        html = _get(client, f"{SITE}/video/{slug}")
        if _matches(html, code):
            url = _video(html)
            if url:
                return url
    search = _get(client, f"{SITE}/search/{quote(code, safe='')}")
    for path in dict.fromkeys(_SEARCH_VIDEO.findall(search)):
        html = _get(client, SITE + path)
        if _matches(html, code):
            url = _video(html)
            if url:
                return url
    return ""


def preview_url(code: str, cache=None) -> str:
    """Return the JavTrailers HLS master for `code`, or an empty string.

    `cache` is a `RemoteMediaCache`; when supplied the resolved media URL is
    reused for a day. A negative result is not cached, so a transient block
    does not hide a title for 24 hours.
    """
    def fetch() -> bytes:
        with http_client(timeout=8, follow_redirects=True) as client:
            client.headers.update({
                "User-Agent": USER_AGENT,
                "Referer": SITE + "/",
                "Accept-Language": "en-US,en;q=0.9",
            })
            return _resolve(client, code).encode()

    if cache is None:
        return fetch().decode()
    try:
        return cache.bytes(f"javtrailers:{normalized_code(code)}", fetch, ttl=24 * 3600).decode()
    except Exception:
        return ""
