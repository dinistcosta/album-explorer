import re
import unicodedata


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", " ", stripped).strip()


_DISCOGS_URL = re.compile(r"\[url=[^\]]*\](.*?)\[/url\]", re.IGNORECASE | re.DOTALL)
_DISCOGS_LINK = re.compile(r"\[([almr])=([^\]]*)\]", re.IGNORECASE)
_DISCOGS_ID = re.compile(r"\[[almr]\d+\]", re.IGNORECASE)
_DISCOGS_STYLE = re.compile(r"\[/?(?:b|i|u|url)\]", re.IGNORECASE)


def strip_discogs_markup(text: str) -> str:
    """Discogs notes markup removed, visible text kept: "[a=Kurt Cobain]" -> "Kurt Cobain",
    "[url=https://x]site[/url]" -> "site", "[b]x[/b]" -> "x"; bare id references ("[r123]") dropped."""
    text = _DISCOGS_URL.sub(r"\1", text or "")
    text = _DISCOGS_LINK.sub(lambda m: "" if m.group(2).strip().isdigit() else m.group(2), text)
    text = _DISCOGS_ID.sub("", text)
    text = _DISCOGS_STYLE.sub("", text)
    return "\n".join(re.sub(r"[ \t]{2,}", " ", line).strip() for line in text.splitlines()).strip()
