import json
from pathlib import Path

import httpx
import pytest
import respx
from django.utils import timezone

from catalog.models import Album, Story
from catalog.services.stories import (
    import_discogs_notes, import_lastfm_stories, select_story,
)
from sources import lastfm
from sources.http import SourceUnavailable

FIX = Path(__file__).parent.parent / "fixtures"
LASTFM = "https://ws.audioscrobbler.com/2.0/"
DISCOGS = "https://api.discogs.com"
MB = "https://musicbrainz.org/ws/2/"


def fx(rel):
    return json.loads((FIX / rel).read_text())


def story(owner, lang, source="wikipedia", manual=False, text="Texto."):
    kw = {"album": owner} if isinstance(owner, Album) else {"artist": owner}
    return Story.objects.create(
        **kw, lang=lang, source=source, is_manual=manual, url=f"https://x/{source}/{lang}",
        license="CC BY-SA 4.0", sections=[{"heading": None, "paragraphs": [f"{text} {source} {lang}"]}],
        fetched_at=timezone.now())


@pytest.fixture
def album(album_factory):
    return album_factory(title="Nevermind", year=1991)


def test_chain_prefers_reader_language(album):
    story(album, "en"); story(album, "pt")
    v = select_story(album, "pt")
    assert v.lang == "pt" and not v.is_other_language and v.source == "wikipedia"


def test_chain_falls_back_to_english_with_flag(album):
    story(album, "en")
    v = select_story(album, "pt")
    assert v.lang == "en" and v.is_other_language and not v.is_generated
    assert v.license == "CC BY-SA 4.0" and v.url == "https://x/wikipedia/en"


def test_chain_portuguese_story_for_english_reader_flagged(album):
    story(album, "pt")
    v = select_story(album, "en")
    assert v.lang == "pt" and v.is_other_language


def test_chain_lastfm_before_generated(album):
    story(album, "en", source="lastfm")
    v = select_story(album, "pt")
    assert v.source == "lastfm" and v.lang == "en" and v.is_other_language and not v.is_generated


def test_wikipedia_other_language_beats_lastfm_same_language(album):
    story(album, "en"); story(album, "pt", source="lastfm")
    assert select_story(album, "pt").source == "wikipedia"


def test_chain_generated_when_nothing(album):
    v = select_story(album, "pt")
    assert v.is_generated and v.sections == [] and v.source == ""


def test_manual_story_wins(album):
    story(album, "pt"); story(album, "pt", manual=True, source="manual")
    v = select_story(album, "pt")
    assert v.source == "manual" and "manual" in v.sections[0]["paragraphs"][0]


def test_artist_generated(artist_factory):
    a = artist_factory(name="Os Xis", artist_type="Group", country="PT", begin_year=1980)
    v = select_story(a, "pt")
    assert v.is_generated
    assert v.sections == [{"heading": None, "paragraphs": ["Os Xis é uma banda formada em 1980 (Portugal)."]}]


def test_clean_lastfm_wiki_strips_read_more():
    raw = fx("lastfm/album_info_en.json")["album"]["wiki"]["content"]
    cleaned = lastfm.clean_lastfm_wiki(raw)
    assert "Read more on Last.fm" not in cleaned and "User-contributed" not in cleaned and "<a" not in cleaned
    assert cleaned.startswith("Nevermind is the second studio album") and cleaned.endswith("Butch Vig.")


@pytest.fixture
def lf(settings, no_sleep):
    settings.LASTFM_API_KEY = "k"
    with respx.mock(assert_all_called=False) as router:
        def handler(request):
            q = request.url.params
            if q["method"] == "album.getinfo":
                return httpx.Response(200, json=fx(f"lastfm/album_info_{q['lang']}.json"))
            if q["method"] == "artist.getinfo":
                return httpx.Response(200, json=fx("lastfm/artist_info_en.json"))
            return httpx.Response(200, json=fx("lastfm/error_not_found.json"))
        router.route = router.get(LASTFM).mock(side_effect=handler)
        yield router


