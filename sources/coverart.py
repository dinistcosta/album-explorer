from .http import SourceNotFound, fetch

SOURCE = "coverart"


def cover_url(release_group_mbid: str) -> str:
    return f"https://coverartarchive.org/release-group/{release_group_mbid}/front-500"


def fetch_cover(release_group_mbid: str) -> bytes | None:
    """Cover bytes, or None when the archive has no front cover (404)."""
    try:
        return fetch(SOURCE, cover_url(release_group_mbid), binary=True)
    except SourceNotFound:
        return None
