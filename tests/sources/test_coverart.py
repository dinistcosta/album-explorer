
import pytest
import respx

from catalog.services.color import apply_cover_and_accent
from sources.coverart import cover_url, fetch_cover
from sources.http import SourceUnavailable

MBID = "1b022e01-4da6-387b-8658-8678046e4cef"


def test_cover_url():
    assert cover_url(MBID) == f"https://coverartarchive.org/release-group/{MBID}/front-500"


@respx.mock
def test_fetch_cover_returns_bytes_through_redirect(db, no_sleep):
    respx.get(cover_url(MBID)).respond(307, headers={"Location": "https://archive.org/img.jpg"})
    respx.get("https://archive.org/img.jpg").respond(200, content=b"JPEGDATA")
    assert fetch_cover(MBID) == b"JPEGDATA"


@respx.mock
def test_fetch_cover_404_is_none(db, no_sleep):
    respx.get(cover_url(MBID)).respond(404)
    assert fetch_cover(MBID) is None


@respx.mock
def test_fetch_cover_unavailable_propagates(db, no_sleep):
    respx.get(cover_url(MBID)).respond(500)
    with pytest.raises(SourceUnavailable):
        fetch_cover(MBID)


@respx.mock
def test_missing_cover_keeps_placeholder(db, imported_album, client):
    respx.get(cover_url(str(imported_album.mbid))).respond(404)
    apply_cover_and_accent(imported_album)
    imported_album.refresh_from_db()
    assert imported_album.cover_url == "" and imported_album.accent_color == ""
    assert 'class="sleeve placeholder"' in client.get(f"/pt/album/{imported_album.mbid}/").content.decode()


@respx.mock
def test_cover_sets_url_and_accent(db, imported_album):
    from tests.catalog.test_color import solid_png

    respx.get(cover_url(str(imported_album.mbid))).respond(200, content=solid_png("#2f7cc0"))
    apply_cover_and_accent(imported_album)
    imported_album.refresh_from_db()
    assert imported_album.cover_url == cover_url(str(imported_album.mbid))
    assert imported_album.accent_color.startswith("#")


@respx.mock
def test_locked_accent_and_cover_are_kept(db, imported_album):
    from tests.catalog.test_color import solid_png

    imported_album.accent_color = "#123456"
    imported_album.locked_fields = ["accent_color"]
    imported_album.save()
    respx.get(cover_url(str(imported_album.mbid))).respond(200, content=solid_png("#2f7cc0"))
    apply_cover_and_accent(imported_album)
    imported_album.refresh_from_db()
    assert imported_album.accent_color == "#123456"
    assert imported_album.cover_url


@respx.mock
def test_unreadable_image_leaves_accent_default(db, imported_album):
    respx.get(cover_url(str(imported_album.mbid))).respond(200, content=b"not an image")
    apply_cover_and_accent(imported_album)
    imported_album.refresh_from_db()
    assert imported_album.accent_color == ""