def test_lastfm_album_story_pt_and_en(album, lf):
    import_lastfm_stories(album)
    pt, en = (Story.objects.get(album=album, source="lastfm", lang=l) for l in ("pt", "en"))
    assert pt.license == en.license == "CC BY-SA 3.0"
    assert pt.sections[0]["paragraphs"][0].startswith("Nevermind é o segundo")
    assert en.url == "https://www.last.fm/music/Nirvana/Nevermind"
    album.refresh_from_db()
    assert album.lastfm_listeners == 2200000


def test_lastfm_pt_skipped_when_identical_to_en(album, lf, monkeypatch):
    lf.route.side_effect = lambda r: httpx.Response(200, json=fx("lastfm/album_info_en.json"))
    import_lastfm_stories(album)
    assert list(Story.objects.filter(album=album).values_list("lang", flat=True)) == ["en"]


def test_lastfm_artist_story(artist_factory, lf):
    a = artist_factory(name="Nirvana")
    import_lastfm_stories(a)
    s = Story.objects.get(artist=a, source="lastfm")
    assert s.lang == "en" and s.sections[0]["paragraphs"][0].startswith("Nirvana was an American")


def test_lastfm_skipped_without_key(album, settings):
    settings.LASTFM_API_KEY = ""
    with respx.mock(assert_all_called=False) as router:
        route = router.route()
        import_lastfm_stories(album)
        assert lastfm.album_info("A", "B", None, "en") is None
        assert lastfm.artist_info("A", None, "en") is None
        assert lastfm.album_top_tags("A", "B") == []
        assert lastfm.tag_top_albums("grunge") == []
        assert lastfm.tag_info("grunge", "en") is None
        assert route.call_count == 0
    assert not Story.objects.exists()


def test_lastfm_leaves_manual_story_alone(album, lf):
    manual = story(album, "en", source="lastfm", manual=True, text="Mine")
    import_lastfm_stories(album)
    manual.refresh_from_db()
    assert manual.sections[0]["paragraphs"][0].startswith("Mine")
    assert Story.objects.filter(album=album, lang="en").count() == 2


def test_lastfm_listeners_respects_lock(album, lf):
    album.locked_fields = ["lastfm_listeners"]; album.lastfm_listeners = 5; album.save()
    import_lastfm_stories(album)
    album.refresh_from_db()
    assert album.lastfm_listeners == 5


def test_lastfm_api_error_returns_none(db, settings, no_sleep):
    settings.LASTFM_API_KEY = "k"
    with respx.mock() as router:
        router.get(LASTFM).respond(200, json=fx("lastfm/error_not_found.json"))
        assert lastfm.album_info("A", "B", None, "en") is None


def test_lastfm_top_tags_and_tag_calls(db, settings, no_sleep):
    settings.LASTFM_API_KEY = "k"
    with respx.mock() as router:
        router.get(LASTFM).mock(side_effect=lambda r: httpx.Response(200, json=fx(
            {"album.gettoptags": "lastfm/album_top_tags.json", "tag.gettopalbums": "lastfm/tag_top_albums.json",
             "tag.getinfo": "lastfm/tag_info_en.json"}[r.url.params["method"]])))
        assert lastfm.album_top_tags("Nirvana", "Nevermind") == ["grunge", "rock", "albums I own"]
        assert [a["name"] for a in lastfm.tag_top_albums("grunge", 2)] == ["Nevermind", "Ten"]
        assert lastfm.tag_info("grunge", "en")["name"] == "grunge"


@pytest.fixture
def dc(settings, no_sleep):
    settings.DISCOGS_TOKEN = "tok"
    with respx.mock(assert_all_called=False) as router:
        router.mb = router.get(url__startswith=f"{MB}release-group/").mock(
            return_value=httpx.Response(200, json=fx("musicbrainz/nevermind_rg.json")))
        router.master = router.get(f"{DISCOGS}/masters/13814").mock(
            return_value=httpx.Response(200, json=fx("discogs/master_13814.json")))
        router.release = router.get(f"{DISCOGS}/releases/367485").mock(
            return_value=httpx.Response(200, json=fx("discogs/release_367485.json")))
        yield router


def test_discogs_notes_stored(album, dc):
    import_discogs_notes(album)
    album.refresh_from_db()
    assert album.discogs_master_id == "13814"
    assert album.discogs_styles == ["Grunge", "Alternative Rock"]
    assert album.discogs_notes.startswith("Recorded at Sound City Studios")
    assert dc.master.calls.last.request.headers["Authorization"] == "Discogs token=tok"


