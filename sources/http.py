import hashlib
import json
from datetime import timedelta
from time import sleep  # noqa: F401  (module-level so tests can patch it)

import httpx
from django.conf import settings
from django.utils import timezone

from .models import HttpCacheEntry
from .throttle import MIN_INTERVAL, acquire_slot  # noqa: F401

MAX_ATTEMPTS = 3
TIMEOUT = 10.0
# Foreground fetches run inside a page request (gunicorn --timeout 60): one retry, short waits.
FOREGROUND_MAX_ATTEMPTS = 2
FOREGROUND_TIMEOUT = 5.0
FOREGROUND_BACKOFF = 1.0
RETRY_STATUSES = {429, 503}


class SourceUnavailable(Exception):
    pass


class SourceNotFound(Exception):
    pass


def _cache_key(source: str, url: str, params: dict | None) -> str:
    raw = json.dumps([source, url, sorted((params or {}).items())], default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _decode(body: bytes, as_json: bool, binary: bool):
    if binary:
        return body
    text = body.decode("utf-8", errors="replace")
    if as_json:
        try:
            return json.loads(text)
        except ValueError as exc:
            raise SourceUnavailable("invalid JSON") from exc
    return text


def fetch(
    source: str,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    ttl: timedelta = timedelta(days=30),
    foreground: bool = False,
    as_json: bool = True,
    binary: bool = False,
) -> dict | str | bytes:
    key = _cache_key(source, url, params)
    entry = HttpCacheEntry.objects.filter(key=key).first()
    if entry and timezone.now() - entry.fetched_at < ttl:
        return _decode(bytes(entry.body), as_json, binary)

    request_headers = {"User-Agent": f"AlbumExplorer/0.1 ( {settings.CONTACT_URL} )"}
    request_headers.update(headers or {})

    attempts = FOREGROUND_MAX_ATTEMPTS if foreground else MAX_ATTEMPTS
    timeout = FOREGROUND_TIMEOUT if foreground else TIMEOUT
    response = None
    for attempt in range(attempts):
        if attempt:
            sleep(FOREGROUND_BACKOFF if foreground else float(attempt))  # background: 1 s, then 2 s
        acquire_slot(source, foreground=foreground)
        try:
            response = httpx.get(
                url, params=params, headers=request_headers, timeout=timeout,
                follow_redirects=True,
            )
        except httpx.TransportError:
            response = None
            continue
        if response.status_code in RETRY_STATUSES:
            continue
        break
    if response is None or response.status_code in RETRY_STATUSES:
        raise SourceUnavailable(f"{source}: unavailable after {attempts} attempts")

    if response.status_code == 404:
        raise SourceNotFound(url)
    if not 200 <= response.status_code < 300:
        raise SourceUnavailable(f"{source}: HTTP {response.status_code}")

    body = response.content
    result = _decode(body, as_json, binary)
    HttpCacheEntry.objects.update_or_create(
        key=key,
        defaults={"status": response.status_code, "body": body, "fetched_at": timezone.now()},
    )
    return result
