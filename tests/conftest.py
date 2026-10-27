from datetime import datetime, timedelta, timezone

import json
import re
from pathlib import Path

import httpx
import pytest
import respx

from tests.ids import NEVERMIND_RG

FIX = Path(__file__).parent / "fixtures" / "musicbrainz"
BASE = "https://musicbrainz.org/ws/2/"


def load(name):
    return json.loads((FIX / name).read_text())


class FakeClock:
    def __init__(self):
        self.current = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.slept = 0.0

    def now(self):
        return self.current

    def sleep(self, seconds):
        self.slept += seconds
        self.current += timedelta(seconds=seconds)


@pytest.fixture
def fake_clock(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr("sources.throttle.now", clock.now)
    monkeypatch.setattr("sources.throttle.sleep", clock.sleep)
    monkeypatch.setattr("sources.http.sleep", clock.sleep)
    return clock


@pytest.fixture(autouse=False)
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr("sources.throttle.sleep", lambda s: None)
    monkeypatch.setattr("sources.http.sleep", slept.append)
    return slept


@pytest.fixture
def artist_factory(db):
    import uuid

    from catalog.models import Artist

    def make(**overrides):
        n = uuid.uuid4().hex[:8]
        defaults = {"mbid": uuid.uuid4(), "name": f"Artist {n}", "sort_name": f"Artist {n}"}
        defaults.update(overrides)
        return Artist.objects.create(**defaults)

    return make


@pytest.fixture
def album_factory(db, artist_factory):
    import uuid

    from catalog.models import Album

    def make(**overrides):
        n = uuid.uuid4().hex[:8]
        if "artist" not in overrides:
            overrides["artist"] = artist_factory()
        defaults = {
            "mbid": uuid.uuid4(),
            "title": f"Album {n}",
            "artist_credit": overrides["artist"].name if overrides["artist"] else "",
            "primary_type": "Album",
            "imported_at": datetime(2026, 1, 1, tzinfo=timezone.utc),  # a full import, not a discography stub
        }
        defaults.update(overrides)
        return Album.objects.create(**defaults)

    return make


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
        router.full_release = router.get(
            url__regex=re.escape(BASE) + r"release/[0-9a-f-]{36}\?").mock(side_effect=full_release)
        router.get(url__regex=re.escape(BASE) + r"release\?").respond(200, json={
            "release-count": len(releases), "releases": releases})
        router.reference_id = choose_reference_release(releases)["id"]
        router.vinyl_ids = vinyl_ids
        yield router


@pytest.fixture
def imported_album(db, mb_fixtures):
    from catalog.services.album_import import import_album_core

    return import_album_core(NEVERMIND_RG, foreground=True)


@pytest.fixture(autouse=True)
def immediate_tasks(settings):
    settings.TASKS = {"default": {"BACKEND": "django.tasks.backends.immediate.ImmediateBackend"}}


@pytest.fixture
def enqueued(monkeypatch):
    """Records (task_name, object_id) instead of enqueueing, so view tests run no enrichers."""
    calls = []

    def fake(obj):
        calls.append(("enrich_album" if type(obj).__name__ == "Album" else "enrich_artist", obj.pk))

    monkeypatch.setattr("catalog.views.enqueue_enrichment", fake)
    return calls


@pytest.fixture
def genre_factory(db):
    from catalog.models import Genre

    def make(**overrides):
        name = overrides.pop("name", "shoegaze")
        defaults = {"slug": name.replace(" ", "-"), "name": name}
        defaults.update(overrides)
        return Genre.objects.create(**defaults)

    return make
