"""Band page data: artist fields, links, MusicBrainz genres, members and album stubs."""
from django.db import transaction
from django.utils import timezone

from catalog.models import Album, Artist, ExternalLink, Membership
from catalog.services.album_import import _artist_values, _upsert_artist, _year
from catalog.services.genres import attach_genres, significant_genre_names
from catalog.services.links import classify_url
from catalog.tasks import register_artist_enricher
from sources import musicbrainz as mb
from sources.wikidata import wikidata_id_from_rels

SECTION_ORDER = ["studio", "ep", "live", "compilation", "other"]
# Membership attributes that describe the stint, not an instrument.
NOT_INSTRUMENTS = {"original"}


def release_group_kind(primary: str, secondary: list[str]) -> str:
    if "Live" in secondary:
        return "live"
    if "Compilation" in secondary:
        return "compilation"
    if secondary:
        return "other"
    if primary == "EP":
        return "ep"
    if primary == "Album":
        return "studio"
    return "other"


def _classified_links(relations) -> dict[str, tuple[str, str]]:
    found = {}
    for rel in relations or []:
        url = (rel.get("url") or {}).get("resource") or ""
        kind = classify_url(url, rel.get("type") or "") if url else None
        if kind:
            found.setdefault(url, kind)
    return found


def _discogs_id(relations) -> str:
    for rel in relations or []:
        url = (rel.get("url") or {}).get("resource") or ""
        if rel.get("type") == "discogs" and "/artist/" in url:
            digits = url.rsplit("/artist/", 1)[1].split("-")[0].split("/")[0]
            if digits.isdigit():
                return digits
    return ""


def _collect_members(relations) -> list[dict]:
    """One entry per (member, begin, end); instruments merged across the duplicated relations."""
    merged: dict[tuple, dict] = {}
    for rel in relations or []:
        if rel.get("type") != "member of band" or rel.get("direction") != "backward" or not rel.get("artist"):
            continue
        key = (rel["artist"]["id"], _year(rel.get("begin")), _year(rel.get("end")))
        entry = merged.setdefault(key, {"artist": rel["artist"], "begin": key[1], "end": key[2], "instruments": []})
        for attr in rel.get("attributes") or []:
            if attr not in NOT_INSTRUMENTS and attr not in entry["instruments"]:
                entry["instruments"].append(attr)
    return list(merged.values())


def _upsert_stubs(artist: Artist, groups: list[dict]) -> None:
    existing = {str(a.mbid): a for a in Album.objects.filter(mbid__in=[g["id"] for g in groups])}
    for group in groups:
        album = existing.get(group["id"])
        if album is None:
            album = Album.objects.create(
                mbid=group["id"], title=group.get("title", ""), artist=artist, artist_credit=artist.name)
        changed = album.apply_source_fields(
            title=group.get("title", ""),
            year=_year(group.get("first-release-date")),
            primary_type=group.get("primary-type") or "",
            secondary_types=group.get("secondary-types") or [],
        )
        if changed:
            album.save(update_fields=changed)


def import_artist_core(mbid: str, *, foreground: bool) -> Artist:
    # All network I/O first: the throttle holds a row lock while reserving a slot.
    data = mb.get_artist(str(mbid), foreground=foreground)
    groups = mb.browse_release_groups(str(mbid), foreground=foreground)
    relations = data.get("relations") or []
    life = data.get("life-span") or {}
    links = _classified_links(relations)
    members = _collect_members(relations)

    with transaction.atomic():
        artist, _ = Artist.objects.get_or_create(mbid=data["id"], defaults=_artist_values(data))
        values = {
            **_artist_values(data),
            "begin_year": _year(life.get("begin")),
            "end_year": _year(life.get("end")),
            "imported_at": timezone.now(),
        }
        qid = wikidata_id_from_rels(relations)
        if qid:
            values["wikidata_id"] = qid
        discogs = _discogs_id(relations)
        if discogs:
            values["discogs_id"] = discogs
        artist.apply_source_fields(**values)
        artist.save()

        for url, (kind, service) in links.items():
            ExternalLink.objects.update_or_create(artist=artist, url=url, defaults={"kind": kind, "service": service})
        artist.links.exclude(url__in=list(links)).delete()

        artist.memberships.all().delete()
        for m in members:
            member = _upsert_artist(m["artist"])
            if member.pk != artist.pk:
                Membership.objects.create(
                    band=artist, member=member, begin_year=m["begin"], end_year=m["end"],
                    instruments=m["instruments"])

        _upsert_stubs(artist, groups)

    attach_genres(artist, significant_genre_names(data.get("genres")), "musicbrainz")
    return artist


def refresh_artist_core(artist: Artist) -> None:
    import_artist_core(str(artist.mbid), foreground=False)


# Last, so the Wikidata/story enrichers run on the freshly refreshed fields next time round.
register_artist_enricher(refresh_artist_core)


def discography_sections(artist: Artist) -> list[tuple[str, list[Album]]]:
    buckets: dict[str, list[Album]] = {key: [] for key in SECTION_ORDER}
    for album in artist.albums.all():
        buckets[release_group_kind(album.primary_type, album.secondary_types or [])].append(album)
    return [
        (key, sorted(buckets[key], key=lambda a: (a.year is None, a.year or 0, a.title)))
        for key in SECTION_ORDER
    ]


def header_cover_album(artist: Artist) -> Album | None:
    studio = dict(discography_sections(artist))["studio"]
    if not studio:
        return None
    return max(studio, key=lambda a: a.lastfm_listeners or 0) if any(a.lastfm_listeners for a in studio) else studio[0]
