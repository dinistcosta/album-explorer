import json
import re
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
import respx
from django.utils import timezone

from catalog.models import Album, Artist, ArtistGenre, ExternalLink, Genre, Membership
from catalog.services.artist_import import discography_sections, import_artist_core, release_group_kind
from sources.http import SourceUnavailable
from tests.ids import NIRVANA

pytestmark = pytest.mark.usefixtures("enqueued")

FIX = Path(__file__).parent.parent / "fixtures" / "musicbrainz"
BASE = "https://musicbrainz.org/ws/2/"
BIG_ARTIST = "11111111-2222-3333-4444-555555555555"


def load(name):
    return json.loads((FIX / name).read_text())


@pytest.fixture
def nirvana_respx(db, no_sleep):
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}artist/{NIRVANA}").respond(200, json=load("nirvana_artist.json"))

        def rgs(request):
            if request.url.params.get("offset") == "0":
                return httpx.Response(200, json=load("nirvana_rgs_page1.json"))
            return httpx.Response(200, json={"release-group-count": 449, "release-groups": []})

        router.get(url__regex=re.escape(BASE) + r"release-group\?").mock(side_effect=rgs)
        yield router


@pytest.fixture
def imported_nirvana(nirvana_respx):
    return import_artist_core(NIRVANA, foreground=True)


@pytest.fixture
def respx_150_release_groups(db, no_sleep):
    groups = [
        {"id": f"00000000-0000-0000-0000-{i:012d}", "title": f"Record {i}", "primary-type": "Album",
         "secondary-types": [], "first-release-date": "2001"}
        for i in range(150)
    ]

    def page(request):
        offset = int(request.url.params["offset"])
        return httpx.Response(200, json={"release-group-count": 150, "release-groups": groups[offset:offset + 100]})

    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}artist/{BIG_ARTIST}").respond(
            200, json={"id": BIG_ARTIST, "name": "Prolific", "sort-name": "Prolific", "type": "Group", "relations": []})
        router.get(url__regex=re.escape(BASE) + r"release-group\?").mock(side_effect=page)
        yield router


def test_artist_page_lists_studio_albums_first(client, nirvana_respx):
    r = client.get(f"/pt/artist/{NIRVANA}/")
    assert r.status_code == 200
    html = r.content.decode()
    assert html.index("Nevermind") < html.index("Ao vivo")
    assert re.search(r"<details class=\"disc-group\" open>\s*<summary>Álbuns de estúdio", html)
    assert '<details class="disc-group">' in html  # the rest are collapsed


def test_english_headings_and_album_link(client, nirvana_respx):
    html = client.get(f"/en/artist/{NIRVANA}/").content.decode()
    assert "Studio albums" in html and "Live" in html and "Compilations" in html
    nevermind = Album.objects.get(title="Nevermind")
    assert f'href="/en/album/{nevermind.mbid}/"' in html
    assert "front-250" in html and 'loading="lazy"' in html


def test_members_with_years(client, imported_nirvana):
    html = client.get(f"/pt/artist/{imported_nirvana.mbid}/").content.decode()
    assert "Dave Grohl" in html and "1990–1994" in html
    assert "Fonte: MusicBrainz" in html


def test_members_merge_duplicate_relations(imported_nirvana):
    cobain = Membership.objects.filter(band=imported_nirvana, member__name="Kurt Cobain")
    assert cobain.count() == 1
    inst = cobain.get().instruments
    assert {"guitar", "lead vocals"} <= set(inst) and "original" not in inst
    assert cobain.get().begin_year == 1987 and cobain.get().end_year == 1994


def test_core_fields_links_genres_stubs(db, nirvana_respx):
    Genre.objects.create(slug="grunge", name="Grunge")
    Genre.objects.create(slug="punk-rock", name="Punk rock")
    Artist.objects.create(mbid=NIRVANA, name="Nirvana", country="XX", locked_fields=["country"])
    artist = import_artist_core(NIRVANA, foreground=True)
    assert artist.country == "XX"  # locked field survives the import
    assert artist.begin_year == 1987 and artist.end_year == 1994 
    assert artist.wikidata_id == "Q11649" and artist.discogs_id == "125246"
    assert artist.imported_at is not None
    assert ExternalLink.objects.filter(artist=artist, kind="official").exists()
    assert ExternalLink.objects.filter(artist=artist, service="spotify").exists()
    assert Album.objects.filter(artist=artist).count() == 100
    nevermind = Album.objects.get(title="Nevermind")
    assert nevermind.year == 1991 and nevermind.imported_at is None and nevermind.artist == artist
    assert set(ArtistGenre.objects.filter(artist=artist).values_list("genre__slug", flat=True)) == {"grunge", "punk-rock"}


def test_stubs_do_not_overwrite_imported_albums(db, nirvana_respx, album_factory):
    artist = Artist.objects.create(mbid=NIRVANA, name="Nirvana")
    album = album_factory(
        mbid="1b022e01-4da6-387b-8658-8678046e4cef", title="Nevermind", artist=artist,
        cover_url="https://example.org/c.jpg", accent_color="#123456", discogs_master_id="13814",
        imported_at=timezone.now(), locked_fields=["title"])
    album.title = "Edited"
    album.save()
    import_artist_core(NIRVANA, foreground=True)
    album.refresh_from_db()
    assert album.title == "Edited" and album.year == 1991
    assert album.cover_url == "https://example.org/c.jpg" and album.accent_color == "#123456"
    assert album.discogs_master_id == "13814" and album.imported_at is not None


def test_discography_paginates_past_100(db, respx_150_release_groups):
    artist = import_artist_core(BIG_ARTIST, foreground=True)
    assert artist.albums.count() == 150


