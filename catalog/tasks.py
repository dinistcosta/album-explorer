"""Background tasks (Django 6 `django.tasks`, database backend from `django-tasks-db`).

Run the worker with `python manage.py db_worker`.

Enrichers are plain callables `fn(obj) -> None`. Each module that provides one calls
`register_album_enricher` / `register_artist_enricher` at import time; `CatalogConfig.ready()`
imports those modules.
"""
import logging
from collections.abc import Callable

from django.tasks import task
from django.utils import timezone

from .models import Album, Artist
from .services.album_import import apply_vinyl_sides
from .services.color import apply_cover_and_accent

logger = logging.getLogger(__name__)

ALBUM_ENRICHERS: list[Callable[[Album], None]] = []
ARTIST_ENRICHERS: list[Callable[[Artist], None]] = []


def register_album_enricher(fn):
    ALBUM_ENRICHERS.append(fn)
    return fn


def register_artist_enricher(fn):
    ARTIST_ENRICHERS.append(fn)
    return fn


register_album_enricher(apply_vinyl_sides)
register_album_enricher(apply_cover_and_accent)


def _run_enrichers(obj, enrichers) -> None:
    for fn in list(enrichers):
        try:
            fn(obj)
        except Exception:  # SourceUnavailable, Pillow errors, bugs: log and carry on
            logger.exception("enricher %s failed for %r", getattr(fn, "__name__", fn), obj)
    obj.enriched_at = timezone.now()
    obj.save(update_fields=["enriched_at"])


@task
def enrich_album(album_id: int) -> None:
    album = Album.objects.filter(pk=album_id).first()
    if album is not None:
        _run_enrichers(album, ALBUM_ENRICHERS)


@task
def enrich_artist(artist_id: int) -> None:
    artist = Artist.objects.filter(pk=artist_id).first()
    if artist is not None:
        _run_enrichers(artist, ARTIST_ENRICHERS)


@task
def resolve_genre_room(genre_id: int) -> None:
    """Refresh a genre room's Last.fm ranking and resolve its rows to MusicBrainz release groups."""
    from sources import lastfm
    from sources.http import SourceUnavailable

    from .models import Genre
    from .services import genres_room

    genre = Genre.objects.filter(pk=genre_id).first()
    if genre is None:
        return
    try:
        items = lastfm.tag_top_albums(genre.name, 100)
        if items:
            genres_room.store_rankings(genre, items)
        genres_room.resolve_rankings(genre)
    except SourceUnavailable:
        logger.warning("genre room %s: source unavailable", genre.slug)
