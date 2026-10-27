import pytest
from django.db import IntegrityError

from catalog.models import AlbumGenre, Genre
from catalog.services.text import normalize


def test_apply_source_fields_skips_locked(db, album_factory):
    a = album_factory(title="Old", locked_fields=["title"])
    changed = a.apply_source_fields(title="New", year=1991)
    assert a.title == "Old" and a.year == 1991 and changed == ["year"]


def test_apply_source_fields_reports_only_real_changes(db, album_factory):
    a = album_factory(year=1991)
    assert a.apply_source_fields(year=1991) == []


def test_normalize():
    assert normalize("Sigur Rós") == "sigur ros"
    assert normalize("AC/DC") == "ac dc"
    assert normalize("  Hello,   World!! ") == "hello world"


def test_search_name_set_on_save(db, album_factory, artist_factory):
    artist = artist_factory(name="Sigur Rós")
    assert artist.search_name == "sigur ros"
    album = album_factory(title="Ágætis byrjun", artist=artist)
    assert album.search_name == normalize("Ágætis byrjun")


def test_album_without_artist(db, album_factory):
    assert album_factory(artist=None).artist is None


def test_album_genre_unique_per_triple(db, album_factory):
    album = album_factory()
    genre = Genre.objects.create(slug="grunge", name="Grunge")
    AlbumGenre.objects.create(album=album, genre=genre, source="musicbrainz")
    with pytest.raises(IntegrityError):
        AlbumGenre.objects.create(album=album, genre=genre, source="musicbrainz")
