"""Final-review minor fixes (M1-M14)."""
import io
from unittest import mock

import httpx
import pytest
import respx
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation
from PIL import Image

from catalog.models import Album, Award, Influence, Release, Track
from sources.http import SourceNotFound
from tests.catalog.test_story_chain import fx, lf  # noqa: F401  (fixture)
from tests.catalog.test_wikidata_import import wikidata_fixtures  # noqa: F401  (fixture)
from tests.ids import NIRVANA

pytestmark = pytest.mark.usefixtures("enqueued")
MB = "https://musicbrainz.org/ws/2/"


# M1 ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("msgid", [
    "Unlock all fields", "Unlocked %(n)d item(s).", "Refresh now", "Refresh started for “%(title)s”.",
    "Refresh started for %(n)d artist(s).", "Could not refresh “%(title)s”: source unavailable.",
    "Could not refresh “%(title)s”: MusicBrainz no longer has this album.",
])
def test_admin_strings_translated_to_portuguese(msgid):
    with translation.override("pt"):
        assert translation.gettext(msgid) != msgid


# M2 ---------------------------------------------------------------------------------------------
def test_503_wording_fits_artists_too(client, db, no_sleep):
    with respx.mock:
        respx.get(url__regex=r".*").respond(503)
        en = client.get(f"/en/artist/{NIRVANA}/").content.decode()
        pt = client.get(f"/pt/artist/{NIRVANA}/").content.decode()
    assert "this page" in en and "album" not in en.split("<main>", 1)[1].split("</main>")[0]
    assert "esta página" in pt


# M3 ---------------------------------------------------------------------------------------------
def test_influences_stored_but_not_shown(client, artist_factory):
    from django.utils import timezone

    artist = artist_factory(imported_at=timezone.now(), enriched_at=timezone.now())
    Influence.objects.create(artist=artist, target_wikidata_id="Q1", target_label="The Beatles")
    for lang in ("pt", "en"):
        html = client.get(f"/{lang}/artist/{artist.mbid}/").content.decode()
        assert "The Beatles" not in html and "nfluênc" not in html and "Influences" not in html


# M4 ---------------------------------------------------------------------------------------------
def test_tracklist_shows_its_source(client, album_factory):
    album = album_factory()
    release = Release.objects.create(album=album, mbid="44444444-4444-4444-4444-444444444444", title="r")
    Track.objects.create(release=release, position=1, number="1", title="Song")
    album.reference_release = release
    album.save()
    html = client.get(f"/pt/album/{album.mbid}/").content.decode()
    tracks = html.split('class="a-tracks"', 1)[1].split("a-sections", 1)[0]
    assert "Fonte: MusicBrainz" in tracks
    assert "Source: MusicBrainz" in client.get(f"/en/album/{album.mbid}/").content.decode()


# M7 ---------------------------------------------------------------------------------------------
def test_accent_color_validated(album_factory):
    album = album_factory(accent_color="#12abEF")
    album.full_clean()
    for bad in ("red", "#12abEG", "#fff", "#12abef;"):
        album.accent_color = bad
        with pytest.raises(ValidationError):
            album.full_clean()


def test_invalid_accent_falls_back_to_default(client, album_factory):
    bad = album_factory(accent_color="red;}</style>")
    assert '--accent: #c8a45a"' in client.get(f"/pt/album/{bad.mbid}/").content.decode()
    good = album_factory(accent_color="#2f7cc0")
    assert '--accent: #2f7cc0"' in client.get(f"/pt/album/{good.mbid}/").content.decode()
    assert '--accent: #c8a45a"' in client.get("/pt/").content.decode()


# M8 ---------------------------------------------------------------------------------------------
def test_search_tolerates_null_fields(client, db, no_sleep):
    a, g = "55555555-5555-5555-5555-555555555555", "66666666-6666-6666-6666-666666666666"
    with respx.mock(assert_all_called=False) as router:
        router.get(url__startswith=MB + "artist").respond(json={"artists": [
            {"id": a, "name": "Nullband", "sort-name": None, "country": None, "type": None}]})
        router.get(url__startswith=MB + "release-group").respond(json={"release-groups": [
            {"id": g, "title": None, "primary-type": "Album", "score": 90,
             "artist-credit": [{"name": "Nullband", "joinphrase": None, "artist": {"id": a, "name": None}}]}]})
        r = client.get("/en/search/", {"q": "nullband"})
    assert r.status_code == 200 and "None" not in r.content.decode()
    assert Album.objects.get(mbid=g).artist_credit == "Nullband"


# M9 ---------------------------------------------------------------------------------------------
def test_500_page_is_bilingual(db):
    html = render_to_string("500.html")
    assert "Algo correu mal" in html and "Something went wrong" in html and "site" in html


