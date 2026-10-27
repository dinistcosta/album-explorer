from urllib.parse import quote

from django.core.management.base import BaseCommand
from django.template.defaultfilters import slugify
from django.conf import settings

from catalog.models import Album, Genre
from catalog.seed_data import FEATURED_GENRES, SEED_ALBUMS
from catalog.services.album_import import import_album_core
from catalog.services.refresh import needs_enrichment
from catalog.tasks import enrich_album, resolve_genre_room
from sources import lastfm
from sources import musicbrainz as mb
from sources.http import SourceNotFound, SourceUnavailable


class Command(BaseCommand):
    help = "Load genres, the curated seed albums and the featured genre rooms. Safe to re-run."

    def add_arguments(self, parser):
        parser.add_argument("--skip-albums", action="store_true", help="Do not import seed albums.")
        parser.add_argument("--skip-rooms", action="store_true", help="Do not resolve featured genre rooms.")

    def log(self, message):
        self.stdout.write(message)
        self.stdout.flush()

    def handle(self, *args, skip_albums=False, skip_rooms=False, **options):
        self.seed_genres()
        have_key = bool(settings.LASTFM_API_KEY)
        if have_key:
            self.seed_descriptions()
        else:
            self.log("LASTFM_API_KEY is not set: skipping genre descriptions and genre rooms.")
        if not skip_albums:
            self.seed_albums()
        if not skip_rooms and have_key:
            self.seed_rooms()
        self.log("Seed finished.")

    def seed_genres(self):
        try:
            names = mb.list_genres(foreground=True)
        except SourceUnavailable:
            self.log("MusicBrainz genre list unavailable; using the genres already stored.")
            names = []
        existing = {g.slug: g for g in Genre.objects.all()}
        created = 0
        for name in names:
            slug = slugify(name)[:120]
            if not slug:
                continue
            genre = existing.get(slug)
            if genre is None:
                existing[slug] = Genre.objects.create(slug=slug, name=name)
                created += 1
            elif genre.name != name:
                genre.name = name
                genre.save(update_fields=["name"])
        Genre.objects.filter(slug__in=FEATURED_GENRES).exclude(featured=True).update(featured=True)
        Genre.objects.filter(featured=True).exclude(slug__in=FEATURED_GENRES).update(featured=False)
        missing = [s for s in FEATURED_GENRES if s not in existing]
        self.log(f"Genres: {len(names)} from MusicBrainz, {created} new, {len(FEATURED_GENRES) - len(missing)} featured.")
        for slug in missing:
            self.log(f"  featured genre not found in MusicBrainz: {slug}")

    def seed_descriptions(self):
        for genre in Genre.objects.filter(featured=True, description=""):
            try:
                texts = {lang: lastfm.clean_lastfm_wiki(((lastfm.tag_info(genre.name, lang) or {}).get("wiki") or {}).get("summary", ""))
                         for lang in ("en", "pt")}
            except SourceUnavailable:
                self.log(f"  {genre.name}: Last.fm unavailable, description skipped")
                continue
            # Last.fm falls back to English when there is no Portuguese text: keep pt only if it differs.
            lang = "pt" if texts["pt"] and texts["pt"] != texts["en"] else "en"
            text = texts[lang]
            if not text:
                continue
            genre.description = text
            genre.description_lang = lang
            genre.description_source_url = f"https://www.last.fm/tag/{quote(genre.name)}"
            genre.save(update_fields=["description", "description_lang", "description_source_url"])
            self.log(f"  {genre.name}: description stored")

    def seed_albums(self):
        total = len(SEED_ALBUMS)
        for i, mbid in enumerate(SEED_ALBUMS, start=1):
            prefix = f"Album {i}/{total} {mbid}"
            album = Album.objects.filter(mbid=mbid).first()
            if album and album.imported_at and not needs_enrichment(album):
                self.log(f"{prefix}: skip (already enriched)")
                continue
            try:
                album = import_album_core(mbid, foreground=True)
                enrich_album.call(album.pk)
            except (SourceUnavailable, SourceNotFound) as exc:
                self.log(f"{prefix}: failed ({exc.__class__.__name__}); run seed again to resume")
                continue
            self.log(f"{prefix}: {album.title} imported and enriched")

    def seed_rooms(self):
        for genre in Genre.objects.filter(featured=True).order_by("name"):
            self.log(f"Room {genre.name}: resolving")
            try:
                resolve_genre_room.call(genre.pk)
            except Exception as exc:  # a failing room must not stop the others
                self.log(f"  {genre.name}: failed ({exc.__class__.__name__})")
                continue
            rows = genre.rankings.count()
            resolved = genre.rankings.filter(album__isnull=False).count()
            pending = genre.rankings.filter(resolved_at__isnull=True).count()
            if not rows:
                self.log(f"  {genre.name}: skipped (no ranking stored)")
            else:
                self.log(f"  {genre.name}: {rows} rankings stored, {resolved} matched, {pending} pending")
