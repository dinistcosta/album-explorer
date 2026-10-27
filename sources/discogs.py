"""Discogs API client. Returns None (no request) when DISCOGS_TOKEN is unset or the id is unknown."""
from django.conf import settings

from . import http

SOURCE = "discogs"
BASE = "https://api.discogs.com"


def _get(path: str) -> dict | None:
    token = settings.DISCOGS_TOKEN
    if not token:
        return None
    try:
        return http.fetch(SOURCE, f"{BASE}{path}", headers={"Authorization": f"Discogs token={token}"})
    except http.SourceNotFound:
        return None


def get_master(id) -> dict | None:
    return _get(f"/masters/{id}")


def get_release(id) -> dict | None:
    return _get(f"/releases/{id}")
