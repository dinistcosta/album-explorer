"""A merged MusicBrainz id answers with the canonical entity: redirect there, never 500."""
import json
import re
from pathlib import Path

import httpx
import pytest
import respx

from catalog.models import Album, Artist, Credit, Membership
from tests.ids import NEVERMIND_RG, NIRVANA

pytestmark = pytest.mark.usefixtures("enqueued")

FIX = Path(__file__).parent.parent / "fixtures" / "musicbrainz"
BASE = "https://musicbrainz.org/ws/2/"
OLD = "99999999-9999-4999-8999-999999999999"


def load(name):
    return json.loads((FIX / name).read_text())


@pytest.fixture
def merged_album(db, mb_fixtures):
    mb_fixtures.get(f"{BASE}release-group/{OLD}").respond(200, json=load("nevermind_rg.json"))
    return mb_fixtures


@pytest.fixture
def merged_artist(db, no_sleep):
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}artist/{OLD}").respond(200, json=load("nirvana_artist.json"))
        router.get(url__regex=re.escape(BASE) + r"release-group\?").respond(
            200, json={"release-group-count": 0, "release-groups": []})
        yield router


def test_merged_album_mbid_redirects_to_canonical(client, merged_album):
    r = client.get(f"/pt/album/{OLD}/")
    assert r.status_code == 301 and r["Location"] == f"/pt/album/{NEVERMIND_RG}/"
    assert Album.objects.filter(mbid=NEVERMIND_RG).exists()
    r = client.get(f"/en/album/{OLD}/")
    assert r.status_code == 301 and r["Location"] == f"/en/album/{NEVERMIND_RG}/"


def test_merged_album_stub_is_removed(client, merged_album, artist_factory):
    Album.objects.create(mbid=OLD, title="Nevermind", artist=artist_factory())
    assert client.get(f"/pt/album/{OLD}/").status_code == 301
    assert not Album.objects.filter(mbid=OLD).exists()


def test_merged_album_stub_with_manual_data_is_kept(client, merged_album, artist_factory):
    stub = Album.objects.create(mbid=OLD, title="Nevermind", artist=artist_factory())
    Credit.objects.create(album=stub, role="thanks", is_manual=True)
    assert client.get(f"/pt/album/{OLD}/").status_code == 301
    assert Album.objects.filter(mbid=OLD).exists()


def test_merged_artist_mbid_redirects_to_canonical(client, merged_artist):
    r = client.get(f"/en/artist/{OLD}/")
    assert r.status_code == 301 and r["Location"] == f"/en/artist/{NIRVANA}/"


def test_merged_artist_stub_is_folded_into_canonical(client, merged_artist, artist_factory, album_factory):
    stub = artist_factory(mbid=OLD, name="Nirvana")
    band = artist_factory()
    membership = Membership.objects.create(band=band, member=stub)
    credit = Credit.objects.create(album=album_factory(), person=stub, role="producer")
    assert client.get(f"/pt/artist/{OLD}/").status_code == 301
    assert not Artist.objects.filter(mbid=OLD).exists()
    canonical = Artist.objects.get(mbid=NIRVANA)
    membership.refresh_from_db()
    credit.refresh_from_db()
    assert membership.member == canonical and credit.person == canonical


def test_merged_artist_stub_with_locked_fields_is_kept(client, merged_artist, artist_factory):
    artist_factory(mbid=OLD, name="Mine", locked_fields=["name"])
    assert client.get(f"/pt/artist/{OLD}/").status_code == 301
    assert Artist.objects.filter(mbid=OLD).exists()
