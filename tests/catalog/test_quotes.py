import json
from pathlib import Path

import httpx
import pytest
import respx

from catalog.models import Membership, Quote, Release, Track
from catalog.services.quotes import extract_wikipedia_quotes, extract_wikiquote_quotes, import_quotes
from catalog.services.text import normalize

FIX = Path(__file__).parent.parent / "fixtures" / "wikiquote"
WIKIDATA = "https://www.wikidata.org/w/api.php"


def fixture_html(name):
    return json.loads((FIX / name).read_text())["parse"]["text"]


@pytest.fixture
def wikiquote_html():
    return fixture_html("cobain_en.json")


def test_wikiquote_keeps_only_album_mentions(wikiquote_html):
    qs = extract_wikiquote_quotes(wikiquote_html, "Nevermind", ["Lithium"], "Kurt Cobain")
    assert qs and all(
        "nevermind" in normalize(q.text + q.source_label) or "lithium" in normalize(q.text + q.source_label)
        for q in qs)
    assert all(q.speaker == "Kurt Cobain" and q.origin == "wikiquote" for q in qs)


def test_wikiquote_skips_lyrics_and_quotes_about(wikiquote_html):
    qs = extract_wikiquote_quotes(wikiquote_html, "In Utero", ["Lithium"], "Kurt Cobain")
    assert qs
    assert not any("I'm so happy" in q.text for q in qs)  # lyric lines (<br>) are not statements
    assert not any("Genius is a weird" in q.text for q in qs)  # "Quotes about Cobain": someone else


def test_wikiquote_lyrics_page_yields_nothing():
    assert extract_wikiquote_quotes(fixture_html("nirvana_en.json"), "Nevermind", ["Lithium"], "Nirvana") == []


def test_wikiquote_source_label_from_nested_item():
    html = ('<div class="mw-parser-output"><div class="mw-heading mw-heading2"><h2>Interviews</h2></div>'
            '<ul><li>We just made Nevermind in a few weeks.<ul><li>Interview, <a href="https://example.org/x">Spin</a>, 1992</li></ul></li></ul></div>')
    [q] = extract_wikiquote_quotes(html, "Nevermind", [], "Kurt Cobain")
    assert q.text == "We just made Nevermind in a few weeks."
    assert q.source_label == "Interview, Spin, 1992" and q.source_url == "https://example.org/x"


def test_wikipedia_quote_requires_person_and_reference():
    html = ('<p>Vig said "we wanted it to sound like a huge record from the start" in 1992.'
            '<sup class="reference"><a href="#cite_note-1">[1]</a></sup></p>'
            '<ol class="references"><li id="cite_note-1"><cite><a href="https://example.org/i">Interview, Spin</a></cite></li></ol>')
    [q] = extract_wikipedia_quotes(html, ["Butch Vig"])
    assert q.speaker == "Butch Vig" and q.source_url == "https://example.org/i"
    assert q.text == "we wanted it to sound like a huge record from the start"
    assert q.source_label == "Interview, Spin" and q.origin == "wikipedia"


def test_wikipedia_quote_dropped_without_reference():
    html = '<p>Vig said "we wanted it to sound like a huge record from the start" in 1992.</p>'
    assert extract_wikipedia_quotes(html, ["Butch Vig"]) == []


def test_wikipedia_quote_dropped_when_two_people_named():
    html = ('<p>Vig and Cobain said "we wanted it to sound like a huge record from the start" in 1992.'
            '<sup class="reference"><a href="#cite_note-1">[1]</a></sup></p>'
            '<ol class="references"><li id="cite_note-1"><cite><a href="https://example.org/i">Spin</a></cite></li></ol>')
    assert extract_wikipedia_quotes(html, ["Butch Vig", "Kurt Cobain"]) == []


def test_wikipedia_quote_dropped_when_short():
    html = ('<p>Vig said "a huge record" in 1992.<sup class="reference"><a href="#cite_note-1">[1]</a></sup></p>'
            '<ol class="references"><li id="cite_note-1"><cite><a href="https://example.org/i">Spin</a></cite></li></ol>')
    assert extract_wikipedia_quotes(html, ["Butch Vig"]) == []


