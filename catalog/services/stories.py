"""Wikipedia stories: the article's own intro and selected sections, stored verbatim (CC BY-SA 4.0).

No translation and no generated text. All network I/O happens before the short `transaction.atomic()`.
"""
import re
from dataclasses import dataclass

from babel import Locale, UnknownLocaleError
from bs4 import BeautifulSoup
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _, override

from catalog.models import Album, Artist, Story
from catalog.services.text import normalize
from catalog.tasks import register_album_enricher, register_artist_enricher
from sources import discogs, lastfm, wikidata, wikipedia
from sources import musicbrainz as mb

KEEP_HEADINGS = {
    "en": ["background", "recording", "production", "composition", "release", "reception", "critical reception"],
    "pt": ["antecedentes", "contexto", "gravação", "produção", "composição", "lançamento", "recepção",
           "receção", "recepção crítica", "receção crítica"],
}
LICENSE = "CC BY-SA 4.0"
STRIP = ["sup.reference", "table", ".infobox", "figure", ".mw-editsection", ".reflist", "ol.references",
         ".navbox", ".hatnote", "style", ".thumb"]


LASTFM_LICENSE = "CC BY-SA 3.0"
OTHER_LANG = {"pt": "en", "en": "pt"}
SOURCE_LABELS = {"wikipedia": "Wikipedia", "lastfm": "Last.fm"}
FORMAT_ORDER = ["Vinyl", "CD", "Cassette", "Digital"]  # MB format substrings, in display order


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


# ---- Last.fm -----------------------------------------------------------------------------------

def _lastfm_text(info: dict | None, key: str) -> str:
    block = (info or {}).get(key) or {}
    return lastfm.clean_lastfm_wiki(block.get("content") or block.get("summary") or "")


def import_lastfm_stories(entity: Album | Artist) -> None:
    if not settings.LASTFM_API_KEY:
        return
    is_album = isinstance(entity, Album)
    infos: dict[str, dict | None] = {}
    for lang in ("en", "pt"):  # English first: it is the reference for "no translation" detection
        if is_album:
            artist_name = entity.artist.name if entity.artist else entity.artist_credit
            ref = entity.reference_release  # Last.fm wants a release MBID, not a release-group one
            infos[lang] = lastfm.album_info(
                artist_name, entity.title, str(ref.mbid) if ref else None, lang)
        else:
            infos[lang] = lastfm.artist_info(entity.name, str(entity.mbid), lang)

    key = "wiki" if is_album else "bio"
    texts = {lang: _lastfm_text(info, key) for lang, info in infos.items()}
    rows = []
    for lang in ("pt", "en"):
        text = texts[lang]
        if not text or (lang == "pt" and text == texts["en"]):
            continue
        rows.append((lang, infos[lang].get("url") or "", [{"heading": None, "paragraphs": text.split("\n\n")}]))

    listeners = None
    if is_album:
        raw = (infos["en"] or infos["pt"] or {}).get("listeners")
        listeners = int(raw) if str(raw).isdigit() else None

    owner = "album" if is_album else "artist"
    with transaction.atomic():
        for lang, url, sections in rows:
            Story.objects.update_or_create(
                **{owner: entity}, lang=lang, source="lastfm", is_manual=False,
                defaults={"url": url, "license": LASTFM_LICENSE, "sections": sections,
                          "fetched_at": timezone.now()},
            )
        if listeners is not None and entity.apply_source_fields(lastfm_listeners=listeners):
            entity.save(update_fields=["lastfm_listeners"])


register_album_enricher(import_lastfm_stories)
register_artist_enricher(import_lastfm_stories)


# ---- Discogs -----------------------------------------------------------------------------------

def _discogs_master_id(album: Album) -> str:
    if "discogs_master_id" in album.locked_fields and album.discogs_master_id:
        return album.discogs_master_id
    group = mb.get_release_group(str(album.mbid))
    for rel in group.get("relations") or []:
        if rel.get("type") != "discogs":
            continue
        match = re.search(r"/master/(\d+)", (rel.get("url") or {}).get("resource") or "")
        if match:
            return match.group(1)
    return album.discogs_master_id


def import_discogs_notes(album: Album) -> None:
    if not settings.DISCOGS_TOKEN:
        return
    master_id = _discogs_master_id(album)
    if not master_id:
        return
    master = discogs.get_master(master_id)
    if master is None:
        return
    release = discogs.get_release(master["main_release"]) if master.get("main_release") else None
    values = {"discogs_master_id": master_id, "discogs_styles": list(master.get("styles") or [])}
    if release is not None:
        values["discogs_notes"] = (release.get("notes") or "").strip()
    with transaction.atomic():
        changed = album.apply_source_fields(**values)
        if changed:
            album.save(update_fields=changed)


register_album_enricher(import_discogs_notes)


# ---- Fact sheet (generated, never translated by machine: fixed sentences filled with data) -----

