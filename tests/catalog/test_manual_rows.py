"""Hand-edited multi-row blocks (credits, awards, quotes, links) survive a refresh."""
import pytest
from django.urls import reverse

from catalog.models import Award, Credit, ExternalLink, Quote
from catalog.services.album_import import import_album_core
from catalog.services.artist_import import import_artist_core
from catalog.services.links import import_album_links, listen_and_buy
from catalog.services.quotes import import_quotes
from catalog.services.wikidata_import import import_album_wikidata
from sources.models import HttpCacheEntry
from tests.catalog.test_admin import change_url, form_data
from tests.catalog.test_artist import imported_nirvana, nirvana_respx  # noqa: F401  (fixtures)
from tests.catalog.test_quotes import quote_world  # noqa: F401  (fixture)
from tests.catalog.test_wikidata_import import wikidata_fixtures  # noqa: F401  (fixture)
from tests.ids import NEVERMIND_RG

SPOTIFY = "https://open.spotify.com/album/x"


def rg(*urls):
    return {"id": "x", "relations": [{"type": "streaming", "url": {"resource": u}} for u in urls]}


def _key(c):
    return (c.role, c.person_id, c.place_id, c.track_id)


# ---- credits --------------------------------------------------------------------------------

def test_edited_credit_is_not_duplicated_by_refresh(admin_client, imported_album):
    credit = Credit.objects.filter(album=imported_album, role="producer", person__name="Butch Vig").first()
    original = _key(credit)
    data = {"album": credit.album_id, "track": credit.track_id or "", "person": credit.person_id or "",
            "place": credit.place_id or "", "role": "co-producer", "attributes": "[]",
            "begin_date": credit.begin_date, "is_hidden": "", "_save": "Save"}
    assert admin_client.post(reverse("admin:catalog_credit_change", args=[credit.pk]), data).status_code == 302
    before = Credit.objects.filter(album=imported_album).count()
    import_album_core(NEVERMIND_RG, foreground=False)
    rows = list(Credit.objects.filter(album=imported_album))
    assert len(rows) == before
    assert not any(_key(c) == original and not c.is_hidden for c in rows)
    credit.refresh_from_db()
    assert credit.role == "co-producer" and credit.is_manual


def test_deleted_credit_stays_gone_after_refresh(admin_client, client, imported_album):
    credit = Credit.objects.filter(album=imported_album, role="engineer").first()
    name = credit.person.name
    admin_client.post(reverse("admin:catalog_credit_delete", args=[credit.pk]), {"post": "yes"})
    credit.refresh_from_db()
    assert credit.is_hidden and credit.is_manual
    import_album_core(NEVERMIND_RG, foreground=False)
    same = [c for c in Credit.objects.filter(album=imported_album) if _key(c) == _key(credit)]
    assert same == [credit]
    if not Credit.objects.filter(album=imported_album, person__name=name, is_hidden=False).exists():
        assert name not in client.get(f"/en/album/{NEVERMIND_RG}/").content.decode()


def test_deleting_a_manual_credit_deletes_it(admin_client, imported_album):
    credit = Credit.objects.create(album=imported_album, role="thanks", is_manual=True)
    admin_client.post(reverse("admin:catalog_credit_delete", args=[credit.pk]), {"post": "yes"})
    assert not Credit.objects.filter(pk=credit.pk).exists()


def test_bulk_delete_action_hides_imported_credits(admin_client, imported_album):
    pks = list(Credit.objects.filter(album=imported_album).values_list("pk", flat=True)[:2])
    admin_client.post(reverse("admin:catalog_credit_changelist"),
                      {"action": "delete_selected", "_selected_action": pks, "post": "yes"})
    assert Credit.objects.filter(pk__in=pks, is_hidden=True).count() == 2


# ---- links -----------------------------------------------------------------------------------

def test_admin_added_link_survives_refresh(admin_client, album_factory, no_sleep, monkeypatch):
    album = album_factory()
    data = form_data(admin_client, album)
    data.update({"links-TOTAL_FORMS": "1", "links-INITIAL_FORMS": "0", "links-0-kind": "listen",
                 "links-0-service": "bandcamp", "links-0-url": "https://band.bandcamp.com/album/y"})
    r = admin_client.post(change_url(album), data)
    assert r.status_code == 302, r.content.decode()[:2000]
    link = ExternalLink.objects.get(album=album)
    assert link.is_manual
    monkeypatch.setattr("catalog.services.links.mb.get_release_group", lambda mbid: rg(SPOTIFY))
    import_album_links(album)
    assert sorted(album.links.values_list("url", flat=True)) == ["https://band.bandcamp.com/album/y", SPOTIFY]


