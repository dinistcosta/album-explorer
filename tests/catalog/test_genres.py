import pytest

from catalog.models import AlbumGenre, Genre
from catalog.services.genres import attach_genres, import_album_genres, match_genre


def test_match_genre_normalises(db):
    Genre.objects.create(slug="hip-hop", name="hip hop")
    assert match_genre("Hip-Hop")
    assert match_genre("hiphop")


def test_match_genre_ampersand(db):
    Genre.objects.create(slug="rock-and-roll", name="Rock and Roll")
    assert match_genre("Rock & Roll")


def test_unknown_tag_ignored(db):
    Genre.objects.create(slug="rock", name="rock")
    assert match_genre("seen live") is None


def test_attach_genres_replaces_per_source(db, album_factory):
    album = album_factory()
    rock = Genre.objects.create(slug="rock", name="rock")
    grunge = Genre.objects.create(slug="grunge", name="grunge")
    attach_genres(album, ["Rock", "seen live"], "lastfm")
    attach_genres(album, ["grunge"], "musicbrainz")
    attach_genres(album, ["Grunge"], "lastfm")
    assert sorted(AlbumGenre.objects.values_list("genre__slug", "source")) == [
        ("grunge", "lastfm"), ("grunge", "musicbrainz")]
    assert rock.pk and grunge.pk


def test_import_album_genres_three_sources(db, album_factory, monkeypatch):
    album = album_factory(discogs_styles=["Grunge"])
    for n in ("alternative rock", "grunge", "rock"):
        Genre.objects.create(slug=n.replace(" ", "-"), name=n)
    monkeypatch.setattr("catalog.services.genres.mb.get_release_group",
                        lambda mbid: {"genres": [{"name": "alternative rock"}, {"name": "rock"}]})
    monkeypatch.setattr("catalog.services.genres.lastfm.album_top_tags", lambda a, t: ["rock", "seen live"])
    import_album_genres(album)
    assert sorted(AlbumGenre.objects.values_list("genre__slug", "source")) == [
        ("alternative-rock", "musicbrainz"), ("grunge", "discogs"), ("rock", "lastfm"), ("rock", "musicbrainz")]
