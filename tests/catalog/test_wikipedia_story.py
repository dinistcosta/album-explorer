import json
import re
from pathlib import Path

import httpx
import pytest
import respx

from catalog.models import Story
from catalog.services.stories import import_wikipedia_stories, parse_wikipedia_html
from catalog.services.text import normalize

FIX = Path(__file__).parent.parent / "fixtures" / "wikipedia"
WIKIDATA = "https://www.wikidata.org/w/api.php"


def html(name):
    return json.loads((FIX / name).read_text())["parse"]["text"]


@pytest.fixture
def wiki_en_html():
    return html("nevermind_en.json")


@pytest.fixture
def wiki_pt_html():
    return html("acabou_chorare_pt.json")


@pytest.fixture
def respx_wiki(no_sleep):
    with respx.mock(assert_all_called=False) as router:
        router.wikidata = router.get(WIKIDATA).mock(return_value=httpx.Response(200, json={
            "entities": {"Q1": {"id": "Q1", "sitelinks": {
                "ptwiki": {"title": "Acabou Chorare"}, "enwiki": {"title": "Nevermind"}}}}}))
        router.en = router.get("https://en.wikipedia.org/w/api.php").mock(
            return_value=httpx.Response(200, json=json.loads((FIX / "nevermind_en.json").read_text())))
        router.pt = router.get("https://pt.wikipedia.org/w/api.php").mock(
            return_value=httpx.Response(200, json=json.loads((FIX / "acabou_chorare_pt.json").read_text())))
        yield router


def test_intro_and_recording_kept_tables_dropped(wiki_en_html):
    sections = parse_wikipedia_html(wiki_en_html, "en")
    assert sections[0]["heading"] is None and sections[0]["paragraphs"]
    assert any(s["heading"].lower().startswith("recording") for s in sections[1:])
    assert all("[1]" not in p for s in sections for p in s["paragraphs"])
    assert all(s["paragraphs"] for s in sections)
    assert not any((s["heading"] or "").lower().startswith(("track", "personnel", "references")) for s in sections)


def test_portuguese_headings_with_accents(wiki_pt_html):
    sections = parse_wikipedia_html(wiki_pt_html, "pt")
    assert any(normalize(s["heading"] or "").startswith("gravacao") for s in sections)
    assert not any(re.search(r"\[\d+\]", p) for s in sections for p in s["paragraphs"])


def test_h3_merged_and_bare_h2():
    page = (
        "<p>Intro.</p><h2>Recording</h2><p>One.</p><h3>Sub</h3><p>Two.</p>"
        "<h2>Track listing</h2><p>No.</p><h2>Release</h2><table><tr><td>x</td></tr></table>"
    )
    assert parse_wikipedia_html(page, "en") == [
        {"heading": None, "paragraphs": ["Intro."]},
        {"heading": "Recording", "paragraphs": ["One.", "Two."]},
    ]


def test_story_saved_per_language(db, imported_album, respx_wiki):
    imported_album.wikidata_id = "Q1"
    imported_album.save()
    import_wikipedia_stories(imported_album)
    stories = {s.lang: s for s in Story.objects.filter(album=imported_album)}
    assert set(stories) == {"pt", "en"}
    assert stories["en"].source == "wikipedia" and stories["en"].license == "CC BY-SA 4.0"
    assert stories["en"].url == "https://en.wikipedia.org/wiki/Nevermind"
    assert stories["pt"].url == "https://pt.wikipedia.org/wiki/Acabou_Chorare"
    assert stories["en"].sections and stories["en"].fetched_at
    import_wikipedia_stories(imported_album)
    assert Story.objects.filter(album=imported_album).count() == 2


def test_manual_story_untouched(db, imported_album, respx_wiki):
    imported_album.wikidata_id = "Q1"
    imported_album.save()
    manual = Story.objects.create(
        album=imported_album, lang="en", source="wikipedia", is_manual=True,
        sections=[{"heading": None, "paragraphs": ["mine"]}])
    import_wikipedia_stories(imported_album)
    manual.refresh_from_db()
    assert manual.sections == [{"heading": None, "paragraphs": ["mine"]}]
    assert Story.objects.filter(album=imported_album, lang="en").count() == 2


def test_no_wikidata_id_makes_no_requests(db, album_factory, respx_wiki):
    import_wikipedia_stories(album_factory())
    assert respx_wiki.calls.call_count == 0


def test_artist_story(db, artist_factory, respx_wiki):
    artist = artist_factory(wikidata_id="Q1")
    import_wikipedia_stories(artist)
    assert Story.objects.filter(artist=artist).count() == 2


def test_registered_after_wikidata_enrichers():
    from catalog.tasks import ALBUM_ENRICHERS, ARTIST_ENRICHERS

    for lst, name in ((ALBUM_ENRICHERS, "import_album_wikidata"), (ARTIST_ENRICHERS, "import_artist_wikidata")):
        names = [f.__name__ for f in lst]
        assert names.index("import_wikipedia_stories") > names.index(name)
