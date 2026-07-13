"""Best-effort free public proxy discovery for the region-block bypass.

When a video is geo-restricted by its uploader, the only reliable workaround is
to route the request through a proxy that exits in a country where the video is
available (see ``config`` for the full rationale). This module fetches a list of
free public proxies, ranks them, and exposes a quick liveness check so the
downloader can try the most promising ones first.

Free proxies are inherently unreliable, slow, and short-lived, so every function
here is defensive: network errors are swallowed and simply yield an empty/❌
result rather than raising. Callers should treat this as a hint, not a
guarantee, and fall back to asking the user for their own proxy/VPN.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Any

from ..config import (
    AUTO_PROXY_CANDIDATE_POOL,
    FREE_PROXY_API_URL,
    PREFERRED_PROXY_COUNTRIES,
    PROXY_CACHE_TTL,
    PROXY_LIVENESS_TIMEOUT,
)

_USER_AGENT = "Mozilla/5.0 (YoutubeVideoDownloader)"
# A tiny endpoint that returns HTTP 204 with an empty body — ideal for cheaply
# confirming a proxy can actually reach YouTube over TLS.
_LIVENESS_URL = "https://www.youtube.com/generate_204"

_ACCEPTED_ANONYMITY = {"elite", "anonymous"}

_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"ts": 0.0, "candidates": []}

# A proxy that recently completed a download is very likely to work for sibling
# videos (same geo block), so we remember the last good one and try it first.
_good_lock = threading.Lock()
_good_proxy: dict[str, Any] = {"url": None, "ts": 0.0}


def remember_good_proxy(url: str) -> None:
    with _good_lock:
        _good_proxy["url"] = url
        _good_proxy["ts"] = time.time()


def forget_proxy(url: str) -> None:
    with _good_lock:
        if _good_proxy.get("url") == url:
            _good_proxy["url"] = None
            _good_proxy["ts"] = 0.0


def get_remembered_proxy() -> str | None:
    with _good_lock:
        url = _good_proxy.get("url")
        if url and (time.time() - _good_proxy.get("ts", 0.0)) < PROXY_CACHE_TTL:
            return str(url)
    return None


@dataclass(slots=True, frozen=True)
class ProxyCandidate:
    """A single ranked free proxy."""

    url: str
    country: str = "??"


def _quality_key(record: dict[str, Any], preferred: set[str]) -> tuple:
    """Ranking key: preferred countries first, then most reliable/fastest."""

    country = str((record.get("ip_data") or {}).get("countryCode") or "").upper()
    uptime = float(record.get("uptime") or 0.0)
    avg_timeout = float(record.get("average_timeout") or 1_000_000.0)
    return (
        0 if country in preferred else 1,
        -uptime,
        avg_timeout,
    )


def _fetch_records() -> list[dict[str, Any]]:
    request = urllib.request.Request(
        FREE_PROXY_API_URL, headers={"User-Agent": _USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8", "replace"))
    records = payload.get("proxies")
    return records if isinstance(records, list) else []


def fetch_proxy_candidates(
    *,
    preferred_countries: tuple[str, ...] = PREFERRED_PROXY_COUNTRIES,
    exclude_countries: tuple[str, ...] = (),
    pool_size: int = AUTO_PROXY_CANDIDATE_POOL,
    use_cache: bool = True,
) -> list[ProxyCandidate]:
    """Return ranked free-proxy candidates (best first). Empty list on failure.

    Results are cached process-wide for ``PROXY_CACHE_TTL`` seconds so a queue of
    geo-blocked videos reuses one fetch instead of re-hitting the API per item.
    """

    now = time.time()
    if use_cache:
        with _cache_lock:
            if _cache["candidates"] and (now - _cache["ts"]) < PROXY_CACHE_TTL:
                return list(_cache["candidates"])

    try:
        records = _fetch_records()
    except Exception:
        return []

    preferred = {c.upper() for c in preferred_countries}
    excluded = {c.upper() for c in exclude_countries}

    usable: list[dict[str, Any]] = []
    for record in records:
        if not record.get("alive", True):
            continue
        if str(record.get("anonymity") or "").lower() not in _ACCEPTED_ANONYMITY:
            continue
        proxy_url = record.get("proxy")
        if not isinstance(proxy_url, str) or "://" not in proxy_url:
            continue
        country = str((record.get("ip_data") or {}).get("countryCode") or "").upper()
        if country and country in excluded:
            continue
        usable.append(record)

    usable.sort(key=lambda rec: _quality_key(rec, preferred))

    candidates = [
        ProxyCandidate(
            url=str(rec["proxy"]),
            country=str((rec.get("ip_data") or {}).get("countryCode") or "??").upper(),
        )
        for rec in usable[:pool_size]
    ]

    if use_cache and candidates:
        with _cache_lock:
            _cache["ts"] = now
            _cache["candidates"] = list(candidates)

    return candidates


def proxy_is_live(proxy_url: str, timeout: float = PROXY_LIVENESS_TIMEOUT) -> bool:
    """Quickly check whether ``proxy_url`` can reach YouTube. Never raises."""

    handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    opener = urllib.request.build_opener(handler)
    request = urllib.request.Request(
        _LIVENESS_URL, headers={"User-Agent": _USER_AGENT}
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            return 200 <= getattr(response, "status", 200) < 400
    except Exception:
        return False
