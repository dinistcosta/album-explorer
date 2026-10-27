"""Wikipedia stories: the article's own intro and selected sections, stored verbatim (CC BY-SA 4.0).

No translation and no generated text. All network I/O happens before the short `transaction.atomic()`.
"""
import re

from bs4 import BeautifulSoup
from django.db import transaction
from django.utils import timezone

from catalog.models import Album, Artist, Story
from catalog.services.text import normalize
from catalog.tasks import register_album_enricher, register_artist_enricher
from sources import wikidata, wikipedia

KEEP_HEADINGS = {
    "en": ["background", "recording", "production", "composition", "release", "reception", "critical reception"],
    "pt": ["antecedentes", "contexto", "gravação", "produção", "composição", "lançamento", "recepção",
           "receção", "recepção crítica", "receção crítica"],
}
LICENSE = "CC BY-SA 4.0"
STRIP = ["sup.reference", "table", ".infobox", "figure", ".mw-editsection", ".reflist", "ol.references",
         ".navbox", ".hatnote", "style", ".thumb"]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_wikipedia_html(html: str, lang: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    for selector in STRIP:
        for node in soup.select(selector):
            node.decompose()
    keep = [normalize(h) for h in KEEP_HEADINGS[lang]]

    intro = {"heading": None, "paragraphs": []}
    sections: list[dict] = [intro]
    current: dict | None = intro  # None while inside a dropped h2
    for el in soup.find_all(["h2", "h3", "h4", "p"]):
        if el.name == "h2":
            heading = _clean(el.get_text())
            if any(normalize(heading).startswith(k) for k in keep):
                current = {"heading": heading, "paragraphs": []}
                sections.append(current)
            else:
                current = None
        elif el.name == "p" and current is not None:
            text = _clean(el.get_text())
            if text:
                current["paragraphs"].append(text)
    return [s for s in sections if s["paragraphs"]]


def import_wikipedia_stories(entity: Album | Artist) -> None:
    if not entity.wikidata_id:
        return
    wikidata_entity = wikidata.get_entities([entity.wikidata_id], props="sitelinks").get(entity.wikidata_id) or {}
    titles = wikidata.wiki_titles(wikidata_entity)
    owner = "album" if isinstance(entity, Album) else "artist"

    fetched = []
    for lang in ("pt", "en"):
        title = titles.get(f"{lang}wiki")
        if not title:
            continue
        sections = parse_wikipedia_html(wikipedia.get_article_html(lang, title), lang)
        if sections:
            fetched.append((lang, wikipedia.article_url(lang, title), sections))

    with transaction.atomic():
        for lang, url, sections in fetched:
            Story.objects.update_or_create(
                **{owner: entity}, lang=lang, source="wikipedia", is_manual=False,
                defaults={"url": url, "license": LICENSE, "sections": sections, "fetched_at": timezone.now()},
            )


register_album_enricher(import_wikipedia_stories)
register_artist_enricher(import_wikipedia_stories)
