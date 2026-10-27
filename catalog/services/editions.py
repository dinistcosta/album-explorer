import re

from catalog.services.text import normalize

_POSITION = re.compile(r"^([A-Za-z]+)\d+$")


def _sort_key(release: dict):
    date = release.get("date") or ""
    return (not date, date, release.get("id", ""))


def choose_reference_release(releases: list[dict]) -> dict:
    official = [r for r in releases if r.get("status") == "Official"]
    return min(official or releases, key=_sort_key)


def vinyl_candidates(releases: list[dict]) -> list[dict]:
    def is_vinyl(release):
        media = release.get("media") or []
        return bool(media) and all("Vinyl" in (m.get("format") or "") for m in media)

    return sorted((r for r in releases if is_vinyl(r)), key=_sort_key)


def _tracks(release: dict) -> list[dict]:
    return [t for m in release.get("media") or [] for t in m.get("tracks") or []]


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
