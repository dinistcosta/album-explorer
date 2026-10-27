from datetime import timedelta
from urllib.parse import quote

from . import http

SOURCE = "wikiquote"


def page_url(lang: str, title: str) -> str:
    return f"https://{lang}.wikiquote.org/wiki/{quote(title.replace(' ', '_'), safe='_(),')}"


def get_wikiquote_html(lang: str, title: str) -> str:
    """Rendered HTML of a Wikiquote page (same MediaWiki parse API as Wikipedia). Text is CC BY-SA."""
    try:
        data = http.fetch(
            SOURCE, f"https://{lang}.wikiquote.org/w/api.php",
            params={
                "action": "parse", "page": title, "prop": "text", "formatversion": 2,
                "redirects": 1, "format": "json",
            },
            ttl=timedelta(days=30),
        )
    except http.SourceNotFound:
        return ""
    return ((data.get("parse") or {}).get("text")) or ""
