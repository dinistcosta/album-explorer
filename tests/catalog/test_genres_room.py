import uuid
from datetime import datetime, timezone

import httpx
import pytest
import respx

from catalog.models import Album, Genre, GenreRanking
from catalog.services.genres_room import room_by_decade
from catalog.tasks import resolve_genre_room

MB = "https://musicbrainz.org/ws/2/"
LASTFM = "https://ws.audioscrobbler.com/2.0/"
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fast(no_sleep):
    pass


@pytest.fixture
def genre_with_ranked_albums(genre_factory, album_factory):
    genre = genre_factory(name="shoegaze", description="Barulho bonito.",
                          description_source_url="https://www.last.fm/tag/shoegaze")
    for rank, year in enumerate([1991, None, 1967, 1994, 1991], start=1):
        album = album_factory(year=year, title=f"Disco {rank}")
        GenreRanking.objects.create(genre=genre, rank=rank, lastfm_artist="A", lastfm_title=album.title,
                                    album=album, resolved_at=NOW)
    return genre


@pytest.fixture
def genre_with_unresolved(genre_factory):
    genre = genre_factory(name="shoegaze")
    GenreRanking.objects.create(genre=genre, rank=1, lastfm_artist="Slowdive", lastfm_title="Souvlaki")
    return genre


@pytest.fixture
def enqueued_rooms(monkeypatch):
    calls = []
    monkeypatch.setattr("catalog.views.enqueue_room", lambda genre: calls.append(genre.pk))
    return calls


def test_room_groups_by_decade(genre_with_ranked_albums):
    groups = room_by_decade(genre_with_ranked_albums)
    assert [d for d, _ in groups] == [1960, 1990, None]
    assert [a.title for a in groups[1][1]] == ["Disco 1", "Disco 4", "Disco 5"]  # by rank


def test_room_hides_numbers_and_labels_decades(client, genre_with_ranked_albums, enqueued_rooms):
    html = client.get("/pt/genre/shoegaze/").content.decode()
    assert "listeners" not in html and "ouvintes" not in html
    for label in ("Anos 60", "Anos 90", "Sem data"):
        assert label in html
    assert "ainda está a ser montada" not in html
    assert enqueued_rooms == []
    en = client.get("/en/genre/shoegaze/").content.decode()
    assert "1960s" in en and "1990s" in en and "Undated" in en


def test_room_shows_description_with_source(client, genre_with_ranked_albums, enqueued_rooms):
    html = client.get("/pt/genre/shoegaze/").content.decode()
    assert "Barulho bonito." in html
    assert 'href="https://www.last.fm/tag/shoegaze"' in html and "CC BY-SA" in html


def test_incomplete_room_notice(client, genre_with_unresolved, enqueued_rooms):
    html = client.get("/pt/genre/shoegaze/").content.decode()
    assert "Esta sala ainda está a ser montada." in html
    assert enqueued_rooms == [genre_with_unresolved.pk]


def test_unknown_genre_404(client, db):
    assert client.get("/pt/genre/nope/").status_code == 404


def test_album_page_genre_chip_links_to_room(client, album_factory, genre_factory, enqueued):
    from catalog.models import AlbumGenre

    album = album_factory()
    genre = genre_factory(name="shoegaze")
    AlbumGenre.objects.create(album=album, genre=genre, source="musicbrainz")
    html = client.get(f"/pt/album/{album.mbid}/").content.decode()
    assert 'href="/pt/genre/shoegaze/"' in html


# --- resolution ---

def rg(title, artist, mbid=None, date="1993-06-01"):
    return {"id": str(mbid or uuid.uuid4()), "title": title, "first-release-date": date,
            "primary-type": "Album", "secondary-types": [],
            "artist-credit": [{"name": artist, "joinphrase": "", "artist": {"id": str(uuid.uuid4()), "name": artist}}]}


@pytest.fixture
def room_respx(settings):
    settings.LASTFM_API_KEY = "k"
    with respx.mock(assert_all_called=False) as router:
        router.tag = router.get(LASTFM).respond(json={"albums": {"album": [
            {"name": "Souvlaki", "artist": {"name": "Slowdive"}},
            {"name": "Loveless", "artist": {"name": "My Bloody Valentine"}},
        ]}})
        router.mb = router.get(url__startswith=MB + "release-group")
        yield router


def test_resolution_accepts_match(genre_factory, room_respx):
    genre = genre_factory(name="shoegaze")
    mbid = uuid.uuid4()
    room_respx.mb.mock(side_effect=lambda req: httpx.Response(200, json={"release-groups": [
        rg("Souvlaki" if "Souvlaki" in req.url.params["query"] else "Loveless",
           "Slowdive" if "Souvlaki" in req.url.params["query"] else "My Bloody Valentine",
           mbid if "Souvlaki" in req.url.params["query"] else None)]}))
    resolve_genre_room.call(genre.pk)
    rows = list(GenreRanking.objects.filter(genre=genre))
    assert [r.rank for r in rows] == [1, 2]
    assert rows[0].album.mbid == mbid and rows[0].album.year == 1993
    assert all(r.resolved_at for r in rows)
    resolve_genre_room.call(genre.pk)  # idempotent
    assert GenreRanking.objects.filter(genre=genre).count() == 2 and Album.objects.count() == 2


