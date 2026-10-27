from datetime import timedelta
from time import sleep  # noqa: F401  (module-level so tests can patch it)

from django.db import transaction
from django.utils import timezone

from .models import SourceThrottle

MIN_INTERVAL = {
    "musicbrainz": 1.0,
    "discogs": 1.0,
    "lastfm": 0.25,
    "wikipedia": 0.1,
    "wikidata": 0.1,
    "wikiquote": 0.1,
    "coverart": 0.1,
}
FOREGROUND_PRIORITY_WINDOW = timedelta(seconds=2)


def now():
    return timezone.now()


def acquire_slot(source: str, *, foreground: bool) -> None:
    """Reserve the next request slot for `source`, then sleep until it starts."""
    with transaction.atomic():
        current = now()
        row, _ = SourceThrottle.objects.select_for_update().get_or_create(
            source=source, defaults={"next_allowed_at": current}
        )
        start = max(current, row.next_allowed_at)
        if not foreground and row.last_foreground_at:
            start = max(start, row.last_foreground_at + FOREGROUND_PRIORITY_WINDOW)
        row.next_allowed_at = start + timedelta(seconds=MIN_INTERVAL[source])
        if foreground:
            row.last_foreground_at = current
        row.save()
    delay = (start - current).total_seconds()
    if delay > 0:
        sleep(delay)
