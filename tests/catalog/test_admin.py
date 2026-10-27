import re
from html.parser import HTMLParser
from unittest import mock

import pytest
from django.urls import reverse

from catalog.models import Album, Artist, Credit, Genre, Quote, Story
from catalog.services.album_import import import_album_core
from sources.http import SourceUnavailable


class _FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.data = {}
        self._in_form = False
        self._select = None
        self._textarea = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if not self._in_form:
            return
        name = a.get("name")
        if tag == "input" and name:
            t = a.get("type", "text")
            if t in ("submit", "button", "file"):
                return
            if t in ("checkbox", "radio"):
                if "checked" in a:
                    self.data[name] = a.get("value", "on")
                return
            self.data[name] = a.get("value", "")
        elif tag == "select" and name:
            self._select = name
            self.data.setdefault(name, "")
        elif tag == "option" and self._select and "selected" in a:
            self.data[self._select] = a.get("value", "")
        elif tag == "textarea" and name:
            self._textarea = name
            self.data[name] = ""

    def handle_endtag(self, tag):
        if tag == "select":
            self._select = None
        elif tag == "textarea":
            self._textarea = None

    def handle_data(self, data):
        if self._textarea:
            self.data[self._textarea] += data


def change_url(obj):
    return reverse(f"admin:catalog_{type(obj).__name__.lower()}_change", args=[obj.pk])


def form_data(client, obj, **overrides):
    """POST data built from the admin change form itself (inlines' management fields included)."""
    html = client.get(change_url(obj)).content.decode()
    p = _FormParser()
    p._in_form = True
    start = re.search(r"<form[^>]*id=\"\w+_form\"", html).start()
    p.feed(html[start:])
    data = dict(p.data)
    # textarea leading newline is not part of the value
    data = {k: (v[1:] if isinstance(v, str) and v.startswith("\n") else v) for k, v in data.items()}
    data.update(overrides)
    data["_save"] = "Save"
    return data


def test_admin_edit_locks_field(admin_client, imported_album):
    r = admin_client.post(change_url(imported_album),
                          form_data(admin_client, imported_album, title="Nevermind (corrigido)"))
    assert r.status_code == 302
    imported_album.refresh_from_db()
    assert imported_album.title == "Nevermind (corrigido)"
    assert imported_album.locked_fields == ["title"]


def test_admin_save_without_changes_locks_nothing(admin_client, imported_album):
    admin_client.post(change_url(imported_album), form_data(admin_client, imported_album))
    imported_album.refresh_from_db()
    assert imported_album.locked_fields == []


def test_admin_lock_is_deduped_and_skips_bookkeeping(admin_client, imported_album):
    imported_album.locked_fields = ["title"]
    imported_album.save()
    admin_client.post(change_url(imported_album),
                      form_data(admin_client, imported_album, title="Y", year="1990"))
    imported_album.refresh_from_db()
    assert sorted(imported_album.locked_fields) == ["title", "year"]
    page = admin_client.get(change_url(imported_album)).content.decode()
    for name in ("locked_fields", "search_name", "imported_at", "enriched_at"):
        assert f'name="{name}"' not in page


def test_artist_edit_locks_field(admin_client, artist_factory):
    a = artist_factory(name="Old")
    admin_client.post(change_url(a), form_data(admin_client, a, name="New"))
    a.refresh_from_db()
    assert a.name == "New" and a.locked_fields == ["name"]


def test_locked_field_survives_reimport(db, imported_album, mb_fixtures):
    imported_album.title = "X"
    imported_album.locked_fields = ["title"]
    imported_album.save()
    import_album_core(str(imported_album.mbid), foreground=False)
    imported_album.refresh_from_db()
    assert imported_album.title == "X"


