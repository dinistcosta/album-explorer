from datetime import timedelta

from django.utils import timezone
from django_tasks_db.models import DBTaskResult

from catalog import tasks
from catalog.services import refresh
from catalog.services.album_import import apply_vinyl_sides
from catalog.services.color import apply_cover_and_accent


def boom(obj):
    raise RuntimeError("boom")


def test_enrichers_registered_in_order():
    assert tasks.ALBUM_ENRICHERS[:2] == [apply_vinyl_sides, apply_cover_and_accent]
    assert tasks.ARTIST_ENRICHERS == []


def test_failing_enricher_does_not_stop_others(db, imported_album, monkeypatch):
    calls = []
    monkeypatch.setattr(tasks, "ALBUM_ENRICHERS", [boom, lambda a: calls.append(a.pk)])
    tasks.enrich_album.call(imported_album.pk)
    imported_album.refresh_from_db()
    assert calls == [imported_album.pk] and imported_album.enriched_at is not None


def test_failing_artist_enricher_does_not_stop_others(db, artist_factory, monkeypatch):
    artist = artist_factory()
    calls = []
    monkeypatch.setattr(tasks, "ARTIST_ENRICHERS", [boom, lambda a: calls.append(a.pk)])
    tasks.enrich_artist.call(artist.pk)
    artist.refresh_from_db()
    assert calls == [artist.pk] and artist.enriched_at is not None


def test_missing_object_is_ignored(db):
    tasks.enrich_album.call(999999)
    tasks.enrich_artist.call(999999)
    tasks.resolve_genre_room.call(999999)


def test_needs_enrichment(album_factory):
    album = album_factory()
    assert refresh.needs_enrichment(album)
    album.enriched_at = timezone.now()
    assert not refresh.needs_enrichment(album)
    album.enriched_at = timezone.now() - timedelta(days=31)
    assert refresh.needs_enrichment(album)


def test_enqueue_dedupes_queued_task(db, settings, album_factory):
    settings.TASKS = {"default": {"BACKEND": "django_tasks_db.DatabaseBackend"}}
    album = album_factory()
    refresh.enqueue_enrichment(album)
    refresh.enqueue_enrichment(album)
    assert DBTaskResult.objects.count() == 1
    refresh.enqueue_enrichment(album_factory())
    assert DBTaskResult.objects.count() == 2


def test_visit_enqueues_when_stale(client, imported_album, enqueued):
    imported_album.enriched_at = timezone.now() - timedelta(days=31)
    imported_album.save()
    client.get(imported_album.get_absolute_url())
    assert enqueued == [("enrich_album", imported_album.pk)]


def test_visit_does_not_enqueue_when_fresh(client, imported_album, enqueued):
    imported_album.enriched_at = timezone.now()
    imported_album.save()
    client.get(imported_album.get_absolute_url())
    assert enqueued == []


def test_first_visit_enqueues_after_import(client, db, mb_fixtures, enqueued):
    from tests.ids import NEVERMIND_RG

    client.get(f"/pt/album/{NEVERMIND_RG}/")
    assert len(enqueued) == 1 and enqueued[0][0] == "enrich_album"


def test_enrichment_endpoint_enqueues_when_unenriched(client, imported_album, enqueued):
    client.get(f"/pt/album/{imported_album.mbid}/sections/")
    assert enqueued == [("enrich_album", imported_album.pk)]
