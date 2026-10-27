import httpx
import pytest
import respx
from django.utils import timezone

from catalog.models import Release, Track
from tests.ids import NEVERMIND_RG

pytestmark = pytest.mark.usefixtures("enqueued")


def make_album(album_factory, sides):
    album = album_factory(title="Sided", artist_credit="Band")
    release = Release.objects.create(mbid="11111111-1111-1111-1111-111111111111", album=album, title="Sided")
    for i, side in enumerate(sides, 1):
        Track.objects.create(release=release, position=i, number=str(i), side=side, title=f"Song {i}", length_ms=61000 + i)
    album.reference_release = release
    album.save()
    return album


def url(album):
    return f"/pt/album/{album.mbid}/"


def test_album_page_imports_on_first_visit(client, db, mb_fixtures):
    r = client.get(f"/pt/album/{NEVERMIND_RG}/")
    assert r.status_code == 200
    html = r.content.decode()
    assert "Nevermind" in html and "Smells Like Teen Spirit" in html


def test_sides_shown_when_known(client, album_factory):
    album = make_album(album_factory, ["A", "A", "B"])
    html = client.get(url(album)).content.decode()
    assert "Lado A" in html and "Lado B" in html


def test_single_list_without_sides(client, album_factory):
    album = make_album(album_factory, [None, None])
    html = client.get(url(album)).content.decode()
    assert "Alinhamento" in html and "Lado A" not in html
    assert "1:01" in html


def test_english_headings(client, album_factory):
    album = make_album(album_factory, ["A", "B"])
    html = client.get(f"/en/album/{album.mbid}/").content.decode()
    assert "Side A" in html and "Side B" in html


def test_unknown_mbid_is_404(client, db, no_sleep):
    with respx.mock:
        respx.get(url__regex=r".*").respond(404, json={"error": "Not Found"})
        assert client.get("/pt/album/00000000-0000-0000-0000-000000000000/").status_code == 404


def test_malformed_mbid_is_404(client, db):
    assert client.get("/pt/album/not-a-uuid/").status_code == 404


def test_source_down_on_first_visit_is_503(client, db, no_sleep):
    with respx.mock:
        respx.get(url__regex=r".*").respond(503)
        r = client.get(f"/pt/album/{NEVERMIND_RG}/")
    assert r.status_code == 503 and "Tenta outra vez" in r.content.decode()


def test_cached_album_renders_when_source_down(client, imported_album, no_sleep):
    with respx.mock:
        route = respx.get(url__regex=r".*").respond(503)
        assert client.get(f"/pt/album/{imported_album.mbid}/").status_code == 200
        assert not route.called


def test_polling_while_not_enriched(client, imported_album):
    html = client.get(f"/pt/album/{imported_album.mbid}/").content.decode()
    assert 'hx-get="/pt/album/%s/sections/' % imported_album.mbid in html
    assert "load delay:2s" in html


def test_polling_stops_once_enriched(client, imported_album):
    imported_album.enriched_at = timezone.now()
    imported_album.save()
    assert "hx-get" not in client.get(f"/pt/album/{imported_album.mbid}/sections/").content.decode()


def test_polling_stops_after_max_polls(client, imported_album):
    html = client.get(f"/pt/album/{imported_album.mbid}/sections/?n=15").content.decode()
    assert "hx-get" not in html
    html = client.get(f"/pt/album/{imported_album.mbid}/sections/?n=3").content.decode()
    assert "n=4" in html


def test_credits_rendered_with_source(client, imported_album):
    html = client.get(f"/pt/album/{imported_album.mbid}/sections/").content.decode()
    assert "Butch Vig" in html and "MusicBrainz" in html


def test_placeholder_sleeve_without_cover(client, album_factory):
    album = make_album(album_factory, [None])
    html = client.get(url(album)).content.decode()
    assert "sleeve placeholder" in html and "<img" not in html.split("a-hero")[1].split("</section>")[0]


def test_cover_rendered_when_set(client, album_factory):
    album = make_album(album_factory, [None])
    album.cover_url = "https://example.org/c.jpg"
    album.save()
    assert "https://example.org/c.jpg" in client.get(url(album)).content.decode()


