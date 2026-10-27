"""Genre rooms: Last.fm's top albums for a tag, matched to MusicBrainz release groups."""
import re
from collections import defaultdict

from django.utils import timezone

from catalog.models import Album, Genre, GenreRanking
from catalog.services.text import normalize
from sources import musicbrainz as mb

_TRAILING_PAREN = re.compile(r"\s*[(\[][^)\]]*[)\]]\s*$")


def titles_match(wanted: str, found: str) -> bool:
    """Equal after normalising, or one is the other plus a trailing parenthetical ("(Remastered)")."""
    a, b = normalize(wanted), normalize(found)
    if not a or not b:
        return False
    return a == b or normalize(_TRAILING_PAREN.sub("", wanted)) == b or a == normalize(_TRAILING_PAREN.sub("", found))


def artists_match(wanted: str, group: dict) -> bool:
    credits = group.get("artist-credit") or []
    names = {normalize("".join((c.get("name") or "") + (c.get("joinphrase") or "") for c in credits))}
    names |= {normalize(c.get("name") or "") for c in credits}
    names |= {normalize((c.get("artist") or {}).get("name") or "") for c in credits}
    return normalize(wanted) in names - {""}


def release_group_query(title: str, artist: str) -> str:
    return f'releasegroup:"{mb.escape_lucene(title)}" AND artist:"{mb.escape_lucene(artist)}"'


def _year(date: str | None) -> int | None:
    head = (date or "")[:4]
    return int(head) if head.isdigit() else None


def stub_album(group: dict) -> Album:
    """The album for a release group: the existing row, or a stub the album page imports on demand."""
    album = Album.objects.filter(mbid=group["id"]).first()
    if album is None:
        credit = "".join((c.get("name") or "") + (c.get("joinphrase") or "") for c in group.get("artist-credit") or [])
        album = Album.objects.create(
            mbid=group["id"], title=group.get("title", ""), artist_credit=credit,
            year=_year(group.get("first-release-date")), primary_type=group.get("primary-type") or "",
            secondary_types=group.get("secondary-types") or [])
    return album


def store_rankings(genre: Genre, items: list[dict]) -> None:
    existing = {r.rank: r for r in GenreRanking.objects.filter(genre=genre)}
    for rank, item in enumerate(items, start=1):
        artist = (item.get("artist") or {}).get("name", "") if isinstance(item.get("artist"), dict) else item.get("artist", "")
        title = item.get("name", "")
        row = existing.get(rank)
        if row is None:
            GenreRanking.objects.create(genre=genre, rank=rank, lastfm_artist=artist[:300], lastfm_title=title[:500])
        elif (row.lastfm_artist, row.lastfm_title) != (artist[:300], title[:500]):
            row.lastfm_artist, row.lastfm_title = artist[:300], title[:500]
            row.album, row.resolved_at = None, None
            row.save()
    GenreRanking.objects.filter(genre=genre, rank__gt=len(items)).delete()


def resolve_rankings(genre: Genre) -> None:
    """Resolve every unresolved row; a source failure leaves the rest for the next run."""
    from sources.http import SourceNotFound, SourceUnavailable

    for row in GenreRanking.objects.filter(genre=genre, resolved_at__isnull=True):
        try:
            groups = mb.search_release_groups(
                release_group_query(row.lastfm_title, row.lastfm_artist), limit=1, foreground=False, raw=True)
        except SourceNotFound:
            groups = []
        except SourceUnavailable:
            return
        match = next((g for g in groups[:1] if titles_match(row.lastfm_title, g.get("title", ""))
                      and artists_match(row.lastfm_artist, g)), None)
        row.album = stub_album(match) if match else None
        row.resolved_at = timezone.now()
        row.save(update_fields=["album", "resolved_at"])


def room_by_decade(genre: Genre) -> list[tuple[int | None, list[Album]]]:
    seen, groups = set(), defaultdict(list)
    for row in GenreRanking.objects.filter(genre=genre, album__isnull=False).select_related("album").order_by("rank"):
        if row.album_id in seen:
            continue
        seen.add(row.album_id)
        year = row.album.year
        groups[year // 10 * 10 if year else None].append(row.album)
    dated = sorted((d, a) for d, a in groups.items() if d is not None)
    return dated + ([(None, groups[None])] if None in groups else [])
