import json
from pathlib import Path

import httpx
import pytest
import respx

from catalog.models import ExternalLink
from catalog.services.links import classify_url, import_album_links

FIXMB = Path(__file__).parent.parent / "fixtures" / "musicbrainz"
MB = "https://musicbrainz.org/ws/2/"


@pytest.mark.parametrize("url,expected", [
    ("https://open.spotify.com/album/x", ("listen", "spotify")),
    ("https://music.apple.com/pt/album/x", ("listen", "apple_music")),
    ("https://music.youtube.com/playlist?list=x", ("listen", "youtube")),
    ("https://www.youtube.com/playlist?list=x", ("listen", "youtube")),
    ("https://band.bandcamp.com/album/x", ("listen", "bandcamp")),
    ("https://www.instagram.com/band", ("social", "instagram")),
    ("https://twitter.com/band", ("social", "x")),
    ("https://soundcloud.com/band", ("social", "soundcloud")),
    ("https://www.allmusic.com/album/x", None),
    ("https://notspotify.com/open.spotify.com", None),
])
def test_classify_url(url, expected):
    assert classify_url(url) == expected


def test_classify_official_needs_rel_type():
    assert classify_url("https://nirvana.com", "official homepage") == ("official", "website")
    assert classify_url("https://nirvana.com") is None


def rg(relations):
    return {"id": "x", "relations": [{"type": t, "url": {"resource": u}} for t, u in relations]}


@pytest.fixture
def album(album_factory, imported_album):
    return imported_album


def test_links_from_release_group(db, no_sleep, album_factory, monkeypatch):
    album = album_factory()
    monkeypatch.setattr("catalog.services.links.mb.get_release_group", lambda mbid: rg([
        ("streaming", "https://open.spotify.com/album/x"), ("allmusic", "https://www.allmusic.com/a")]))
    called = []
    monkeypatch.setattr("catalog.services.links.mb.get_release", lambda mbid: called.append(mbid) or {})
    import_album_links(album)
    assert [(l.kind, l.service) for l in album.links.all()] == [("listen", "spotify")]
    assert called == []


def test_links_fall_back_to_reference_release_only(db, no_sleep, album_factory, monkeypatch):
    from catalog.models import Release

    album = album_factory()
    ref = Release.objects.create(album=album, mbid="22222222-2222-2222-2222-222222222222", title="r")
    album.reference_release = ref
    album.save()
    monkeypatch.setattr("catalog.services.links.mb.get_release_group", lambda mbid: rg([]))
    called = []

    def get_release(mbid):
        called.append(mbid)
        return rg([("bandcamp", "https://band.bandcamp.com/album/y")])

    monkeypatch.setattr("catalog.services.links.mb.get_release", get_release)
    import_album_links(album)
    assert called == [str(ref.mbid)]
    assert album.links.get().service == "bandcamp"


def test_links_updated_and_stale_removed(db, no_sleep, album_factory, monkeypatch):
    album = album_factory()
    ExternalLink.objects.create(album=album, kind="listen", service="spotify", url="https://open.spotify.com/album/old")
    ExternalLink.objects.create(album=album, kind="listen", service="youtube", url="https://music.youtube.com/playlist?list=z")
    monkeypatch.setattr("catalog.services.links.mb.get_release_group", lambda mbid: rg([
        ("streaming", "https://music.youtube.com/playlist?list=z"), ("streaming", "https://music.apple.com/pt/album/x")]))
    import_album_links(album)
    import_album_links(album)
    assert sorted(album.links.values_list("service", flat=True)) == ["apple_music", "youtube"]
