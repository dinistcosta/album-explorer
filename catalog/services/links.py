"""Listen / buy / official / social links from MusicBrainz url-relationships."""
from urllib.parse import quote_plus, urlparse

from django.db import transaction

from catalog.models import Album, ExternalLink
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


def import_album_links(album: Album) -> None:
    found = _classified(mb.get_release_group(str(album.mbid)).get("relations"))
    if not any(kind == "listen" for kind, _ in found.values()) and album.reference_release:
        # Only the reference release: one extra request, not one per edition.
        for url, kind in _classified(mb.get_release(str(album.reference_release.mbid)).get("relations")).items():
            found.setdefault(url, kind)
    with transaction.atomic():
        for url, (kind, service) in found.items():
            ExternalLink.objects.update_or_create(
                album=album, url=url, defaults={"kind": kind, "service": service})
        album.links.exclude(url__in=list(found)).delete()


def discogs_search_url(artist: str, title: str) -> str:
    return f"https://www.discogs.com/search/?q={quote_plus(artist)}+{quote_plus(title)}&type=all"


def listen_and_buy(album: Album) -> tuple[list[dict], list[dict]]:
    """Display data for the hero: one listen link per service (fixed order), buy links (Bandcamp, Discogs search)."""
    by_service = {}
    for link in album.links.filter(kind="listen").order_by("id"):
        by_service.setdefault(link.service, link.url)
    listen = [{"service": s, "name": SERVICE_NAMES[s], "url": by_service[s]}
              for s in LISTEN_ORDER if s in by_service]
    buy = [item for item in listen if item["service"] == "bandcamp"]
    return listen, buy


register_album_enricher(import_album_links)
