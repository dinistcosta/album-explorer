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


def test_significant_genre_names_drops_low_vote_noise():
    from catalog.services.genres import significant_genre_names

    names = significant_genre_names([
        {"name": "hip hop", "count": 1}, {"name": "grunge", "count": 68}, {"name": "rock", "count": 26},
        {"name": "alternative rock", "count": 30}, {"name": "noise rock", "count": 12},
        {"name": "psytrance", "count": 1}])
    assert names == ["grunge", "alternative rock", "rock"]  # floor is max(2, 25% of 68) = 17, most-voted first


def test_significant_genre_names_floor_and_cap():
    from catalog.services.genres import significant_genre_names

    small = significant_genre_names([{"name": "a", "count": 3}, {"name": "b", "count": 2}, {"name": "c", "count": 1}])
    assert small == ["a", "b"]  # small top count: floor stays at 2
    many = significant_genre_names([{"name": f"g{i}", "count": 10} for i in range(12)])
    assert len(many) == 8
    assert significant_genre_names([{"name": "x"}, {"name": "y"}]) == ["x", "y"]  # no counts: keep
    assert significant_genre_names(None) == []


def test_import_album_genres_ignores_low_vote_musicbrainz_genres(db, album_factory, monkeypatch):
    album = album_factory()
    genre_factory_names = ["grunge", "hip hop"]
    for n in genre_factory_names:
        Genre.objects.create(slug=n.replace(" ", "-"), name=n, search_name=n)
    monkeypatch.setattr("catalog.services.genres.mb.get_release_group", lambda mbid: {
        "genres": [{"name": "grunge", "count": 48}, {"name": "hip hop", "count": 1}]})
    monkeypatch.setattr("catalog.services.genres.lastfm.album_top_tags", lambda a, t: [])
    import_album_genres(album)
    assert list(album.album_genres.values_list("genre__slug", flat=True)) == ["grunge"]
