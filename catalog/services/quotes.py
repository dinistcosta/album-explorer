"""Quotes: Wikiquote statements about the album and Wikipedia sentences quoting a named person.

Texts are stored verbatim with speaker and source (both sites are CC BY-SA). No translation, no generation.
All network I/O happens before the short `transaction.atomic()`.
"""
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, NavigableString, Tag
from django.db import transaction

from catalog.models import Album, Quote
from catalog.services.manual import manual_keys
from catalog.services.text import normalize
from catalog.services.wikidata_import import _item_ids, _label
from catalog.tasks import register_album_enricher
from sources import wikidata, wikipedia, wikiquote

MAX_QUOTES = 2
MAX_MEMBERS = 4
MAX_WIKIQUOTE_CHARS = 500
MIN_QUOTE_WORDS = 6
# h2 sections of a Wikiquote page that are not the subject's own statements.
SKIP_SECTIONS = ("song lyrics", "lyrics", "letras", "quotes about", "about", "sobre", "see also", "ver tambem",
                 "external links", "ligacoes externas", "ligacoes", "in song", "misattributed", "disputed",
                 "atribuidas", "atribuidos")


@dataclass
class QuoteData:
    text: str
    speaker: str
    source_label: str
    source_url: str
    origin: str


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _mentions(text: str, needles: list[str]) -> bool:
    haystack = f" {normalize(text)} "
    return any(n and f" {n} " in haystack for n in (normalize(x) for x in needles))


# ---- Wikiquote ---------------------------------------------------------------------------------

def extract_wikiquote_quotes(html: str, album_title: str, track_titles: list[str], speaker: str) -> list[QuoteData]:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one("div.mw-parser-output") or soup
    needles = [album_title, *track_titles]
    found: list[QuoteData] = []
    skipping = False
    for el in root.children:
        if not isinstance(el, Tag):
            continue
        classes = el.get("class") or []
        if el.name == "h2" or "mw-heading2" in classes:
            heading = normalize(_clean((el.find("h2") or el).get_text()).removesuffix("[edit]"))
            skipping = any(heading.startswith(s) for s in SKIP_SECTIONS)
            continue
        if skipping or el.name != "ul":
            continue
        for li in el.find_all("li", recursive=False):
            if li.find("br"):  # lyric lines, not a statement
                continue
            nested = li.find("ul")
            own = _clean("".join(
                c.get_text() if isinstance(c, Tag) else str(c)
                for c in li.children if c is not nested and getattr(c, "name", None) != "ul"))
            if not own or len(own) > MAX_WIKIQUOTE_CHARS:
                continue
            source = nested.find("li") if nested else None
            label = _clean(source.get_text()) if source else ""
            link = source.find("a", href=re.compile(r"^https?://")) if source else None
            if not _mentions(own, needles) and not _mentions(label, needles):
                continue
            found.append(QuoteData(own, speaker, label, link["href"] if link else "", "wikiquote"))
    return found


# ---- Wikipedia ---------------------------------------------------------------------------------

QUOTE_RE = re.compile(r'"([^"]+)"|“([^”]+)”|«([^»]+)»')
SENTENCE_END = re.compile(r"(?<=[.!?])(?:⟦[^⟧]*⟧)*\s+(?=[A-ZÀ-Ý])")


def _reference_entry(soup: BeautifulSoup, ref_id: str) -> tuple[str, str] | None:
    entry = soup.find(id=ref_id)
    if entry is None:
        return None
    holder = entry.find("cite") or entry.find(class_="reference-text") or entry
    label = _clean(holder.get_text())[:300]
    link = entry.find("a", href=re.compile(r"^https?://"))
    return (label, link["href"] if link else "") if label else None


def _sentences(paragraph: Tag) -> list[str]:
    """Paragraph text with reference markers kept as ⟦id⟧ tokens; quotes are never split."""
    for sup in paragraph.select("sup.reference"):
        anchor = sup.find("a", href=True)
        sup.replace_with(NavigableString(f"⟦{anchor['href'].lstrip('#')}⟧" if anchor else ""))
    text = _clean(paragraph.get_text())
    text = QUOTE_RE.sub(lambda m: m.group(0).replace(". ", ".\x00"), text)
    return [s.replace("\x00", " ") for s in SENTENCE_END.split(text)]


