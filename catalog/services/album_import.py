from django.db import transaction
from django.utils import timezone

from catalog.models import Album, Artist, Credit, Place, Release, Track
from sources import musicbrainz as mb

from .editions import assign_sides, choose_reference_release, vinyl_candidates

MAX_VINYL_CANDIDATES = 3

# MusicBrainz relation type -> stored role (anything not listed is ignored)
ARTIST_ROLES = {
    "producer": "producer",
    "mix": "mix",
    "engineer": "engineer",
    "recording engineer": "recording engineer",
    "audio": "audio",
    "instrument": "instrument",
    "vocal": "vocal",
}


def _year(date: str | None) -> int | None:
    head = (date or "")[:4]
    return int(head) if head.isdigit() else None


def _artist_values(data: dict) -> dict:
    return {
        "name": data.get("name", ""),
        "sort_name": data.get("sort-name") or "",
        "country": data.get("country") or "",
        "artist_type": data.get("type") or "",
    }


def _upsert_artist(data: dict) -> Artist:
    artist, _ = Artist.objects.get_or_create(mbid=data["id"], defaults=_artist_values(data))
    changed = artist.apply_source_fields(**_artist_values(data))
    if changed:
        artist.save()
    return artist


def _release_values(data: dict) -> dict:
    media = data.get("media") or []
    labels = [li["label"]["name"] for li in data.get("label-info") or [] if li.get("label")]
    return {
        "title": data.get("title", ""),
        "date": data.get("date") or "",
        "country": data.get("country") or "",
        "status": data.get("status") or "",
        "formats": [m.get("format") or "" for m in media],
        "label": labels[0] if labels else "",
        "track_count": sum(m.get("track-count", len(m.get("tracks") or [])) for m in media),
    }


def _relations(reference: dict):
    """Yield (position_key_or_None, relation) for release- and recording-level relations."""
    for rel in reference.get("relations") or []:
        yield None, rel
    for medium in reference.get("media") or []:
        for track in medium.get("tracks") or []:
            key = (medium.get("position", 1), track.get("position"))
            for rel in (track.get("recording") or {}).get("relations") or []:
                yield key, rel


def _collect_credits(reference: dict) -> list[dict]:
    seen, out = set(), []
    for key, rel in _relations(reference):
        rtype, target = rel.get("type"), rel.get("target-type")
        attrs = list(rel.get("attributes") or [])
        if target == "artist" and rtype in ARTIST_ROLES and rel.get("artist"):
            entry = {"key": key, "role": ARTIST_ROLES[rtype], "attributes": attrs, "artist": rel["artist"]}
            ident = (key, entry["role"], tuple(attrs), rel["artist"]["id"])
        elif target == "place" and rtype == "recorded at" and rel.get("place"):
            entry = {"key": key, "role": "recorded at", "attributes": attrs, "place": rel["place"]}
            ident = (key, "recorded at", tuple(attrs), rel["place"]["id"])
        else:
            continue
        if ident not in seen:
            seen.add(ident)
            out.append(entry)
    return out


def import_album_core(mbid: str, *, foreground: bool) -> Album:
    # All network I/O first: the throttle holds a row lock while reserving a slot.
    group = mb.get_release_group(mbid, foreground=foreground)
    releases = mb.browse_releases(mbid, foreground=foreground)
    reference = None
    if releases:
        ref_id = choose_reference_release(releases)["id"]
        reference = mb.get_release(ref_id, foreground=foreground)

    credit_entries = _collect_credits(reference) if reference else []
    credit = (group.get("artist-credit") or [{}])[0]

    with transaction.atomic():
        artist = _upsert_artist(credit["artist"]) if credit.get("artist") else None
        album, _ = Album.objects.get_or_create(mbid=group["id"], defaults={"title": group.get("title", "")})
        album.apply_source_fields(
            title=group.get("title", ""),
            artist=artist,
            artist_credit="".join(
                (c.get("name") or c.get("artist", {}).get("name", "")) + (c.get("joinphrase") or "")
                for c in group.get("artist-credit") or []
            ),
            year=_year(group.get("first-release-date")),
            primary_type=group.get("primary-type") or "",
            secondary_types=group.get("secondary-types") or [],
            imported_at=timezone.now(),
        )

        release_rows = {}
        for data in releases:
            row, _ = Release.objects.update_or_create(
                mbid=data["id"], defaults={"album": album, **_release_values(data)}
            )
            release_rows[data["id"]] = row

        tracks = {}
        if reference:
            ref_row = release_rows[reference["id"]]
            for name, value in _release_values(reference).items():
                setattr(ref_row, name, value)
            ref_row.save()
            album.reference_release = ref_row
            keep = []
            for medium in reference.get("media") or []:
                for t in medium.get("tracks") or []:
                    disc, pos = medium.get("position", 1), t["position"]
                    track, _ = Track.objects.update_or_create(
                        release=ref_row, disc=disc, position=pos,
                        defaults={
                            "number": t.get("number") or "",
                            "title": t.get("title", ""),
                            "length_ms": t.get("length"),
                            "recording_mbid": (t.get("recording") or {}).get("id"),
                        },
                    )
                    tracks[(disc, pos)] = track
                    keep.append(track.pk)
            ref_row.tracks.exclude(pk__in=keep).delete()
        album.save()

        Credit.objects.filter(album=album, is_manual=False).delete()
        for entry in credit_entries:
            person = place = None
            if "artist" in entry:
                person = _upsert_artist(entry["artist"])
            else:
                p = entry["place"]
                place, _ = Place.objects.get_or_create(mbid=p["id"], defaults={"name": p.get("name", "")})
                area = (p.get("area") or {}).get("name") or ""
                if place.name != p.get("name", "") or place.area != area:
                    place.name, place.area = p.get("name", ""), area
                    place.save()
            Credit.objects.create(
                album=album, track=tracks.get(entry["key"]) if entry["key"] else None,
                person=person, place=place, role=entry["role"], attributes=entry["attributes"],
            )
    return album


def _as_release_dict(release: Release) -> dict:
    return {
        "id": str(release.mbid), "date": release.date, "status": release.status,
        "media": [{"format": f} for f in release.formats],
    }


def apply_vinyl_sides(album: Album) -> None:
    reference = album.reference_release
    if reference is None:
        return
    ref_dict = {"media": [{"tracks": [
        {"number": t.number, "title": t.title, "recording": {"id": str(t.recording_mbid)}}
        for t in reference.tracks.all() if t.recording_mbid
    ]}]}
    others = [_as_release_dict(r) for r in album.releases.exclude(pk=reference.pk)]
    sides = None
    for candidate in vinyl_candidates(others)[:MAX_VINYL_CANDIDATES]:
        sides = assign_sides(ref_dict, mb.get_release(candidate["id"]))
        if sides:
            break
    with transaction.atomic():
        for track in reference.tracks.all():
            side = sides.get(str(track.recording_mbid)) if sides else None
            if track.side != side:
                track.side = side
                track.save(update_fields=["side"])