def test_wikipedia_curly_and_guillemet_quotes():
    ref = ('<sup class="reference"><a href="#cite_note-1">[1]</a></sup></p>'
           '<ol class="references"><li id="cite_note-1"><span class="reference-text">Revista X. <a class="external" href="https://example.org/r">link</a></span></li></ol>')
    [a] = extract_wikipedia_quotes('<p>Vig disse “queríamos um disco enorme desde o primeiro dia”.' + ref, ["Butch Vig"])
    [b] = extract_wikipedia_quotes('<p>Vig disse «queríamos um disco enorme desde o primeiro dia».' + ref, ["Butch Vig"])
    assert a.text == b.text == "queríamos um disco enorme desde o primeiro dia"
    assert a.source_url == "https://example.org/r"


# ---- enricher ------------------------------------------------------------------------------

@pytest.fixture
def quote_world(db, no_sleep, album_factory, artist_factory):
    artist = artist_factory(name="Kurt Cobain", wikidata_id="Q1")
    album = album_factory(title="In Utero", artist=artist, wikidata_id="Q2")
    release = Release.objects.create(album=album, mbid="33333333-3333-3333-3333-333333333333", title="In Utero")
    Track.objects.create(release=release, position=1, number="1", title="Lithium")
    album.reference_release = release
    album.save()
    wp_html = ('<p>Albini said "we recorded the whole thing live in about six days" in 1993.'
               '<sup class="reference"><a href="#cite_note-1">[1]</a></sup></p>'
               '<ol class="references"><li id="cite_note-1"><cite><a href="https://example.org/a">Interview</a></cite></li></ol>')

    def wikidata(request):
        ids = request.url.params["ids"]
        sitelinks = {"Q1": {"enwikiquote": {"title": "Kurt Cobain"}}, "Q2": {"enwiki": {"title": "In Utero"}}}
        return httpx.Response(200, json={"entities": {i: {"id": i, "sitelinks": sitelinks.get(i, {})}
                                                       for i in ids.split("|")}})

    with respx.mock(assert_all_called=False) as router:
        router.get(WIKIDATA).mock(side_effect=wikidata)
        router.wq = router.get("https://en.wikiquote.org/w/api.php").mock(
            return_value=httpx.Response(200, json=json.loads((FIX / "cobain_en.json").read_text())))
        router.wp = router.get("https://en.wikipedia.org/w/api.php").mock(
            return_value=httpx.Response(200, json={"parse": {"text": wp_html}}))
        router.album, router.artist = album, artist
        yield router


def test_import_quotes_max_two_wikiquote_first(quote_world):
    from catalog.models import Credit

    Credit.objects.create(album=quote_world.album, person=quote_world.artist.__class__.objects.create(
        mbid="11111111-1111-1111-1111-111111111111", name="Steve Albini", sort_name="Albini, Steve"),
        role="producer")
    import_quotes(quote_world.album)
    quotes = list(quote_world.album.quotes.order_by("id"))
    assert len(quotes) <= 2 and quotes
    assert quotes[0].origin == "wikiquote" and quotes[0].lang == "en" and quotes[0].speaker == "Kurt Cobain"
    assert quotes[0].source_url


def test_import_quotes_keeps_manual_and_replaces_old(quote_world):
    album = quote_world.album
    manual = Quote.objects.create(album=album, text="Mine", origin="manual", is_manual=True)
    old = Quote.objects.create(album=album, text="Stale", origin="wikiquote", speaker="x")
    import_quotes(album)
    assert Quote.objects.filter(pk=manual.pk).exists()
    assert not Quote.objects.filter(pk=old.pk).exists()