def _join_names(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    return _("%(head)s and %(last)s") % {"head": ", ".join(names[:-1]), "last": names[-1]}


def _format_list(album: Album) -> list[str]:
    found = {f for release in album.releases.all() for f in release.formats or []}
    names = {"Vinyl": _("vinyl"), "CD": "CD", "Cassette": _("cassette"), "Digital": _("digital")}
    return [names[n] for n in FORMAT_ORDER if any(n.lower() in f.lower() for f in found)]


def _studio(album: Album):
    credits = [c for c in album.credits.filter(role="recorded at", place__isnull=False).select_related("place")
               .order_by("id")]
    if not credits:
        return None, ""
    dated = sorted((c for c in credits if c.begin_date), key=lambda c: c.begin_date)
    chosen = dated[0] if dated else credits[0]
    year = chosen.begin_date[:4] if chosen.begin_date[:4].isdigit() else ""
    return chosen.place, year


def build_fact_sheet(album: Album, lang: str) -> list[str]:
    with override(lang):
        sentences = []
        place, rec_year = _studio(album)
        if place is not None:
            args = {"year": rec_year, "studio": place.name, "area": place.area}
            if rec_year and place.area:
                sentences.append(_("Recorded in %(year)s at %(studio)s, %(area)s.") % args)
            elif rec_year:
                sentences.append(_("Recorded in %(year)s at %(studio)s.") % args)
            elif place.area:
                sentences.append(_("Recorded at %(studio)s, %(area)s.") % args)
            else:
                sentences.append(_("Recorded at %(studio)s.") % args)

        names = list(dict.fromkeys(
            c.person.name for c in album.credits.filter(role="producer", person__isnull=False)
            .select_related("person").order_by("id")))
        if names:
            sentences.append(_("Produced by %(names)s.") % {"names": _join_names(names)})

        label = album.reference_release.label if album.reference_release else ""
        if label:
            formats = _format_list(album)
            args = {"year": album.year, "label": label, "formats": _join_names(formats) if formats else ""}
            if album.year and formats:
                sentences.append(_("Released in %(year)s by %(label)s on %(formats)s.") % args)
            elif album.year:
                sentences.append(_("Released in %(year)s by %(label)s.") % args)
            elif formats:
                sentences.append(_("Released by %(label)s on %(formats)s.") % args)
            else:
                sentences.append(_("Released by %(label)s.") % args)
    return [" ".join(sentences)] if sentences else []


def _country_name(code: str, lang: str) -> str:
    try:
        return Locale.parse(lang).territories.get(code.upper(), "") if code else ""
    except (UnknownLocaleError, ValueError):
        return ""


def build_artist_fact_sheet(artist: Artist, lang: str) -> list[str]:
    country = _country_name(artist.country, lang)
    args = {"name": artist.name, "country": country, "year": artist.begin_year}
    year, c = bool(artist.begin_year), bool(country)
    with override(lang):
        if artist.artist_type == "Group":
            if year and c:
                text = _("%(name)s is a band formed in %(year)s (%(country)s).") % args
            elif year:
                text = _("%(name)s is a band formed in %(year)s.") % args
            elif c:
                text = _("%(name)s is a band (%(country)s).") % args
            else:
                text = _("%(name)s is a band.") % args
        elif year and c:
            text = _("Artist active since %(year)s (%(country)s).") % args
        elif year:
            text = _("Artist active since %(year)s.") % args
        elif c:
            text = _("Artist (%(country)s).") % args
        else:
            text = _("Artist.")
    return [text]


# ---- Story selection ---------------------------------------------------------------------------

@dataclass
class StoryView:
    sections: list[dict]
    source: str
    url: str
    license: str
    lang: str
    is_other_language: bool
    is_generated: bool
    notes: str = ""

    @property
    def source_label(self) -> str:
        if self.source in SOURCE_LABELS:
            return f"{SOURCE_LABELS[self.source]} ({self.lang.upper()})"
        return _("Editorial contribution") if self.source == "manual" else ""

    @property
    def visible_sections(self) -> list[dict]:
        return self.sections[:2]

    @property
    def more_sections(self) -> list[dict]:
        return self.sections[2:]

    @property
    def notes_paragraphs(self) -> list[str]:
        return [p.strip() for p in self.notes.splitlines() if p.strip()]


def _view(story: Story, lang: str) -> StoryView:
    return StoryView(
        sections=story.sections, source=story.source, url=story.url, license=story.license,
        lang=story.lang, is_other_language=story.lang != lang, is_generated=False,
    )


def select_story(entity: Album | Artist, lang: str) -> StoryView:
    stories = list(entity.stories.all())
    other = OTHER_LANG.get(lang, "en")
    candidates = [
        lambda s: s.is_manual and s.lang == lang,
        lambda s: s.source == "wikipedia" and s.lang == lang,
        lambda s: s.source == "wikipedia" and s.lang == other,
        lambda s: s.source == "lastfm" and s.lang == lang,
        lambda s: s.source == "lastfm" and s.lang == other,
    ]
    for matches in candidates:
        found = next((s for s in stories if matches(s) and s.sections), None)
        if found:
            return _view(found, lang)
    if isinstance(entity, Album):
        paragraphs = build_fact_sheet(entity, lang)
        notes = entity.discogs_notes
    else:
        paragraphs, notes = build_artist_fact_sheet(entity, lang), ""
    return StoryView(
        sections=[{"heading": None, "paragraphs": paragraphs}] if paragraphs else [], source="", url="",
        license="", lang=lang, is_other_language=False, is_generated=True, notes=notes,
    )