def test_deleted_imported_link_stays_hidden_after_refresh(admin_client, album_factory, no_sleep, monkeypatch):
    album = album_factory()
    monkeypatch.setattr("catalog.services.links.mb.get_release_group", lambda mbid: rg(SPOTIFY))
    import_album_links(album)
    link = album.links.get()
    data = form_data(admin_client, album)
    data["links-0-DELETE"] = "on"
    assert admin_client.post(change_url(album), data).status_code == 302
    link.refresh_from_db()
    assert link.is_hidden and link.is_manual
    import_album_links(album)
    assert album.links.count() == 1 and album.links.get().is_hidden
    assert listen_and_buy(album) == ([], [])


def test_edited_imported_link_url_is_not_readded(admin_client, album_factory, no_sleep, monkeypatch):
    album = album_factory()
    monkeypatch.setattr("catalog.services.links.mb.get_release_group", lambda mbid: rg(SPOTIFY))
    import_album_links(album)
    data = form_data(admin_client, album, **{"links-0-url": "https://open.spotify.com/album/fixed"})
    assert admin_client.post(change_url(album), data).status_code == 302
    import_album_links(album)
    visible = album.links.filter(is_hidden=False)
    assert list(visible.values_list("url", flat=True)) == ["https://open.spotify.com/album/fixed"]


def test_manual_artist_link_survives_artist_refresh(imported_nirvana):
    link = ExternalLink.objects.create(artist=imported_nirvana, kind="official", service="website",
                                       url="https://example.org/nirvana", is_manual=True)
    HttpCacheEntry.objects.all().delete()
    import_artist_core(str(imported_nirvana.mbid), foreground=False)
    assert ExternalLink.objects.filter(pk=link.pk).exists()


def test_hidden_artist_link_not_shown_or_recreated(client, imported_nirvana):
    link = imported_nirvana.links.first()
    link.is_hidden = link.is_manual = True
    link.save()
    import_artist_core(str(imported_nirvana.mbid), foreground=False)
    assert imported_nirvana.links.filter(url=link.url).count() == 1
    html = client.get(f"/en/artist/{imported_nirvana.mbid}/").content.decode()
    assert f'href="{link.url}"' not in html


# ---- quotes and awards -----------------------------------------------------------------------

def test_deleted_quote_stays_gone_after_refresh(admin_client, quote_world):
    album = quote_world.album
    import_quotes(album)
    first = album.quotes.order_by("id").first()
    text = first.text
    data = form_data(admin_client, album)
    idx = next(k.split("-")[1] for k, v in data.items() if k.startswith("quotes-") and k.endswith("-id")
               and v == str(first.pk))
    data[f"quotes-{idx}-DELETE"] = "on"
    assert admin_client.post(change_url(album), data).status_code == 302
    import_quotes(album)
    assert not album.quotes.filter(text=text, is_hidden=False).exists()
    assert album.quotes.filter(text=text, is_hidden=True).count() == 1


def test_edited_quote_is_not_duplicated(quote_world):
    album = quote_world.album
    import_quotes(album)
    q = album.quotes.order_by("id").first()
    q.speaker, q.is_manual = "Kurt", True  # as the admin save does
    q.save()
    import_quotes(album)
    assert album.quotes.filter(text=q.text).count() == 1


def test_hidden_award_stays_gone_after_refresh(db, imported_album, wikidata_fixtures, client):
    import_album_wikidata(imported_album)
    award = imported_album.awards.get()
    award.is_hidden = award.is_manual = True
    award.save()
    import_album_wikidata(imported_album)
    assert list(Award.objects.filter(album=imported_album)) == [award]
    html = client.get(f"/en/album/{imported_album.mbid}/sections/").content.decode()
    assert award.name_en not in html


def test_edited_award_is_not_duplicated(db, imported_album, wikidata_fixtures):
    import_album_wikidata(imported_album)
    award = imported_album.awards.get()
    Award.objects.filter(pk=award.pk).update(name_en="Diamond (SNEP)", is_manual=True)
    import_album_wikidata(imported_album)
    assert list(imported_album.awards.values_list("name_en", flat=True)) == ["Diamond (SNEP)"]
