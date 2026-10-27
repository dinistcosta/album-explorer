import copy
import json
from pathlib import Path

import httpx
import pytest
import respx

from catalog.models import Award, Influence
from catalog.services.wikidata_import import import_album_wikidata, import_artist_wikidata
from sources import wikidata
from sources.wikidata import wiki_titles, wikidata_id_from_rels
from tests.ids import NIRVANA

FIX = Path(__file__).parent.parent / "fixtures" / "wikidata"
API = "https://www.wikidata.org/w/api.php"


def load(name):
    return json.loads((FIX / name).read_text())


@pytest.fixture
def wikidata_fixtures(db, no_sleep):
    """Answers wbgetentities from recorded fixtures: entities by id, labels-only calls merged."""
    entities = {}
    for name in ("nevermind.json", "nirvana.json"):
        entities.update(load(name)["entities"])
    labels = {}
    for name in ("awards_labels.json", "nirvana_labels.json"):
        labels.update(load(name)["entities"])
    state = {"entity_overrides": {}}

    def answer(request):
        params = request.url.params
        ids = params["ids"].split("|")
        if "claims" in params["props"]:
            out = {i: state["entity_overrides"].get(i, entities.get(i, {"id": i})) for i in ids}
        else:
            out = {i: labels[i] for i in ids}
        return httpx.Response(200, json={"entities": out, "success": 1})

    with respx.mock(assert_all_called=False) as router:
        route = router.get(API).mock(side_effect=answer)
        router.api = route
        router.overrides = state["entity_overrides"]
        yield router


def test_wiki_titles():
    assert wiki_titles({"sitelinks": {"enwiki": {"title": "Nevermind"}}}) == {"enwiki": "Nevermind"}
    assert wiki_titles({"sitelinks": {"frwiki": {"title": "x"}, "ptwikiquote": {"title": "Q"}}}) == {
        "ptwikiquote": "Q"}
    assert wiki_titles({}) == {}


def test_wikidata_id_from_rels():
    rels = [{"type": "discogs", "url": {"resource": "https://x"}},
            {"type": "wikidata", "url": {"resource": "https://www.wikidata.org/wiki/Q17444"}}]
    assert wikidata_id_from_rels(rels) == "Q17444"
    assert wikidata_id_from_rels([]) is None


def test_get_entities_chunks_to_fifty(wikidata_fixtures):
    ids = [f"Q{n}" for n in range(1, 121)]
    wikidata_fixtures.api.mock(side_effect=lambda r: httpx.Response(
        200, json={"entities": {i: {"id": i} for i in r.url.params["ids"].split("|")}}))
    result = wikidata.get_entities(ids, props="labels")
    assert len(result) == 120
    assert wikidata_fixtures.api.call_count == 3


def test_awards_imported_with_both_labels(db, imported_album, wikidata_fixtures):
    import_album_wikidata(imported_album)
    imported_album.refresh_from_db()
    assert imported_album.wikidata_id == "Q17444"
    award = imported_album.awards.get()
    assert award.wikidata_id == "Q120443091"
    assert award.name_en == "SNEP diamond album"
    assert award.name_pt == "SNEP diamond album"  # no pt label: falls back to en
    assert award.year is None
    # one entity call plus one labels call
    assert wikidata_fixtures.api.call_count == 2


def test_award_year_from_p585(db, imported_album, wikidata_fixtures):
    entity = copy.deepcopy(load("nevermind.json")["entities"]["Q17444"])
    entity["claims"]["P166"][0]["qualifiers"] = {"P585": [{"snak": {"datavalue": {
        "value": {"time": "+1993-00-00T00:00:00Z"}}}}]}
    wikidata_fixtures.overrides["Q17444"] = entity
    import_album_wikidata(imported_album)
    assert imported_album.awards.get().year == 1993


def test_manual_award_survives_and_auto_awards_replaced(db, imported_album, wikidata_fixtures):
    manual = Award.objects.create(album=imported_album, name_en="Mine", name_pt="Meu", is_manual=True)
    Award.objects.create(album=imported_album, name_en="Stale", wikidata_id="Q1")
    import_album_wikidata(imported_album)
    import_album_wikidata(imported_album)
    names = sorted(imported_album.awards.values_list("name_en", flat=True))
    assert names == ["Mine", "SNEP diamond album"]
    assert imported_album.awards.filter(pk=manual.pk).exists()


def test_locked_wikidata_id_respected(db, imported_album, wikidata_fixtures):
    imported_album.wikidata_id = "Q999"
    imported_album.locked_fields = ["wikidata_id"]
    imported_album.save()
    import_album_wikidata(imported_album)
    imported_album.refresh_from_db()
    assert imported_album.wikidata_id == "Q999"


def test_album_without_wikidata_link_is_skipped(db, album_factory, wikidata_fixtures, monkeypatch):
    album = album_factory()
    monkeypatch.setattr("sources.musicbrainz.get_release_group", lambda mbid, **kw: {"relations": []})
    import_album_wikidata(album)
    assert wikidata_fixtures.api.call_count == 0
    assert not album.awards.exists()


def _nirvana(artist_factory, monkeypatch):
    artist = artist_factory(mbid=NIRVANA, name="Nirvana")
    monkeypatch.setattr("sources.musicbrainz.get_artist", lambda mbid, **kw: {"relations": [
        {"type": "wikidata", "url": {"resource": "https://www.wikidata.org/wiki/Q11649"}}]})
    return artist


def test_artist_image_and_influences(db, artist_factory, wikidata_fixtures, monkeypatch):
    artist = _nirvana(artist_factory, monkeypatch)
    import_artist_wikidata(artist)
    artist.refresh_from_db()
    assert artist.wikidata_id == "Q11649"
    assert artist.image_url == (
        "https://commons.wikimedia.org/wiki/Special:FilePath/Nirvana%20around%201992.jpg?width=600")
    assert artist.image_source_url == "https://commons.wikimedia.org/wiki/File:Nirvana_around_1992.jpg"
    assert artist.influences.count() == 8
    assert all(i.target_label for i in artist.influences.all())
    assert artist.awards.count() == 6  # 8 claims, 3 identical (SNEP, no year) collapse to 1
    assert wikidata_fixtures.api.call_count == 2  # entity + one combined labels call


def test_influence_links_existing_artist(db, artist_factory, wikidata_fixtures, monkeypatch):
    artist = _nirvana(artist_factory, monkeypatch)
    target = artist_factory(wikidata_id="Q188464")
    import_artist_wikidata(artist)
    assert artist.influences.get(target_wikidata_id="Q188464").target_artist == target
    assert artist.influences.filter(target_artist__isnull=True).count() == 7
    import_artist_wikidata(artist)  # replaced, not duplicated
    assert Influence.objects.filter(artist=artist).count() == 8


def test_locked_image_url_respected(db, artist_factory, wikidata_fixtures, monkeypatch):
    artist = _nirvana(artist_factory, monkeypatch)
    artist.image_url = "https://example.com/mine.jpg"
    artist.locked_fields = ["image_url"]
    artist.save()
    import_artist_wikidata(artist)
    artist.refresh_from_db()
    assert artist.image_url == "https://example.com/mine.jpg"
