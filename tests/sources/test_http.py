from datetime import timedelta

import httpx
import pytest
import respx

from sources.http import MIN_INTERVAL, SourceNotFound, SourceUnavailable, fetch
from sources.models import HttpCacheEntry

URL = "https://musicbrainz.org/ws/2/artist/x"


@pytest.fixture(autouse=True)
def _fast(no_sleep):
    return no_sleep


def test_min_intervals():
    assert MIN_INTERVAL == {
        "musicbrainz": 1.0, "discogs": 1.0, "lastfm": 0.25, "wikipedia": 0.1,
        "wikidata": 0.1, "wikiquote": 0.1, "coverart": 0.1,
    }


@respx.mock
def test_second_fetch_uses_cache(db):
    route = respx.get(URL).respond(json={"id": "x"})
    fetch("musicbrainz", URL)
    assert fetch("musicbrainz", URL) == {"id": "x"}
    assert route.call_count == 1


@respx.mock
def test_params_change_cache_key(db):
    route = respx.get(URL).respond(json={})
    fetch("musicbrainz", URL, params={"a": "1"})
    fetch("musicbrainz", URL, params={"a": "2"})
    assert route.call_count == 2
    assert HttpCacheEntry.objects.count() == 2


@respx.mock
def test_expired_cache_refetches(db, freezer):
    route = respx.get(URL).respond(json={"id": "x"})
    ttl = timedelta(days=1)
    fetch("musicbrainz", URL, ttl=ttl)
    freezer.move_to("2099-01-01")
    fetch("musicbrainz", URL, ttl=ttl)
    assert route.call_count == 2
    assert HttpCacheEntry.objects.count() == 1


@respx.mock
def test_sends_user_agent(db, settings):
    settings.CONTACT_URL = "https://example.org"
    route = respx.get(URL).respond(json={})
    fetch("musicbrainz", URL)
    assert route.calls[0].request.headers["User-Agent"] == "AlbumExplorer/0.1 ( https://example.org )"


@respx.mock
def test_text_and_binary(db):
    respx.get("https://coverartarchive.org/a").respond(content=b"PNG!")
    assert fetch("coverart", "https://coverartarchive.org/a", binary=True) == b"PNG!"
    assert fetch("coverart", "https://coverartarchive.org/a", as_json=False) == "PNG!"


@respx.mock
def test_503_retries_then_raises(db, no_sleep):
    route = respx.get(URL).respond(503)
    with pytest.raises(SourceUnavailable):
        fetch("musicbrainz", URL)
    assert route.call_count == 3
    assert no_sleep == [1, 2]
    assert HttpCacheEntry.objects.count() == 0


@respx.mock
def test_retry_then_success(db):
    route = respx.get(URL).mock(side_effect=[httpx.Response(429), httpx.Response(200, json={"ok": 1})])
    assert fetch("musicbrainz", URL) == {"ok": 1}
    assert route.call_count == 2


@respx.mock
def test_404_raises_not_found_and_is_not_cached(db):
    route = respx.get(URL).respond(404)
    for _ in range(2):
        with pytest.raises(SourceNotFound):
            fetch("musicbrainz", URL)
    assert route.call_count == 2
    assert HttpCacheEntry.objects.count() == 0


@respx.mock
def test_other_error_status_raises_unavailable(db):
    respx.get(URL).respond(500)
    with pytest.raises(SourceUnavailable):
        fetch("musicbrainz", URL)


@respx.mock
def test_timeout_raises_source_unavailable(db):
    route = respx.get(URL).mock(side_effect=httpx.ConnectTimeout("t"))
    with pytest.raises(SourceUnavailable):
        fetch("musicbrainz", URL)
    assert route.call_count == 3


@respx.mock
def test_follows_redirects(db):
    respx.get("https://coverartarchive.org/a").respond(307, headers={"Location": "https://archive.org/b"})
    respx.get("https://archive.org/b").respond(200, content=b"IMG")
    assert fetch("coverart", "https://coverartarchive.org/a", binary=True) == b"IMG"


@respx.mock
def test_foreground_uses_short_budget(db, no_sleep, monkeypatch):
    import sources.http as http

    timeouts = []
    real_get = httpx.get

    def spy(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        return real_get(*args, **kwargs)

    monkeypatch.setattr(http.httpx, "get", spy)
    route = respx.get(URL).respond(503)
    with pytest.raises(SourceUnavailable):
        fetch("musicbrainz", URL, foreground=True)
    assert route.call_count == 2  # one try + one retry
    assert timeouts == [5.0, 5.0]
    assert no_sleep == [1.0]


@respx.mock
def test_background_keeps_long_budget(db, no_sleep, monkeypatch):
    import sources.http as http

    timeouts = []
    real_get = httpx.get

    def spy(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        return real_get(*args, **kwargs)

    monkeypatch.setattr(http.httpx, "get", spy)
    respx.get(URL).respond(503)
    with pytest.raises(SourceUnavailable):
        fetch("musicbrainz", URL)
    assert timeouts == [10.0, 10.0, 10.0]
