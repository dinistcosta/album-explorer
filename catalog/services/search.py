import uuid
from dataclasses import dataclass, field

from django.db.models import Case, IntegerField, Value, When

from catalog.models import Album, Artist
from catalog.services.text import normalize
from sources import musicbrainz as mb
from sources.http import SourceUnavailable

SUGGEST_LIMIT = 5
MIN_CHARS = 2


@dataclass
class SearchResults:
    artists: list = field(default_factory=list)
    albums: list = field(default_factory=list)
    source_error: bool = False


def _prefix_first(qs, term):
    return qs.filter(search_name__contains=term).annotate(
        _rank=Case(When(search_name__startswith=term, then=Value(0)), default=Value(1), output_field=IntegerField())
    )


def suggest(query: str) -> dict[str, list]:
    term = normalize(query)
    if len(term) < MIN_CHARS:
        return {"artists": [], "albums": []}
    artists = _prefix_first(Artist.objects, term).order_by("_rank", "search_name")[:SUGGEST_LIMIT]
    albums = _prefix_first(Album.objects.select_related("artist"), term).order_by("_rank", "search_name")[:SUGGEST_LIMIT]
    return {"artists": list(artists), "albums": list(albums)}


def _year(date: str | None) -> int | None:
    head = (date or "")[:4]
    return int(head) if head.isdigit() else None


def _valid(mbid) -> bool:
    try:
        uuid.UUID(str(mbid))
        return True
    except ValueError:
        return False


def _upsert_artist(data: dict) -> Artist | None:
    if not _valid(data.get("id")):
        return None
    name = (data.get("name") or "")[:300]
    artist, created = Artist.objects.get_or_create(mbid=uuid.UUID(data["id"]), defaults={"name": name})
    values = {
        "name": name,
        "sort_name": (data.get("sort-name") or "")[:300],
        "country": (data.get("country") or "")[:8],
        "artist_type": (data.get("type") or "")[:32],
    }
    values = {k: v for k, v in values.items() if v}  # a sparse credit stub never blanks richer data
    if artist.imported_at is None:
        span = data.get("life-span") or {}
        for key, src in (("begin_year", "begin"), ("end_year", "end")):
            if _year(span.get(src)) is not None:
                values[key] = _year(span.get(src))
    if artist.apply_source_fields(**values) or created:
        artist.save()
    return artist


def _upsert_album(data: dict) -> Album | None:
    if not _valid(data.get("id")):
        return None
    credit = data.get("artist-credit") or []
    artist = None
    if credit and isinstance(credit[0].get("artist"), dict):
        artist = _upsert_artist(credit[0]["artist"])
    credit_text = "".join(f"{c.get('name') or ''}{c.get('joinphrase') or ''}" for c in credit)[:500]
    title = (data.get("title") or "")[:500]
    album, created = Album.objects.get_or_create(mbid=uuid.UUID(data["id"]), defaults={"title": title})
    values = {
        "title": title,
        "primary_type": (data.get("primary-type") or "")[:32],
        "secondary_types": data.get("secondary-types") or [],
        "artist_credit": credit_text,
    }
    year = _year(data.get("first-release-date"))
    if year is not None:
        values["year"] = year
    if album.artist_id is None and artist is not None:
        values["artist"] = artist
    if album.apply_source_fields(**values) or created:
        album.save()
    return album


def _dedupe(items):
    seen, out = set(), []
    for item in items:
        if item is not None and item.mbid not in seen:
            seen.add(item.mbid)
            out.append(item)
    return out


def search(query: str) -> SearchResults:
    query = query.strip()
    term = normalize(query)
    result = SearchResults()
    if not term:
        return result
    mb_artists, mb_albums = [], []
    try:
        # search_artists escapes Lucene itself; the release-group query is composed, so escape here.
        raw_artists = mb.search_artists(query, foreground=True)
        raw_groups = mb.search_release_groups(
            f"releasegroup:({mb.escape_lucene(query)}) AND (primarytype:album OR primarytype:ep)",
            foreground=True, raw=True,
        )
        mb_artists = [_upsert_artist(a) for a in raw_artists]
        scored = [(int(g.get("score", 0) or 0), _upsert_album(g)) for g in raw_groups]
        scored = [(s, a) for s, a in scored if a is not None]
        scored.sort(key=lambda sa: (-sa[0], -(sa[1].lastfm_listeners or 0)))
        mb_albums = [a for _, a in scored]
    except SourceUnavailable:
        result.source_error = True
    local_artists = Artist.objects.filter(search_name__contains=term).order_by("search_name")[:8]
    local_albums = (
        Album.objects.filter(search_name__contains=term).select_related("artist")
        .order_by("-lastfm_listeners", "search_name")[:24]
    )
    result.artists = _dedupe([*mb_artists, *local_artists])
    result.albums = _dedupe([*mb_albums, *local_albums])
    return result
