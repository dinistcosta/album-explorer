"""Listen / buy / official / social links from MusicBrainz url-relationships."""
from urllib.parse import quote_plus, urlparse

from django.db import transaction

from catalog.models import Album, ExternalLink
from catalog.services.manual import manual_keys
from catalog.tasks import register_album_enricher
from sources import musicbrainz as mb

# (host suffix, kind, service); first match wins.
RULES = [
    ("open.spotify.com", "listen", "spotify"),
    ("music.apple.com", "listen", "apple_music"),
    ("itunes.apple.com", "listen", "apple_music"),
    ("music.youtube.com", "listen", "youtube"),
    ("youtube.com", "listen", "youtube"),
    ("youtu.be", "listen", "youtube"),
    ("bandcamp.com", "listen", "bandcamp"),
    ("instagram.com", "social", "instagram"),
    ("facebook.com", "social", "facebook"),
    ("twitter.com", "social", "x"),
    ("x.com", "social", "x"),
    ("tiktok.com", "social", "tiktok"),
    ("soundcloud.com", "social", "soundcloud"),
]
SERVICE_NAMES = {"spotify": "Spotify", "apple_music": "Apple Music", "youtube": "YouTube", "bandcamp": "Bandcamp"}
LISTEN_ORDER = list(SERVICE_NAMES)


def classify_url(url: str, rel_type: str = "") -> tuple[str, str] | None:
    """Bandcamp is also a buy link, but a stored row has one kind, so the buy side is derived at render time."""
    host = (urlparse(url).hostname or "").lower()
    for suffix, kind, service in RULES:
        if host == suffix or host.endswith("." + suffix):
            return kind, service
    if rel_type == "official homepage":
        return "official", "website"
    return None


def _classified(relations) -> dict[str, tuple[str, str]]:
    found = {}
    for rel in relations or []:
        url = (rel.get("url") or {}).get("resource") or ""
        kind = classify_url(url, rel.get("type") or "") if url else None
        if kind:
            found.setdefault(url, kind)
    return found


MAX_STREAMING_RELEASES = 5


def _streaming_candidates(album: Album) -> list:
    """Streaming links in MusicBrainz live on digital releases (often not the reference one, which
    may be a cassette): official digital releases first, newest-known markets last, a few at most."""
    digital = [r for r in album.releases.all() if "Digital Media" in (r.formats or [])]
    digital.sort(key=lambda r: (r.status != "Official", r.country not in ("XW", "US"), r.date or "9999"))
    return digital[:MAX_STREAMING_RELEASES]


def _has(found: dict, service: str) -> bool:
    return any(kind == "listen" and svc == service for kind, svc in found.values())


def import_album_links(album: Album) -> None:
    found = _classified(mb.get_release_group(str(album.mbid)).get("relations"))
    if not any(kind == "listen" for kind, _ in found.values()):
        candidates = _streaming_candidates(album)
        if album.reference_release and all(r.pk != album.reference_release_id for r in candidates):
            candidates.append(album.reference_release)
        # A handful of requests at most (never one per edition); stop once the main services are covered.
        for release in candidates:
            for url, kind in _classified(mb.get_release(str(release.mbid)).get("relations")).items():
                found.setdefault(url, kind)
            if _has(found, "spotify") and _has(found, "apple_music"):
                break
    with transaction.atomic():
        store_links(album.links, {"album": album}, found)


def store_links(related, owner: dict, found: dict[str, tuple[str, str]]) -> None:
    """Upsert imported links and drop the imported ones the source no longer lists.
    Manual and hidden rows are never touched, and block an imported row with the same url."""
    manual = manual_keys(related.all())
    for url, (kind, service) in found.items():
        if url not in manual:
            ExternalLink.objects.update_or_create(**owner, url=url, defaults={"kind": kind, "service": service})
    related.filter(is_manual=False).exclude(url__in=list(found)).delete()


def discogs_search_url(artist: str, title: str) -> str:
    return f"https://www.discogs.com/search/?q={quote_plus(artist)}+{quote_plus(title)}&type=all"


def listen_and_buy(album: Album) -> tuple[list[dict], list[dict]]:
    """Display data for the hero: one listen link per service (fixed order), buy links (Bandcamp, Discogs search)."""
    by_service = {}
    for link in album.links.filter(kind="listen", is_hidden=False).order_by("id"):
        by_service.setdefault(link.service, link.url)
    listen = [{"service": s, "name": SERVICE_NAMES[s], "url": by_service[s]}
              for s in LISTEN_ORDER if s in by_service]
    buy = [item for item in listen if item["service"] == "bandcamp"]
    return listen, buy


register_album_enricher(import_album_links)
