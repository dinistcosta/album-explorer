from datetime import datetime, timedelta, timezone

import pytest


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
        }
        defaults.update(overrides)
        return Album.objects.create(**defaults)

    return make
