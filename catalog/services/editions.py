import calendar
import re

from catalog.services.text import normalize

_POSITION = re.compile(r"^([A-Za-z]+)\d+$")
_COUNTRY_RANK = {"XW": 0, "US": 1, "GB": 2}


def _latest_day(date: str) -> str:
    """A partial date sorts as the last day of its period: "1991" -> "1991-12-31"."""
    parts = date.split("-")
    try:
        year = int(parts[0])
        if len(parts) == 1:
            return f"{year:04d}-12-31"
        month = int(parts[1])
        if len(parts) == 2:
            return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
        return f"{year:04d}-{month:02d}-{int(parts[2]):02d}"
    except (ValueError, IndexError, calendar.IllegalMonthError):
        return date


def _sort_key(release: dict):
    date = release.get("date") or ""
    country = release.get("country") or ""
    return (not date, _latest_day(date), _COUNTRY_RANK.get(country, 3), release.get("id", ""))


def choose_reference_release(releases: list[dict]) -> dict:
    official = [r for r in releases if r.get("status") == "Official"]
    return min(official or releases, key=_sort_key)


def is_all_vinyl(release: dict) -> bool:
    media = release.get("media") or []
    return bool(media) and all("Vinyl" in (m.get("format") or "") for m in media)


def vinyl_candidates(releases: list[dict]) -> list[dict]:
    return sorted((r for r in releases if is_all_vinyl(r)), key=_sort_key)


def _tracks(release: dict) -> list[dict]:
    return [t for m in release.get("media") or [] for t in m.get("tracks") or []]


def own_sides(release: dict) -> dict[str, str] | None:
    """Sides read straight from an all-vinyl release numbered A1, A2, B1…; None otherwise."""
    tracks = _tracks(release)
    if not tracks or not is_all_vinyl(release):
        return None
    sides = {}
    for t in tracks:
        match = _POSITION.match(t.get("number") or "")
        if not match:
            return None
        sides[t["recording"]["id"]] = match.group(1)
    return sides


def _same_track(ref: dict, vin: dict) -> bool:
    if ref["recording"]["id"] == vin["recording"]["id"]:
        return True
    a, b = normalize(ref.get("title") or ""), normalize(vin.get("title") or "")
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


def assign_sides(reference: dict, vinyl: dict) -> dict[str, str] | None:
    """Map reference recording mbid -> side letter, or None if the vinyl does not line up."""
    ref_tracks, vinyl_tracks = _tracks(reference), _tracks(vinyl)
    if not ref_tracks or len(ref_tracks) != len(vinyl_tracks):
        return None
    sides = {}
    for ref, vin in zip(ref_tracks, vinyl_tracks):
        match = _POSITION.match(vin.get("number") or "")
        if not match or not _same_track(ref, vin):
            return None
        sides[ref["recording"]["id"]] = match.group(1)
    return sides
