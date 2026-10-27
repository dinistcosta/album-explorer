from datetime import timedelta
from urllib.parse import quote

from . import http

SOURCE = "wikipedia"


def article_url(lang: str, title: str) -> str:
    return f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'), safe='_(),')}"


def get_article_html(lang: str, title: str) -> str:
    data = http.fetch(
        SOURCE, f"https://{lang}.wikipedia.org/w/api.php",
        params={
            "action": "parse", "page": title, "prop": "text", "formatversion": 2,
            "redirects": 1, "format": "json",
        },
        ttl=timedelta(days=30),
    )
    return ((data.get("parse") or {}).get("text")) or ""
