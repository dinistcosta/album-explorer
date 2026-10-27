"""Last.fm API client. Every function is a no-op (no request) when LASTFM_API_KEY is unset."""
import html
import re
from datetime import timedelta

from django.conf import settings

from . import http

SOURCE = "lastfm"
ENDPOINT = "https://ws.audioscrobbler.com/2.0/"

_READ_MORE = re.compile(r"<a\b[^>]*>\s*Read more on Last\.fm\s*</a>\.?", re.I)
_LICENCE = re.compile(r"User-contributed text is available under[^\n]*", re.I)
_TAG = re.compile(r"<[^>]+>")


def clean_lastfm_wiki(text: str) -> str:
    """Strip the 'Read more' link, the licence line and any other markup; keep paragraph breaks."""
    text = _READ_MORE.sub("", text or "")
    text = _LICENCE.sub("", text)
    text = html.unescape(_TAG.sub("", text))
    paragraphs = [re.sub(r"[ \t]+", " ", p).strip() for p in re.split(r"\n\s*\n|\n", text)]
    return "\n\n".join(p for p in paragraphs if p)


def _call(method: str, ttl: timedelta = timedelta(days=30), **params) -> dict | None:
    key = settings.LASTFM_API_KEY
    if not key:
        return None
    try:
        data = http.fetch(
            SOURCE, ENDPOINT,
            params={"method": method, "api_key": key, "format": "json", **params}, ttl=ttl,
        )
    except http.SourceNotFound:
        return None
    if not isinstance(data, dict) or "error" in data:  # Last.fm reports "not found" as HTTP 200 + error
        return None
    return data


def album_info(artist: str, title: str, mbid: str | None, lang: str) -> dict | None:
    """`mbid` must be a *release* MBID; when it (or its absence) yields nothing, retry by name."""
    if mbid:
        data = _call("album.getinfo", lang=lang, mbid=mbid)
        if (data or {}).get("album"):
            return data["album"]
    data = _call("album.getinfo", lang=lang, artist=artist, album=title, autocorrect=1)
    return (data or {}).get("album") or None


def artist_info(name: str, mbid: str | None, lang: str) -> dict | None:
    if mbid:
        data = _call("artist.getinfo", lang=lang, mbid=mbid)
        if (data or {}).get("artist"):
            return data["artist"]
    data = _call("artist.getinfo", lang=lang, artist=name, autocorrect=1)
    return (data or {}).get("artist") or None


def album_top_tags(artist: str, title: str) -> list[str]:
    data = _call("album.gettoptags", artist=artist, album=title, autocorrect=1)
    return [t["name"] for t in ((data or {}).get("toptags") or {}).get("tag") or [] if t.get("name")]


def tag_top_albums(tag: str, limit: int = 100) -> list[dict]:
    data = _call("tag.gettopalbums", ttl=timedelta(days=7), tag=tag, limit=limit)
    return ((data or {}).get("albums") or {}).get("album") or []


def tag_info(tag: str, lang: str) -> dict | None:
    data = _call("tag.getinfo", tag=tag, lang=lang)
    return (data or {}).get("tag") or None