def test_inline_story_marked_manual(admin_client, imported_album):
    data = form_data(admin_client, imported_album)
    data.update({
        "stories-TOTAL_FORMS": "1", "stories-INITIAL_FORMS": "0",
        "stories-0-lang": "pt", "stories-0-source": "manual",
        "stories-0-sections": '[{"heading": null, "paragraphs": ["Texto."]}]',
    })
    r = admin_client.post(change_url(imported_album), data)
    assert r.status_code == 302, r.content.decode()[:3000]
    story = Story.objects.get(album=imported_album, lang="pt")
    assert story.is_manual is True


def test_untouched_inline_rows_stay_unmanual(admin_client, imported_album):
    assert Credit.objects.filter(album=imported_album).exists()
    admin_client.post(change_url(imported_album), form_data(admin_client, imported_album))
    assert not Credit.objects.filter(album=imported_album, is_manual=True).exists()


def test_changed_inline_credit_marked_manual(admin_client, imported_album):
    credit = Credit.objects.filter(album=imported_album).first()
    data = form_data(admin_client, imported_album)
    data["credits-0-role"] = "mastering wizard"
    r = admin_client.post(change_url(imported_album), data)
    assert r.status_code == 302, r.content.decode()[:3000]
    credit_ids = [c.pk for c in imported_album.credits.all()]
    manual = Credit.objects.filter(album=imported_album, is_manual=True)
    assert manual.count() == 1 and manual[0].role == "mastering wizard"
    assert credit.pk in credit_ids


def test_inline_quote_on_artist_marked_manual(admin_client, artist_factory):
    a = artist_factory()
    data = form_data(admin_client, a)
    data.update({
        "quotes-TOTAL_FORMS": "1", "quotes-INITIAL_FORMS": "0",
        "quotes-0-text": "Hi", "quotes-0-origin": "manual",
    })
    r = admin_client.post(change_url(a), data)
    assert r.status_code == 302, r.content.decode()[:3000]
    assert Quote.objects.get(artist=a).is_manual is True


def test_unlock_all_action(admin_client, imported_album):
    imported_album.locked_fields = ["title", "year"]
    imported_album.save()
    admin_client.post(reverse("admin:catalog_album_changelist"),
                      {"action": "unlock_all", "_selected_action": [imported_album.pk]})
    imported_album.refresh_from_db()
    assert imported_album.locked_fields == []


def test_refresh_now_album(admin_client, imported_album):
    with mock.patch("catalog.admin.import_album_core") as imp, \
            mock.patch("catalog.admin.enqueue_enrichment") as enq:
        admin_client.post(reverse("admin:catalog_album_changelist"),
                          {"action": "refresh_now", "_selected_action": [imported_album.pk]})
    imp.assert_called_once_with(str(imported_album.mbid), foreground=False)
    enq.assert_called_once()


def test_refresh_now_album_source_unavailable_is_message(admin_client, imported_album):
    with mock.patch("catalog.admin.import_album_core", side_effect=SourceUnavailable("down")), \
            mock.patch("catalog.admin.enqueue_enrichment") as enq:
        r = admin_client.post(reverse("admin:catalog_album_changelist"),
                              {"action": "refresh_now", "_selected_action": [imported_album.pk]},
                              follow=True)
    assert r.status_code == 200
    assert any(m.level_tag == "error" for m in r.context["messages"])
    enq.assert_not_called()


def test_refresh_now_artist_only_enqueues(admin_client, artist_factory):
    a = artist_factory()
    with mock.patch("catalog.admin.enqueue_enrichment") as enq:
        admin_client.post(reverse("admin:catalog_artist_changelist"),
                          {"action": "refresh_now", "_selected_action": [a.pk]})
    enq.assert_called_once_with(a)


def test_genre_admin_list(admin_client, genre_factory):
    genre_factory(name="shoegaze", featured=True)
    r = admin_client.get(reverse("admin:catalog_genre_changelist") + "?featured__exact=1")
    assert r.status_code == 200 and b"shoegaze" in r.content


def test_language_switcher_still_works(client):
    r = client.post(reverse("set_language"), {"language": "en", "next": "/en/"})
    assert r.status_code == 302