def test_release_group_kinds():
    assert release_group_kind("Album", []) == "studio"
    assert release_group_kind("EP", []) == "ep"
    assert release_group_kind("Album", ["Live"]) == "live"
    assert release_group_kind("Album", ["Compilation", "Live"]) == "live"
    assert release_group_kind("Album", ["Compilation"]) == "compilation"
    assert release_group_kind("Album", ["Soundtrack"]) == "other"
    assert release_group_kind("Single", []) == "other"


def test_sections_sorted_by_year_none_last(artist_factory, album_factory):
    artist = artist_factory()
    album_factory(artist=artist, title="C", year=None)
    album_factory(artist=artist, title="B", year=2000)
    album_factory(artist=artist, title="A", year=1990)
    album_factory(artist=artist, title="L", year=1995, secondary_types=["Live"])
    sections = dict(discography_sections(artist))
    assert [a.title for a in sections["studio"]] == ["A", "B", "C"]
    assert [a.title for a in sections["live"]] == ["L"]
    assert [k for k, _ in discography_sections(artist)] == ["studio", "ep", "live", "compilation", "other"]


def test_artist_story_falls_back_to_generated(client, artist_factory):
    artist = artist_factory(artist_type="Group", imported_at=timezone.now())
    assert "Conheces a história desta banda?" in client.get(f"/pt/artist/{artist.mbid}/").content.decode()
    assert "Do you know this band's story?" in client.get(f"/en/artist/{artist.mbid}/").content.decode()


def test_photo_links_to_commons_page(client, artist_factory):
    artist = artist_factory(
        imported_at=timezone.now(), image_url="https://commons.wikimedia.org/wiki/Special:FilePath/X.jpg?width=600",
        image_source_url="https://commons.wikimedia.org/wiki/File:X.jpg")
    html = client.get(f"/pt/artist/{artist.mbid}/").content.decode()
    assert 'href="https://commons.wikimedia.org/wiki/File:X.jpg"' in html and "Foto:" in html


def test_header_falls_back_to_most_listened_studio_cover(client, artist_factory, album_factory):
    artist = artist_factory(imported_at=timezone.now())
    album_factory(artist=artist, title="First", year=1990, lastfm_listeners=5)
    top = album_factory(artist=artist, title="Top", year=2000, lastfm_listeners=500)
    html = client.get(f"/pt/artist/{artist.mbid}/").content.decode()
    assert f"release-group/{top.mbid}/front-500" in html
    assert "listeners" not in html and "ouvintes" not in html and ">500<" not in html  # no popularity numbers


def test_unknown_artist_is_404(client, db, no_sleep):
    with respx.mock:
        respx.get(url__regex=r".*").respond(404, json={"error": "Not Found"})
        assert client.get("/pt/artist/00000000-0000-0000-0000-000000000000/").status_code == 404


def test_source_down_on_first_visit_is_503(client, db, no_sleep):
    with respx.mock:
        respx.get(url__regex=r".*").respond(503)
        assert client.get(f"/pt/artist/{NIRVANA}/").status_code == 503


def test_cached_artist_renders_when_source_down(client, artist_factory, no_sleep):
    artist = artist_factory(imported_at=timezone.now(), enriched_at=timezone.now())
    with respx.mock:
        respx.get(url__regex=r".*").respond(503)
        assert client.get(f"/pt/artist/{artist.mbid}/").status_code == 200


def test_stub_artist_without_import_triggers_import(client, nirvana_respx):
    Artist.objects.create(mbid=NIRVANA, name="Nirvana")  # e.g. created from a credit
    client.get(f"/pt/artist/{NIRVANA}/")
    assert Artist.objects.get(mbid=NIRVANA).imported_at is not None


def test_stub_album_triggers_full_import(client, db, mb_fixtures, album_factory):
    from tests.ids import NEVERMIND_RG
    album_factory(mbid=NEVERMIND_RG, title="Nevermind", imported_at=None)
    assert "Smells Like Teen Spirit" in client.get(f"/pt/album/{NEVERMIND_RG}/").content.decode()


def test_enrichment_endpoint_polls_and_enqueues(client, artist_factory, enqueued):
    artist = artist_factory(imported_at=timezone.now())
    html = client.get(f"/pt/artist/{artist.mbid}/sections/").content.decode()
    assert "hx-get" in html and 'id="artist-photo"' in html
    assert ("enrich_artist", artist.pk) in enqueued
    artist.enriched_at = timezone.now()
    artist.save()
    assert "hx-get" not in client.get(f"/pt/artist/{artist.mbid}/sections/").content.decode()


def test_album_page_links_to_band(client, album_factory):
    album = album_factory(imported_at=timezone.now())
    html = client.get(f"/pt/album/{album.mbid}/").content.decode()
    assert f'href="/pt/artist/{album.artist.mbid}/"' in html


def test_instruments_translated_on_pt_page_only(client, imported_nirvana):
    pt = client.get(f"/pt/artist/{NIRVANA}/").content.decode()
    en = client.get(f"/en/artist/{NIRVANA}/").content.decode()
    assert "bateria" in pt and "drums" not in pt
    assert "drums" in en and "bateria" not in en


def test_unknown_instrument_falls_back_to_raw():
    from catalog.services.instruments import instrument_label
    assert instrument_label("theremin") == "theremin"


def test_stub_album_with_source_down_is_503(client, album_factory, no_sleep):
    album = album_factory(imported_at=None)
    with respx.mock:
        respx.get(url__regex=r".*").respond(503)
        assert client.get(f"/pt/album/{album.mbid}/").status_code == 503