# M10 --------------------------------------------------------------------------------------------
def test_discogs_markup_stripped():
    from catalog.services.text import strip_discogs_markup

    raw = ("Recorded at [l=Sound City]. Thanks to [a=Butch Vig] and [a12345].\n"
           "[b]Bold[/b] [i]it[/i] [url=https://x.org/a]the site[/url] [r=99]")
    assert strip_discogs_markup(raw) == "Recorded at Sound City. Thanks to Butch Vig and .\nBold it the site"


def test_discogs_notes_stored_and_rendered_without_markup(client, album_factory, settings, no_sleep):
    from catalog.services.stories import import_discogs_notes

    settings.DISCOGS_TOKEN = "t"
    album = album_factory(discogs_master_id="1", locked_fields=["discogs_master_id"])
    with respx.mock(assert_all_called=False) as router:
        router.get("https://api.discogs.com/masters/1").respond(json={"main_release": 2, "styles": []})
        router.get("https://api.discogs.com/releases/2").respond(json={"notes": "Mixed by [a=Andy Wallace]."})
        import_discogs_notes(album)
    album.refresh_from_db()
    assert album.discogs_notes == "Mixed by Andy Wallace."
    Album.objects.filter(pk=album.pk).update(discogs_notes="Old [b]row[/b] by [a=Someone].")
    html = client.get(f"/en/album/{album.mbid}/").content.decode()
    assert "Old row by Someone." in html and "[a=" not in html


# M11 --------------------------------------------------------------------------------------------
def test_decompression_bomb_keeps_cover_and_default_accent(album_factory, monkeypatch):
    from catalog.services import color

    album = album_factory()
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), "#2f7cc0").save(buf, "PNG")
    monkeypatch.setattr(color, "fetch_cover", lambda mbid: buf.getvalue())

    def bomb(data):
        raise Image.DecompressionBombError("too big")

    monkeypatch.setattr(color, "extract_accent", bomb)
    color.apply_cover_and_accent(album)
    album.refresh_from_db()
    assert album.cover_url and album.accent_color == ""


def test_award_without_any_label_is_skipped(db, imported_album, wikidata_fixtures):
    from catalog.services.wikidata_import import import_album_wikidata

    original = wikidata_fixtures.api.side_effect

    def no_labels(request):
        if "claims" in request.url.params["props"]:
            return original(request)
        ids = request.url.params["ids"].split("|")
        return httpx.Response(200, json={"entities": {i: {"id": i, "labels": {}} for i in ids}})

    wikidata_fixtures.api.side_effect = no_labels
    import_album_wikidata(imported_album)
    assert not Award.objects.filter(album=imported_album).exists()


# M12 --------------------------------------------------------------------------------------------
def test_lastfm_story_url_must_be_https(album_factory, lf):
    from catalog.models import Story
    from catalog.services.stories import import_lastfm_stories

    def handler(request):
        data = fx(f"lastfm/album_info_{request.url.params['lang']}.json")
        data["album"]["url"] = "javascript:alert(1)" if request.url.params["lang"] == "en" else "http://x"
        return httpx.Response(200, json=data)

    lf.route.side_effect = handler
    album = album_factory(title="Nevermind")
    import_lastfm_stories(album)
    assert set(Story.objects.filter(album=album).values_list("url", flat=True)) == {""}


# M13 --------------------------------------------------------------------------------------------
def test_suggestions_have_no_listbox_roles(client, artist_factory):
    artist_factory(name="Nirvana")
    html = client.get("/pt/search/suggest/", {"q": "nirv"}).content.decode()
    assert "Nirvana" in html and "listbox" not in html and 'role="option"' not in html


# M14 --------------------------------------------------------------------------------------------
def test_refresh_now_album_gone_from_musicbrainz_is_message(admin_client, album_factory):
    album = album_factory()
    with mock.patch("catalog.admin.import_album_core", side_effect=SourceNotFound("gone")), \
            mock.patch("catalog.admin.enqueue_enrichment") as enq:
        r = admin_client.post(reverse("admin:catalog_album_changelist"),
                              {"action": "refresh_now", "_selected_action": [album.pk]}, follow=True)
    assert r.status_code == 200
    assert any(m.level_tag == "error" for m in r.context["messages"])
    enq.assert_not_called()


def test_album_cover_shows_its_source(client, album_factory):
    album = album_factory(cover_url="https://coverartarchive.org/release-group/x/front-500")
    html = client.get(f"/pt/album/{album.mbid}/").content.decode()
    assert "Capa: <a" in html and "Cover Art Archive" in html
    assert "cover-source" not in client.get(f"/pt/album/{album_factory().mbid}/").content.decode()
