import json
from pathlib import Path

import httpx
import pytest
import respx

from sources import musicbrainz as mb
from sources.musicbrainz import escape_lucene
from tests.ids import NEVERMIND_RG, NEVERMIND_VINYL, NIRVANA

FIX = Path(__file__).parent.parent / "fixtures" / "musicbrainz"
BASE = "https://musicbrainz.org/ws/2/"


def fixture(name):
    return json.loads((FIX / name).read_text())


@pytest.fixture(autouse=True)
def _fast(db, no_sleep):
    pass


def test_escape_lucene():
    assert escape_lucene('AC/DC "live"') == 'AC\\/DC \\"live\\"'
    assert escape_lucene("a+b-c&&d||e!f(g)h{i}j[k]l^m~n*o?p:q\\r") == (
        "a\\+b\\-c\\&&d\\||e\\!f\\(g\\)h\\{i\\}j\\[k\\]l\\^m\\~n\\*o\\?p\\:q\\\\r"
    )


@respx.mock
def test_browse_release_groups_follows_pagination():
    def item(i):
        return {"id": f"rg-{i}", "title": f"T{i}"}

    def handler(request):
        offset = int(request.url.params["offset"])
        items = [item(i) for i in range(offset, min(offset + 100, 150))]
        return httpx.Response(200, json={"release-group-count": 150, "release-groups": items})

    route = respx.get(BASE + "release-group").mock(side_effect=handler)
    result = mb.browse_release_groups(NIRVANA)
    assert len(result) == 150
    assert route.call_count == 2
    p = route.calls[0].request.url.params
    assert p["artist"] == NIRVANA and p["type"] == "album|ep" and p["limit"] == "100"
    assert p["fmt"] == "json"


@respx.mock
def test_browse_releases_uses_recorded_fixture_and_paginates():
    page1 = fixture("nevermind_releases.json")
    assert page1["release-count"] == 101 and len(page1["releases"]) == 100
    extra = {"release-count": 101, "release-offset": 100, "releases": [{"id": "last"}]}

    def handler(request):
        return httpx.Response(200, json=page1 if request.url.params["offset"] == "0" else extra)

    route = respx.get(BASE + "release").mock(side_effect=handler)
    result = mb.browse_releases(NEVERMIND_RG)
    assert len(result) == 101 and result[-1]["id"] == "last"
    assert route.calls[0].request.url.params["release-group"] == NEVERMIND_RG
    assert route.calls[0].request.url.params["inc"] == "media"


@respx.mock
def test_get_release_group_params_and_user_agent():
    route = respx.get(BASE + f"release-group/{NEVERMIND_RG}").mock(
        return_value=httpx.Response(200, json=fixture("nevermind_rg.json"))
    )
    data = mb.get_release_group(NEVERMIND_RG)
    assert data["id"] == NEVERMIND_RG
    req = route.calls[0].request
    assert req.url.params["inc"] == "artist-credits+url-rels+genres"
    assert req.url.params["fmt"] == "json"
    assert req.headers["User-Agent"].startswith("AlbumExplorer/0.1 (")


@respx.mock
def test_get_release_vinyl_has_side_numbers():
    route = respx.get(BASE + f"release/{NEVERMIND_VINYL}").mock(
        return_value=httpx.Response(200, json=fixture("nevermind_vinyl.json"))
    )
    data = mb.get_release(NEVERMIND_VINYL)
    assert data["media"][0]["tracks"][0]["number"] == "A1"
    assert route.calls[0].request.url.params["inc"] == (
        "recordings+artist-credits+labels+artist-rels+place-rels+recording-level-rels+url-rels"
    )


@respx.mock
def test_get_artist():
    route = respx.get(BASE + f"artist/{NIRVANA}").mock(
        return_value=httpx.Response(200, json=fixture("nirvana_artist.json"))
    )
    assert mb.get_artist(NIRVANA)["name"] == "Nirvana"
    assert route.calls[0].request.url.params["inc"] == "url-rels+artist-rels+genres"


@respx.mock
def test_search_functions_escape_and_limit():
    r1 = respx.get(BASE + "artist").mock(
        return_value=httpx.Response(200, json={"artists": [{"id": "a"}]})
    )
    r2 = respx.get(BASE + "release-group").mock(
        return_value=httpx.Response(200, json={"release-groups": [{"id": "g"}]})
    )
    assert mb.search_artists("AC/DC") == [{"id": "a"}]
    assert mb.search_release_groups("x") == [{"id": "g"}]
    assert r1.calls[0].request.url.params["limit"] == "8"
    assert "AC\\/DC" in r1.calls[0].request.url.params["query"]
    assert r2.calls[0].request.url.params["limit"] == "24"


@respx.mock
def test_list_genres():
    route = respx.get(BASE + "genre/all").mock(
        return_value=httpx.Response(200, text="grunge\n\n  post-rock \nshoegaze\n")
    )
    assert mb.list_genres() == ["grunge", "post-rock", "shoegaze"]
    assert route.calls[0].request.url.params["fmt"] == "txt"
