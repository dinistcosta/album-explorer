import uuid

import httpx
import pytest
import respx

from catalog.models import Album, Artist
from catalog.services.search import search, suggest

MB = "https://musicbrainz.org/ws/2/"
A1, A2, G1, G2 = (str(uuid.uuid4()) for _ in range(4))


@pytest.fixture(autouse=True)
def _fast(no_sleep):
    pass


@pytest.fixture
def mb_search_respx():
    with respx.mock(assert_all_called=False) as router:
        router.artist = router.get(url__startswith=MB + "artist").respond(json={"artists": [
            {"id": A1, "name": "Nirvana", "sort-name": "Nirvana", "country": "US", "type": "Group", "score": 100,
             "life-span": {"begin": "1987", "end": "1994"}},
        ]})
        router.rg = router.get(url__startswith=MB + "release-group").respond(json={"release-groups": [
            {"id": G1, "title": "Nevermind", "first-release-date": "1991-09-24", "primary-type": "Album",
             "secondary-types": [], "score": 100,
             "artist-credit": [{"name": "Nirvana", "joinphrase": "", "artist": {"id": A1, "name": "Nirvana", "sort-name": "Nirvana"}}]},
            {"id": G2, "title": "Nevermind Live", "first-release-date": "1992", "primary-type": "Album",
             "secondary-types": ["Live"], "score": 80,
             "artist-credit": [{"name": "Other", "joinphrase": "", "artist": {"id": A2, "name": "Other", "sort-name": "Other"}}]},
        ]})
        yield router


@pytest.fixture
def mb_503():
    with respx.mock(assert_all_called=False) as router:
        router.get(url__startswith=MB).respond(503)
        yield router


def test_suggest_is_accent_insensitive(db, artist_factory):
    artist_factory(name="Sigur Rós")
    assert [a.name for a in suggest("sigur ros")["artists"]] == ["Sigur Rós"]


def test_suggest_prefix_first_and_capped(db, artist_factory, album_factory):
    artist_factory(name="The Cure")
    artist_factory(name="Cure Kids")
    for i in range(7):
        artist_factory(name=f"Cure {i}")
    names = [a.name for a in suggest("cure")["artists"]]
    assert len(names) == 5 and "The Cure" not in names[:1]
    album_factory(title="Pure Cure", artist=None)
    album_factory(title="Cure All", artist=None)
    assert [a.title for a in suggest("cure")["albums"]][0] == "Cure All"


def test_suggest_never_calls_sources(db):
    with respx.mock(assert_all_called=False) as router:
        suggest("radiohead")
        assert not router.calls


def test_suggest_short_query_empty(db):
    assert suggest("a") == {"artists": [], "albums": []}
    assert suggest("  ") == {"artists": [], "albums": []}


@respx.mock
def test_search_escapes_lucene(db):
    route = respx.get(url__startswith=MB + "artist").respond(json={"artists": []})
    rg = respx.get(url__startswith=MB + "release-group").respond(json={"release-groups": []})
    search("AC/DC")
    assert "AC\\/DC" in route.calls[0].request.url.params["query"]
    q = rg.calls[0].request.url.params["query"]
    assert q == "releasegroup:(AC\\/DC) AND (primarytype:album OR primarytype:ep)"


def test_search_upserts_stubs(db, mb_search_respx):
    r = search("nevermind")
    assert {a.mbid for a in Artist.objects.all()} == {uuid.UUID(A1), uuid.UUID(A2)}
    nirvana = Artist.objects.get(mbid=A1)
    assert (nirvana.country, nirvana.artist_type, nirvana.sort_name) == ("US", "Group", "Nirvana")
    nm = Album.objects.get(mbid=G1)
    assert (nm.title, nm.year, nm.primary_type, nm.artist, nm.artist_credit) == ("Nevermind", 1991, "Album", nirvana, "Nirvana")
    assert Album.objects.get(mbid=G2).secondary_types == ["Live"]
    assert [a.mbid for a in r.albums] == [uuid.UUID(G1), uuid.UUID(G2)]
    assert [a["albums"] for a in [suggest("nevermind live")]][0]  # later suggestions find stubs


def test_search_does_not_clobber_imported_and_dedupes(db, mb_search_respx, artist_factory, album_factory):
    artist = artist_factory(mbid=A1, name="Nirvana", begin_year=1985, imported_at="2026-01-01T00:00:00Z", image_url="http://x/y.jpg")
    album = album_factory(mbid=G1, title="Nevermind", artist=artist, cover_url="http://c/1.jpg", lastfm_listeners=5)
    r = search("nevermind")
    album.refresh_from_db(); artist.refresh_from_db()
    assert album.cover_url == "http://c/1.jpg" and artist.image_url == "http://x/y.jpg" and artist.begin_year == 1985
    assert [a.mbid for a in r.albums].count(album.mbid) == 1
    assert [a.mbid for a in r.artists].count(artist.mbid) == 1


def test_search_survives_source_down(db, mb_503, artist_factory):
    artist_factory(name="Björk")
    r = search("bjork")
    assert r.source_error and r.artists


def test_blank_query_makes_no_source_call(client, db):
    with respx.mock(assert_all_called=False) as router:
        resp = client.get("/en/search/", {"q": "   "})
        assert resp.status_code == 200 and not router.calls


def test_results_page_shows_bands_then_cover_grid(client, db, mb_search_respx):
    html = client.get("/en/search/", {"q": "nirvana"}).content.decode()
    assert html.index("Nirvana") < html.index('class="cover-grid"') < html.index("Nevermind")
    assert "1987" in html and f"/en/artist/{A1}/" in html


def test_results_page_notice_when_source_down(client, db, mb_503, artist_factory):
    artist_factory(name="Björk")
    en = client.get("/en/search/", {"q": "bjork"}).content.decode()
    assert "MusicBrainz didn&#x27;t respond; showing what we already know." in en or "MusicBrainz didn't respond" in en
    assert "Björk" in en
    pt = client.get("/pt/search/", {"q": "bjork"}).content.decode()
    assert "A pesquisa no MusicBrainz não respondeu; mostramos o que já conhecemos." in pt


def test_suggest_view_fragment(client, db, artist_factory):
    artist_factory(name="Sigur Rós")
    html = client.get("/en/search/suggest/", {"q": "sigur"}).content.decode()
    assert "Sigur Rós" in html and "<html" not in html


def test_forms_wired(client, db):
    html = client.get("/en/").content.decode()
    assert 'action="/en/search/"' in html and 'hx-get="/en/search/suggest/"' in html
    page = client.get("/en/search/", {"q": ""}).content.decode()
    assert page.count('hx-get="/en/search/suggest/"') == 1  # header search on non-home pages