def test_accent_color_used(client, album_factory):
    album = make_album(album_factory, [None])
    album.accent_color = "#112233"
    album.save()
    assert "--accent: #112233" in client.get(url(album)).content.decode()


def test_get_absolute_url(album_factory):
    album = album_factory()
    assert album.get_absolute_url() == f"/pt/album/{album.mbid}/"


def test_custom_404_template(client, db, settings):
    settings.DEBUG = False
    r = client.get("/pt/album/not-a-uuid/")
    assert r.status_code == 404 and "museu" in r.content.decode()


def test_credit_roles_translated(client, imported_album):
    pt = client.get(f"/pt/album/{imported_album.mbid}/sections/").content.decode()
    en = client.get(f"/en/album/{imported_album.mbid}/sections/").content.decode()
    assert "Produtor" in pt and "Producer" in en


def test_awards_rendered_in_active_language_with_wikidata_source(client, album_factory):
    from catalog.models import Award

    album = album_factory(wikidata_id="Q17444", enriched_at=timezone.now())
    Award.objects.create(album=album, name_en="Diamond album", name_pt="Álbum de diamante", year=1993)
    pt = client.get(f"/pt/album/{album.mbid}/sections/").content.decode()
    en = client.get(f"/en/album/{album.mbid}/sections/").content.decode()
    assert "Álbum de diamante (1993)" in pt and "Diamond album" not in pt
    assert "Diamond album (1993)" in en and "Álbum de diamante" not in en
    assert 'href="https://www.wikidata.org/wiki/Q17444"' in pt
    assert "Fonte" in pt and "Source" in en


# ---- Task 11: listen / buy links, genres, quotes --------------------------------------------

def _page(client, album, lang="pt"):
    return client.get(f"/{lang}/album/{album.mbid}/").content.decode()


@pytest.fixture
def linked_album(album_factory, enqueued):
    from django.utils import timezone

    from catalog.models import ExternalLink

    album = album_factory(title="Nevermind", enriched_at=timezone.now())
    ExternalLink.objects.create(album=album, kind="listen", service="spotify", url="https://open.spotify.com/album/x")
    return album


def test_listen_button_hidden_without_link(client, linked_album):
    html = _page(client, linked_album)
    assert "Spotify" in html and "Apple Music" not in html and "YouTube" not in html
    assert 'href="https://open.spotify.com/album/x" target="_blank" rel="noopener"' in html
    assert "autoplay" not in html


def test_buy_link_discogs_search_always_present(client, linked_album):
    html = _page(client, linked_album)
    assert "Procurar no Discogs" in html
    assert "https://www.discogs.com/search/?q=" in html and "Nevermind" in html
    assert "Search on Discogs" in _page(client, linked_album, "en")


def test_bandcamp_is_also_a_buy_link(client, linked_album):
    from catalog.models import ExternalLink

    ExternalLink.objects.create(album=linked_album, kind="listen", service="bandcamp", url="https://b.bandcamp.com/album/n")
    html = _page(client, linked_album)
    assert html.count("https://b.bandcamp.com/album/n") == 2


def test_genre_chips_and_quote_blocks(client, linked_album):
    from catalog.models import AlbumGenre, Genre, Quote

    AlbumGenre.objects.create(album=linked_album, genre=Genre.objects.create(slug="grunge", name="grunge"), source="musicbrainz")
    Quote.objects.create(album=linked_album, text="We made it fast", speaker="Kurt Cobain", source_label="Spin", source_url="https://e.org/s", origin="wikiquote", lang="en")
    Quote.objects.create(album=linked_album, text="Wanted it huge", speaker="Butch Vig", source_label="Mojo", source_url="https://e.org/m", origin="wikipedia", lang="en")
    html = _page(client, linked_album)
    assert '<span class="chip">grunge</span>' in html
    assert "Em discurso direto" in html and "We made it fast" in html and "Kurt Cobain" in html
    assert 'href="https://e.org/s"' in html and "Wikiquote" in html
    assert "Wanted it huge" in html and "pull-quote" in html
    assert "In their own words" in _page(client, linked_album, "en")