def test_resolution_rejects_mismatched_artist(genre_factory, room_respx):
    genre = genre_factory(name="shoegaze")
    room_respx.mb.respond(json={"release-groups": [rg("Souvlaki", "Slowdive Tribute Band")]})
    resolve_genre_room.call(genre.pk)
    row = GenreRanking.objects.get(genre=genre, rank=1)
    assert row.album is None and row.resolved_at is not None  # decided, not retried forever


def test_resolution_rejects_mismatched_title(genre_factory, room_respx):
    genre = genre_factory(name="shoegaze")
    room_respx.mb.respond(json={"release-groups": [rg("Souvlaki Live", "Slowdive")]})
    resolve_genre_room.call(genre.pk)
    assert GenreRanking.objects.get(genre=genre, rank=1).album is None


def test_resolution_accepts_parenthetical_suffix(genre_factory, room_respx):
    genre = genre_factory(name="shoegaze")
    room_respx.mb.respond(json={"release-groups": [rg("Souvlaki (Remastered)", "Slowdive")]})
    resolve_genre_room.call(genre.pk)
    assert GenreRanking.objects.get(genre=genre, rank=1).album.title == "Souvlaki (Remastered)"


def test_resolution_uses_background_priority_and_escapes(genre_factory, room_respx, monkeypatch):
    genre = genre_factory(name="shoegaze")
    room_respx.tag.respond(json={"albums": {"album": [{"name": 'Say "Hi"', "artist": {"name": "AC/DC"}}]}})
    room_respx.mb.respond(json={"release-groups": []})
    seen = {}
    from sources import musicbrainz as mb
    real = mb.search_release_groups

    def spy(query, **kw):
        seen.update(query=query, **kw)
        return real(query, **kw)

    monkeypatch.setattr("catalog.services.genres_room.mb.search_release_groups", spy)
    resolve_genre_room.call(genre.pk)
    assert seen["foreground"] is False and seen["raw"] is True and seen["limit"] == 1
    assert seen["query"] == r'releasegroup:"Say \"Hi\"" AND artist:"AC\/DC"'


def test_resolution_source_down_leaves_rows_unresolved(genre_factory, room_respx):
    genre = genre_factory(name="shoegaze")
    room_respx.mb.respond(503)
    resolve_genre_room.call(genre.pk)  # no exception
    assert GenreRanking.objects.filter(genre=genre, resolved_at__isnull=True).count() == 2


def test_resolution_without_lastfm_key_is_noop(genre_factory, settings):
    settings.LASTFM_API_KEY = ""
    genre = genre_factory(name="shoegaze")
    resolve_genre_room.call(genre.pk)
    assert GenreRanking.objects.count() == 0


def test_room_enqueue_dedupes(genre_factory, settings, db):
    from catalog.services.refresh import enqueue_room

    settings.TASKS = {"default": {"BACKEND": "django_tasks_db.DatabaseBackend"}}
    from django_tasks_db.models import DBTaskResult

    genre = genre_factory(name="shoegaze")
    enqueue_room(genre)
    enqueue_room(genre)
    assert DBTaskResult.objects.count() == 1


def test_band_page_genre_chip_links_to_room(client, artist_factory, genre_factory, enqueued):
    from catalog.models import ArtistGenre

    artist = artist_factory(imported_at=NOW)
    ArtistGenre.objects.create(artist=artist, genre=genre_factory(name="shoegaze"), source="musicbrainz")
    html = client.get(f"/pt/artist/{artist.mbid}/").content.decode()
    assert 'href="/pt/genre/shoegaze/"' in html


def test_english_description_flagged_for_pt_readers(client, genre_with_ranked_albums, enqueued_rooms):
    assert "Disponível apenas em inglês" in client.get("/pt/genre/shoegaze/").content.decode()
    assert "Only available in English" not in client.get("/en/genre/shoegaze/").content.decode()
    genre_with_ranked_albums.description_lang = "pt"
    genre_with_ranked_albums.save()
    assert "Disponível apenas em inglês" not in client.get("/pt/genre/shoegaze/").content.decode()
    assert "Only available in Portuguese" in client.get("/en/genre/shoegaze/").content.decode()


def test_decade_labels(settings):
    from django.utils import translation

    from catalog.views import _decade_label

    with translation.override("pt"):
        assert [_decade_label(d) for d in (1900, 1960, 2010)] == ["Anos 1900", "Anos 60", "Anos 2010"]
    with translation.override("en"):
        assert [_decade_label(d) for d in (1900, 1960, 2010)] == ["1900s", "1960s", "2010s"]
