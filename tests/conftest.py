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
