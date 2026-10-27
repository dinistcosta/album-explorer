import httpx
import pytest
import respx
from django.core.management import call_command

from catalog.models import Album, Genre, GenreRanking
from catalog.seed_data import FEATURED_GENRES, SEED_ALBUMS
from tests.ids import NEVERMIND_RG

MB = "https://musicbrainz.org/ws/2/"
LASTFM = "https://ws.audioscrobbler.com/2.0/"


def test_seed_data_shape():
    assert 25 <= len(SEED_ALBUMS) <= 40 and len(set(SEED_ALBUMS)) == len(SEED_ALBUMS)
    assert NEVERMIND_RG in SEED_ALBUMS
    assert len(FEATURED_GENRES) >= 8


class Recorder:
    def __init__(self):
        self.ids = []

    def call(self, album_id):
        from django.utils import timezone
        self.ids.append(album_id)
        Album.objects.filter(pk=album_id).update(enriched_at=timezone.now())


@pytest.fixture
def seed_respx(mb_fixtures, settings, monkeypatch):
    settings.LASTFM_API_KEY = "k"
    monkeypatch.setattr("catalog.management.commands.seed.SEED_ALBUMS", [NEVERMIND_RG])
    rec = Recorder()
    monkeypatch.setattr("catalog.management.commands.seed.enrich_album", rec)
    mb_fixtures.get(MB + "genre/all").respond(text="rock\nshoegaze\nhip hop\nelectronic\njazz\nfado\npunk\nsoul\npolka\n")
    mb_fixtures.get(url__startswith=MB + "release-group?").respond(json={"release-groups": []})

    def lastfm(request):
        method = request.url.params["method"]
        if method == "tag.getinfo":
            return httpx.Response(200, json={"tag": {"name": "x", "wiki": {
                "summary": 'Genre text. <a href="https://www.last.fm/tag/x">Read more on Last.fm</a>'}}})
        return httpx.Response(200, json={"albums": {"album": [{"name": "Nevermind", "artist": {"name": "Nirvana"}}]}})

    mb_fixtures.lastfm = mb_fixtures.get(LASTFM).mock(side_effect=lastfm)
    mb_fixtures.recorder = rec
    return mb_fixtures


def test_seed_is_idempotent(db, seed_respx, capsys):
    call_command("seed")
    first = capsys.readouterr().out
    call_command("seed")
    second = capsys.readouterr().out
    assert Genre.objects.filter(featured=True).count() == len(FEATURED_GENRES)
    assert Genre.objects.count() == 9
    assert Genre.objects.get(slug="hip-hop").featured
    assert not Genre.objects.get(slug="polka").featured
    assert Album.objects.filter(mbid=NEVERMIND_RG).count() == 1
    assert seed_respx.recorder.ids and len(seed_respx.recorder.ids) == 1  # resumed run skipped the enriched album
    assert "skip" in second.lower() and first.strip()
    rock = Genre.objects.get(slug="rock")
    assert rock.description == "Genre text." and "last.fm/tag/rock" in rock.description_source_url


def test_seed_without_lastfm_key_notices_and_still_seeds(db, seed_respx, settings, capsys):
    settings.LASTFM_API_KEY = ""
    call_command("seed")
    out = capsys.readouterr().out
    assert "LASTFM_API_KEY" in out
    assert Genre.objects.filter(featured=True).exists() and Album.objects.filter(mbid=NEVERMIND_RG).exists()
    assert GenreRanking.objects.count() == 0 and Genre.objects.get(slug="rock").description == ""


def test_seed_skip_flags(db, seed_respx):
    call_command("seed", "--skip-albums", "--skip-rooms")
    assert Album.objects.count() == 0 and GenreRanking.objects.count() == 0
    assert Genre.objects.filter(featured=True).exists()
    call_command("seed", "--skip-albums")
    assert GenreRanking.objects.count() >= 1
    assert Album.objects.count() >= 0


def test_seed_survives_unavailable_album(db, seed_respx, capsys):
    seed_respx.get(MB + f"release-group/{NEVERMIND_RG}").respond(503)
    call_command("seed", "--skip-rooms")
    assert "failed" in capsys.readouterr().out.lower()
