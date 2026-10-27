import pytest

from sources.throttle import acquire_slot


def test_slots_are_spaced_by_min_interval(db, fake_clock):
    acquire_slot("musicbrainz", foreground=True)
    acquire_slot("musicbrainz", foreground=True)
    assert fake_clock.slept == pytest.approx(1.0)


def test_background_yields_to_recent_foreground(db, fake_clock):
    acquire_slot("musicbrainz", foreground=True)
    acquire_slot("musicbrainz", foreground=False)
    assert fake_clock.slept >= 2.0


def test_sources_are_independent(db, fake_clock):
    acquire_slot("musicbrainz", foreground=True)
    acquire_slot("wikipedia", foreground=True)
    assert fake_clock.slept == 0
