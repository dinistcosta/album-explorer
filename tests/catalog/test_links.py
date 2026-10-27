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


def test_streaming_links_come_from_digital_releases_not_the_cassette_reference(imported_album, monkeypatch):
    """Real shape: the reference release is a physical edition with only a Discogs relation; the Spotify and
    Apple Music relations ('free streaming' / 'streaming') sit on Digital Media releases."""
    album = imported_album
    digital = [r for r in album.releases.all() if "Digital Media" in r.formats]
    assert len(digital) >= 2
    rels = {str(d.mbid): rg([("free streaming", f"https://open.spotify.com/album/{i}?si=abc")])
            for i, d in enumerate(digital)}
    first = sorted(digital, key=lambda r: (r.status != "Official", r.country not in ("XW", "US"), r.date or "9999"))[0]
    rels[str(first.mbid)] = rg([("streaming", "https://music.apple.com/de/album/1440783617"),
                                ("free streaming", "https://open.spotify.com/album/abc?si=1")])
    calls = []

    def get_release(mbid):
        calls.append(mbid)
        return rels.get(mbid, rg([("discogs", "https://www.discogs.com/release/1")]))

    monkeypatch.setattr("catalog.services.links.mb.get_release_group", lambda mbid: rg([
        ("allmusic", "https://www.allmusic.com/album/mw0000185616")]))
    monkeypatch.setattr("catalog.services.links.mb.get_release", get_release)
    import_album_links(album)
    assert sorted(album.links.values_list("service", flat=True)) == ["apple_music", "spotify"]
    assert calls == [str(first.mbid)]  # stopped as soon as Spotify and Apple Music were covered
    assert len(calls) <= 5