def test_discogs_skipped_without_token(album, settings):
    settings.DISCOGS_TOKEN = ""
    with respx.mock(assert_all_called=False) as router:
        route = router.route()
        import_discogs_notes(album)
        assert route.call_count == 0


def test_discogs_notes_shown_with_generated_sheet(album):
    album.discogs_notes = "Pressed in Germany."
    album.save()
    assert select_story(album, "pt").notes == "Pressed in Germany."


def test_other_language_notice_rendered(client, album, enqueued):
    story(album, "en")
    html = client.get(f"/pt/album/{album.mbid}/").content.decode()
    assert "Disponível apenas em inglês" in html
    assert "Wikipedia (EN)" in html and "CC BY-SA 4.0" in html


def test_english_reader_notice(client, album, enqueued):
    story(album, "pt")
    html = client.get(f"/en/album/{album.mbid}/").content.decode()
    assert "Only available in Portuguese" in html


def test_liner_keep_reading_details(client, album, enqueued):
    Story.objects.create(album=album, lang="pt", source="wikipedia", url="https://x", license="CC BY-SA 4.0",
                         sections=[{"heading": None, "paragraphs": ["Intro."]},
                                   {"heading": "Gravação", "paragraphs": ["Um."]},
                                   {"heading": "Recepção", "paragraphs": ["Dois."]}])
    html = client.get(f"/pt/album/{album.mbid}/").content.decode()
    assert "<details" in html and "Continuar a ler" in html
    assert html.index("Um.") < html.index("<details") < html.index("Dois.")


def test_generated_sheet_rendered_with_placeholder(client, album, enqueued):
    html = client.get(f"/pt/album/{album.mbid}/").content.decode()
    assert "Ficha montada a partir de dados do MusicBrainz e do Discogs" in html
    assert "Conheces a história deste disco?" in html
    en = client.get(f"/en/album/{album.mbid}/").content.decode()
    assert "Fact sheet built from MusicBrainz and Discogs data" in en
    assert "Do you know the story of this record?" in en


def test_enrichers_registered_after_wikipedia():
    from catalog import tasks
    from catalog.services.stories import import_wikipedia_stories
    names = [f.__name__ for f in tasks.ALBUM_ENRICHERS]
    assert names.index("import_wikipedia_stories") < names.index("import_lastfm_stories") < names.index("import_discogs_notes")
    assert tasks.ARTIST_ENRICHERS.index(import_wikipedia_stories) < [f.__name__ for f in tasks.ARTIST_ENRICHERS].index("import_lastfm_stories")


def test_lastfm_album_falls_back_to_name_after_mbid_miss(album, lf):
    from catalog.models import Release
    ref = Release.objects.create(mbid="22222222-2222-2222-2222-222222222222", album=album, title="N")
    album.reference_release = ref; album.save()

    def handler(request):
        q = request.url.params
        if "mbid" in q:
            return httpx.Response(200, json=fx("lastfm/error_not_found.json"))
        return httpx.Response(200, json=fx(f"lastfm/album_info_{q['lang']}.json"))
    lf.route.side_effect = handler
    import_lastfm_stories(album)
    assert Story.objects.filter(album=album, source="lastfm").count() == 2
    mbids = [c.request.url.params["mbid"] for c in lf.route.calls if "mbid" in c.request.url.params]
    assert mbids and set(mbids) == {"22222222-2222-2222-2222-222222222222"}


def test_lastfm_artist_falls_back_to_name(artist_factory, lf):
    a = artist_factory(name="Nirvana")
    lf.route.side_effect = lambda r: httpx.Response(200, json=fx(
        "lastfm/error_not_found.json" if "mbid" in r.url.params else "lastfm/artist_info_en.json"))
    import_lastfm_stories(a)
    assert Story.objects.filter(artist=a, source="lastfm").exists()


def test_lastfm_404_is_none(db, settings, no_sleep):
    settings.LASTFM_API_KEY = "k"
    with respx.mock() as router:
        router.get(LASTFM).respond(404)
        assert lastfm.album_info("A", "B", None, "en") is None