def test_import_quotes_wikipedia_origin_with_members(quote_world, artist_factory):
    album = quote_world.album
    band = artist_factory(name="Nirvana")
    album.artist = band
    album.save()
    Membership.objects.create(band=band, member=artist_factory(name="Steve Albini"))
    quote_world.get("https://en.wikiquote.org/w/api.php").mock(return_value=httpx.Response(200, json={"parse": {"text": ""}}))
    import_quotes(album)
    [q] = album.quotes.all()
    assert q.origin == "wikipedia" and q.speaker == "Steve Albini" and q.lang == "en"
    assert q.source_url == "https://example.org/a"


def test_import_quotes_no_fetch_inside_atomic(quote_world, monkeypatch):
    from django.db import connection

    seen = []
    base = len(connection.savepoint_ids)  # the test's own transaction counts as depth 0 here
    real = httpx.Client.send

    def spy(self, *a, **k):
        seen.append(len(connection.savepoint_ids) > base)
        return real(self, *a, **k)

    monkeypatch.setattr(httpx.Client, "send", spy)
    import_quotes(quote_world.album)
    assert seen and not any(seen)


def test_band_albums_use_members_wikiquote_pages(db, no_sleep, album_factory, artist_factory):
    band = artist_factory(name="Nirvana", wikidata_id="Q11649")
    album = album_factory(title="Nevermind", artist=band)
    release = Release.objects.create(album=album, mbid="44444444-4444-4444-4444-444444444444", title="Nevermind")
    Track.objects.create(release=release, position=1, number="1", title="Lithium")
    album.reference_release = release
    album.save()
    claims = {"P527": [{"mainsnak": {"snaktype": "value", "datavalue": {"value": {"id": "Q8446"}}}},
                       {"mainsnak": {"snaktype": "somevalue"}}]}

    def wikidata(request):
        ids = request.url.params["ids"].split("|")
        data = {"Q11649": {"id": "Q11649", "claims": claims, "labels": {},
                           "sitelinks": {"enwikiquote": {"title": "Nirvana (band)"}}},
                "Q8446": {"id": "Q8446", "labels": {"en": {"value": "Kurt Cobain"}},
                          "sitelinks": {"enwikiquote": {"title": "Kurt Cobain"}}}}
        return httpx.Response(200, json={"entities": {i: data[i] for i in ids}})

    def wikiquote(request):
        name = "nirvana_en.json" if request.url.params["page"] == "Nirvana (band)" else "cobain_en.json"
        return httpx.Response(200, json=json.loads((FIX / name).read_text()))

    with respx.mock(assert_all_called=False) as router:
        router.get(WIKIDATA).mock(side_effect=wikidata)
        router.get("https://en.wikiquote.org/w/api.php").mock(side_effect=wikiquote)
        import_quotes(album)
    quotes = list(album.quotes.all())
    assert quotes and len(quotes) <= 2
    assert all(q.speaker == "Kurt Cobain" and q.origin == "wikiquote" for q in quotes)


def test_missing_wikidata_item_keeps_existing_quotes(quote_world):
    album = quote_world.album
    import_quotes(album)
    before = list(album.quotes.values_list("pk", flat=True))
    assert before
    from sources.models import HttpCacheEntry

    HttpCacheEntry.objects.all().delete()  # a later refresh, past the cache
    quote_world.routes[0].mock(side_effect=lambda r: httpx.Response(200, json={"entities": {
        i: {"id": i, "missing": ""} for i in r.url.params["ids"].split("|")}}))
    import_quotes(album)
    assert list(album.quotes.values_list("pk", flat=True)) == before


def test_redirected_wikidata_item_still_finds_quotes(quote_world):
    album = quote_world.album
    quote_world.routes[0].mock(side_effect=lambda r: httpx.Response(200, json={"entities": {
        "Q100": {"id": "Q100", "sitelinks": {"enwikiquote": {"title": "Kurt Cobain"}}},
    } if r.url.params["ids"] == "Q1" else {"Q200": {"id": "Q200", "sitelinks": {"enwiki": {"title": "In Utero"}}}}}))
    import_quotes(album)
    assert album.quotes.filter(origin="wikiquote").exists()