def extract_wikipedia_quotes(html: str, people: list[str]) -> list[QuoteData]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[QuoteData] = []
    for paragraph in soup.find_all("p"):
        for sentence in _sentences(paragraph):
            ref_ids = re.findall(r"⟦([^⟧]+)⟧", sentence)
            visible = re.sub(r"⟦[^⟧]*⟧", "", sentence)
            quotes = [next(g for g in m.groups() if g) for m in QUOTE_RE.finditer(visible)]
            quotes = [q.strip() for q in quotes if len(q.split()) >= MIN_QUOTE_WORDS]
            if not ref_ids or not quotes:
                continue
            outside = QUOTE_RE.sub(" ", visible)  # a name inside the quoted words is not the speaker
            named = [p for p in dict.fromkeys(people) if _mentions(outside, [p, p.split()[-1]])]
            if len(named) != 1:
                continue
            source = next((s for s in (_reference_entry(soup, r) for r in ref_ids) if s), None)
            if source:
                found.append(QuoteData(quotes[0], named[0], source[0], source[1], "wikipedia"))
    return found


# ---- Enricher ----------------------------------------------------------------------------------

def _people(album: Album) -> list[str]:
    names = []
    if album.artist:
        names += [m.member.name for m in album.artist.memberships.select_related("member").order_by("id")]
        names.append(album.artist.name)
    elif album.artist_credit:
        names.append(album.artist_credit)
    names += [c.person.name for c in album.credits.filter(role="producer", person__isnull=False, is_hidden=False)
              .select_related("person").order_by("id")]
    return list(dict.fromkeys(n for n in names if n))


def import_quotes(album: Album) -> None:
    people = _people(album)
    track_titles = []
    if album.reference_release:
        track_titles = list(album.reference_release.tracks.values_list("title", flat=True))

    rows: list[dict] = []
    if album.artist and album.artist.wikidata_id:
        qid = album.artist.wikidata_id
        entity = wikidata.get_entities([qid], props="sitelinks|claims|labels").get(qid) or {}
        pages = [(album.artist.name, wikidata.wiki_titles(entity))]  # the band/artist's own page first
        member_ids = _item_ids(entity, "P527")[:MAX_MEMBERS]
        if member_ids:  # one call for all members
            members = wikidata.get_entities(member_ids, props="sitelinks|labels")
            for mid in member_ids:
                member = members.get(mid) or {}
                name = _label(member, "en") or _label(member, "pt")
                if name:
                    pages.append((name, wikidata.wiki_titles(member)))
        for speaker, titles in pages:
            for lang in ("en", "pt"):  # reader-independent: English first
                title = titles.get(f"{lang}wikiquote")
                if not title:
                    continue
                html = wikiquote.get_wikiquote_html(lang, title)
                for q in extract_wikiquote_quotes(html, album.title, track_titles, speaker):
                    rows.append({
                        "text": q.text, "speaker": q.speaker[:300],
                        "source_label": (q.source_label or "Wikiquote")[:300],
                        "source_url": (q.source_url or wikiquote.page_url(lang, title))[:500],
                        "origin": "wikiquote", "lang": lang})
                break

    if album.wikidata_id:
        entity = wikidata.get_entities([album.wikidata_id], props="sitelinks").get(album.wikidata_id) or {}
        titles = wikidata.wiki_titles(entity)
        for lang in ("en", "pt"):
            title = titles.get(f"{lang}wiki")
            if not title:
                continue
            for q in extract_wikipedia_quotes(wikipedia.get_article_html(lang, title), people):
                rows.append({
                    "text": q.text, "speaker": q.speaker, "source_label": q.source_label,
                    "source_url": (q.source_url or wikipedia.article_url(lang, title))[:500], "origin": "wikipedia",
                    "lang": lang})

    order = {"wikiquote": 0, "wikipedia": 1}
    rows = sorted(rows, key=lambda r: order[r["origin"]])
    with transaction.atomic():
        kept = manual_keys(album.quotes.all())  # edited or deleted by hand
        rows = [r for r in rows if normalize(r["text"]) not in kept][:MAX_QUOTES]
        album.quotes.filter(is_manual=False).delete()
        for row in rows:
            Quote.objects.create(album=album, is_manual=False, **row)


register_album_enricher(import_quotes)
