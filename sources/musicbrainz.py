import re

from . import http

BASE = "https://musicbrainz.org/ws/2/"
SOURCE = "musicbrainz"
PAGE = 100

RELEASE_INC = (
    "recordings+artist-credits+labels+artist-rels+place-rels+recording-level-rels+url-rels"
)

_LUCENE_SPECIALS = re.compile(r'(&&|\|\||[+\-!(){}\[\]^"~*?:\\/])')


def escape_lucene(text: str) -> str:
    return _LUCENE_SPECIALS.sub(r"\\\1", text)


def _get(path: str, params: dict, *, foreground: bool, **kwargs):
    return http.fetch(
        SOURCE, BASE + path, params={**params, "fmt": params.get("fmt", "json")},
        foreground=foreground, **kwargs,
    )


def _browse(path: str, params: dict, list_key: str, count_key: str, foreground: bool) -> list[dict]:
    items: list[dict] = []
    offset = 0
    while True:
        page = _get(path, {**params, "limit": PAGE, "offset": offset}, foreground=foreground)
        batch = page.get(list_key, [])
        items.extend(batch)
        offset += PAGE
        if not batch or len(items) >= page.get(count_key, 0):
            return items


def get_release_group(mbid: str, foreground: bool = False) -> dict:
    return _get(
        f"release-group/{mbid}", {"inc": "artist-credits+url-rels+genres"}, foreground=foreground
    )


def browse_releases(release_group_mbid: str, foreground: bool = False) -> list[dict]:
    return _browse(
        "release", {"release-group": release_group_mbid, "inc": "media"},
        "releases", "release-count", foreground,
    )


def get_release(mbid: str, foreground: bool = False) -> dict:
    return _get(f"release/{mbid}", {"inc": RELEASE_INC}, foreground=foreground)


def get_artist(mbid: str, foreground: bool = False) -> dict:
    return _get(
        f"artist/{mbid}", {"inc": "url-rels+artist-rels+genres"}, foreground=foreground
    )


def browse_release_groups(artist_mbid: str, foreground: bool = False) -> list[dict]:
    return _browse(
        "release-group", {"artist": artist_mbid, "type": "album|ep"},
        "release-groups", "release-group-count", foreground,
    )


def search_artists(query: str, limit: int = 8, foreground: bool = False) -> list[dict]:
    data = _get(
        "artist", {"query": escape_lucene(query), "limit": limit}, foreground=foreground
    )
    return data.get("artists", [])


def search_release_groups(
    query: str, limit: int = 24, foreground: bool = False, raw: bool = False
) -> list[dict]:
    """`raw=True` sends the query as Lucene (the caller has already escaped its user text)."""
    data = _get(
        "release-group", {"query": query if raw else escape_lucene(query), "limit": limit},
        foreground=foreground,
    )
    return data.get("release-groups", [])


def list_genres(foreground: bool = False) -> list[str]:
    text = _get("genre/all", {"fmt": "txt"}, foreground=foreground, as_json=False)
    return [line.strip() for line in text.splitlines() if line.strip()]
