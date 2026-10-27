import json
import re
from pathlib import Path

import httpx
import pytest
import respx

from catalog.models import Album, Credit, Place, Release, Track
from catalog.services.album_import import apply_vinyl_sides, import_album_core
from sources.http import SourceNotFound
from tests.ids import NEVERMIND_RG, NIRVANA

FIX = Path(__file__).parent.parent / "fixtures" / "musicbrainz"
BASE = "https://musicbrainz.org/ws/2/"


def load(name):
    return json.loads((FIX / name).read_text())


@pytest.fixture
def mb_fixtures(no_sleep):
    """The recorded browse list's rule-chosen reference/vinyl ids differ from the recorded
    full-release fixtures, so full-release requests are answered with the recorded reference
    (or vinyl) payload re-labelled with the requested id."""
    from catalog.services.editions import choose_reference_release, vinyl_candidates

    releases = load("nevermind_releases.json")["releases"]
    vinyl_ids = {r["id"] for r in vinyl_candidates(releases)}
    router = respx.mock(assert_all_called=False)

    def full_release(request):
        rid = request.url.path.rsplit("/", 1)[1]
        data = load("nevermind_vinyl.json" if rid in vinyl_ids else "nevermind_reference.json")
        return httpx.Response(200, json={**data, "id": rid})

    with router:
        router.get(f"{BASE}release-group/{NEVERMIND_RG}").respond(200, json=load("nevermind_rg.json"))
        router.get(url__regex=re.escape(BASE) + r"release/[0-9a-f-]{36}\?").mock(side_effect=full_release)
        router.get(url__regex=re.escape(BASE) + r"release\?").respond(200, json={
            "release-count": len(releases), "releases": releases})
        router.reference_id = choose_reference_release(releases)["id"]
        router.vinyl_ids = vinyl_ids
        yield router


def test_import_nevermind(db, mb_fixtures):
    album = import_album_core(NEVERMIND_RG, foreground=True)
    assert album.title == "Nevermind" and album.artist.name == "Nirvana" and album.year == 1991
    assert str(album.artist.mbid) == NIRVANA
    assert str(album.reference_release.mbid) == mb_fixtures.reference_id
    assert album.reference_release.tracks.count() >= 12
    assert album.imported_at is not None
    assert Release.objects.filter(album=album).count() > 1
    assert Credit.objects.filter(album=album, role="producer", person__name="Butch Vig").exists()
    assert Credit.objects.filter(album=album, role="recorded at", place__isnull=False, track__isnull=False).exists()
    assert Place.objects.exists()
    assert any("guitar" in c.attributes for c in Credit.objects.filter(album=album, role="instrument"))


def test_reimport_is_idempotent(db, mb_fixtures):
    import_album_core(NEVERMIND_RG, foreground=True)
    counts = (Album.objects.count(), Release.objects.count(), Track.objects.count(), Credit.objects.count())
    import_album_core(NEVERMIND_RG, foreground=True)
    assert counts == (Album.objects.count(), Release.objects.count(), Track.objects.count(), Credit.objects.count())


def test_import_keeps_manual_credit(db, mb_fixtures):
    album = import_album_core(NEVERMIND_RG, foreground=True)
    track = album.reference_release.tracks.first()
    manual = Credit.objects.create(album=album, role="thanks", is_manual=True)
    manual_track = Credit.objects.create(album=album, track=track, role="hand", is_manual=True)
    import_album_core(NEVERMIND_RG, foreground=True)
    assert Credit.objects.filter(pk=manual.pk).exists()
    assert Credit.objects.filter(pk=manual_track.pk).exists()


def test_import_respects_locked_fields(db, mb_fixtures):
    import_album_core(NEVERMIND_RG, foreground=True)
    Album.objects.update(title="Mine", locked_fields=["title"])
    album = import_album_core(NEVERMIND_RG, foreground=True)
    assert album.title == "Mine"


def test_import_unknown_mbid_raises_not_found(db, no_sleep):
    with respx.mock:
        respx.get(url__regex=r".*").respond(404, json={"error": "Not Found"})
        with pytest.raises(SourceNotFound):
            import_album_core("00000000-0000-0000-0000-000000000000", foreground=True)
    assert not Album.objects.exists()


def test_recorded_vinyl_gets_sides_from_recorded_reference():
    from catalog.services.editions import assign_sides

    sides = assign_sides(load("nevermind_reference.json"), load("nevermind_vinyl.json"))
    assert sorted(sides.values()) == ["A"] * 6 + ["B"] * 6


def test_apply_vinyl_sides_with_recorded_fixtures(db, mb_fixtures):
    album = import_album_core(NEVERMIND_RG, foreground=True)
    apply_vinyl_sides(album)
    sides = list(album.reference_release.tracks.values_list("side", flat=True))
    assert sides == ["A"] * 6 + ["B"] * 6


def test_apply_vinyl_sides_sets_sides_on_match(db, mb_fixtures):
    album = import_album_core(NEVERMIND_RG, foreground=True)
    vinyl = load("nevermind_vinyl.json")
    ref = load("nevermind_reference.json")
    ref_tracks = [t for m in ref["media"] for t in m["tracks"]]
    for vt, rt in zip((t for m in vinyl["media"] for t in m["tracks"]), ref_tracks):
        vt["recording"]["id"] = rt["recording"]["id"]
    mb_fixtures.get(url__regex=re.escape(BASE) + r"release/[0-9a-f-]{36}\?").mock(
        side_effect=lambda request: httpx.Response(200, json=vinyl))
    apply_vinyl_sides(album)
    sides = list(album.reference_release.tracks.values_list("side", flat=True))
    assert sides == ["A"] * 6 + ["B"] * 6
