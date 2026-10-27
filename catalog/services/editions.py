import re

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


def assign_sides(reference: dict, vinyl: dict) -> dict[str, str] | None:
    ref_tracks, vinyl_tracks = _tracks(reference), _tracks(vinyl)
    ref_ids = [t["recording"]["id"] for t in ref_tracks]
    vinyl_ids = [t["recording"]["id"] for t in vinyl_tracks]
    if not ref_ids or ref_ids != vinyl_ids:
        return None
    sides = {}
    for track in vinyl_tracks:
        match = _POSITION.match(track.get("number") or "")
        if not match:
            return None
        sides[track["recording"]["id"]] = match.group(1)
    return sides
