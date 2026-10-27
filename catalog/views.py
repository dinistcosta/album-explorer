from django.db.models import Sum
from django.http import Http404, HttpResponsePermanentRedirect
from django.shortcuts import get_object_or_404, render
from django.conf import settings
from django.utils.translation import get_language, gettext

from sources.http import SourceNotFound, SourceUnavailable

from .models import Album, Artist, Genre, GenreRanking
from .services.album_import import import_album_core
from .services.artist_import import discography_sections, header_cover_album, import_artist_core
from .services.stories import _country_name
from .services.links import discogs_search_url, listen_and_buy
from .services.stories import select_story
from .services.search import search as run_search, suggest as run_suggest
from .services.genres_room import room_by_decade
from .services.merge import fold_merged_stub
from .services.refresh import enqueue_enrichment, enqueue_room, needs_enrichment

MAX_POLLS = 15


def home(request):
    return render(request, "catalog/home.html", {"featured_genres": Genre.objects.filter(featured=True).order_by("name")})


def _decade_label(decade):
    if decade is None:
        return gettext("Undated")
    shown = f"{decade % 100:02d}" if 1920 <= decade < 2000 and (get_language() or "").startswith("pt") else decade
    return gettext("%(decade)ss") % {"decade": shown}


def genre_detail(request, slug):
    genre = get_object_or_404(Genre, slug=slug)
    rankings = GenreRanking.objects.filter(genre=genre)
    unresolved = rankings.filter(resolved_at__isnull=True).exists()
    building = unresolved or (not rankings.exists() and bool(settings.LASTFM_API_KEY))
    if building:
        enqueue_room(genre)
    rooms = [{"label": _decade_label(d), "albums": albums} for d, albums in room_by_decade(genre)]
    return render(request, "catalog/genre_detail.html", {"genre": genre, "rooms": rooms, "building": building})


def search(request):
    q = request.GET.get("q", "").strip()[:200]
    results = run_search(q)
    return render(request, "catalog/search.html", {"q": q, "results": results, "searched": bool(q)})


def suggest(request):
    return render(request, "catalog/_suggestions.html", {"s": run_suggest(request.GET.get("q", "")[:200])})


def _tracks_by_side(album):
    release = album.reference_release
    if release is None:
        return []
    tracks = list(release.tracks.all())
    if not tracks:
        return []
    if all(t.side for t in tracks):
        groups = {}
        for t in tracks:
            groups.setdefault(t.side, []).append(t)
        return sorted(groups.items())
    return [(None, tracks)]


def _links_context(album):
    listen, buy = listen_and_buy(album)
    artist = album.artist.name if album.artist else album.artist_credit
    return {"listen_links": listen, "buy_links": buy, "discogs_url": discogs_search_url(artist, album.title)}


def _sections_context(album, n=0):
    credits = {}
    for c in album.credits.select_related("person", "place"):
        name = c.person.name if c.person else (c.place.name if c.place else "")
        if not name:
            continue
        names = credits.setdefault(c.role, [])
        if name not in names:
            names.append(name)
    all_quotes = list(album.quotes.order_by("id"))
    liner_quote = next((q for q in all_quotes if q.origin == "wikipedia"), None)  # pulled into the liner notes
    quotes = [q for q in all_quotes if q is not liner_quote]
    polling = album.enriched_at is None and n < MAX_POLLS
    return {
        "album": album,
        "credits": list(credits.items()),
        "other_releases": album.releases.exclude(pk=album.reference_release_id).order_by("date")[:12],
        "quotes": quotes,
        "liner_quote": liner_quote,
        "story": select_story(album, get_language()),
        "awards": list(album.awards.all()),
        "genres": [ag.genre for ag in album.album_genres.select_related("genre")],
        "polling": polling,
        "next_n": n + 1,
    }


def _poll_n(request) -> int:
    try:
        return max(0, int(request.GET.get("n", 0)))
    except ValueError:
        return 0


def album_detail(request, mbid):
    album = Album.objects.select_related("artist", "reference_release").filter(mbid=mbid).first()
    if album is None or album.imported_at is None:  # None: a stub created from an artist's discography
        try:
            imported = import_album_core(str(mbid), foreground=True)
        except SourceNotFound:
            raise Http404("album not found")
        except SourceUnavailable:
            return render(request, "catalog/503.html", status=503)
        if str(imported.mbid) != str(mbid):  # merged on MusicBrainz: send visitors to the canonical id
            fold_merged_stub(Album, str(mbid), imported)
            return HttpResponsePermanentRedirect(imported.get_absolute_url())
        album = Album.objects.select_related("artist", "reference_release").get(pk=imported.pk)
    if needs_enrichment(album):
        enqueue_enrichment(album)
    release = album.reference_release
    total_ms = release.tracks.aggregate(t=Sum("length_ms"))["t"] if release else None
    context = {
        "album": album,
        "tracks_by_side": _tracks_by_side(album),
        "total_minutes": round(total_ms / 60000) if total_ms else None,
        **_links_context(album),
        **_sections_context(album),
    }
    return render(request, "catalog/album_detail.html", context)


def album_enrichment(request, mbid):
    album = get_object_or_404(Album, mbid=mbid)
    if needs_enrichment(album):
        enqueue_enrichment(album)
    n = _poll_n(request)
    return render(request, "catalog/_album_sections.html", {**_links_context(album), **_sections_context(album, n), "oob_links": True})


ARTIST_LINK_NAMES = {
    "spotify": "Spotify", "apple_music": "Apple Music", "youtube": "YouTube", "bandcamp": "Bandcamp",
    "instagram": "Instagram", "facebook": "Facebook", "x": "X", "tiktok": "TikTok", "soundcloud": "SoundCloud",
}
LINK_ORDER = ["official", "listen", "social"]


def _artist_links(artist):
    seen, out = set(), []
    for link in sorted(artist.links.all(), key=lambda l: (LINK_ORDER.index(l.kind) if l.kind in LINK_ORDER else 9, l.id)):
        if (link.kind, link.service) in seen:
            continue
        seen.add((link.kind, link.service))
        out.append({"kind": link.kind, "service": link.service, "name": ARTIST_LINK_NAMES.get(link.service, ""), "url": link.url})
    return out


def _artist_context(artist, n=0):
    lang = get_language()
    header_album = None if artist.image_url else header_cover_album(artist)
    polling = artist.enriched_at is None and n < MAX_POLLS
    return {
        "artist": artist,
        "story": select_story(artist, lang),
        "quotes": list(artist.quotes.order_by("id")),
        "awards": list(artist.awards.all()),
        "genres": [ag.genre for ag in artist.artist_genres.select_related("genre")],
        "members": list(artist.memberships.select_related("member").order_by("begin_year", "id")),
        "links": _artist_links(artist),
        "influences": list(artist.influences.select_related("target_artist")),
        "discography": discography_sections(artist),
        "header_album": header_album,
        "country": _country_name(artist.country, lang),
        "polling": polling,
        "next_n": n + 1,
    }


def artist_detail(request, mbid):
    artist = Artist.objects.filter(mbid=mbid).first()
    if artist is None or artist.imported_at is None:  # None: a member / credit stub, never imported as a band
        try:
            imported = import_artist_core(str(mbid), foreground=True)
        except SourceNotFound:
            raise Http404("artist not found")
        except SourceUnavailable:
            if artist is None:
                return render(request, "catalog/503.html", status=503)
        else:
            if str(imported.mbid) != str(mbid):  # merged on MusicBrainz: send visitors to the canonical id
                fold_merged_stub(Artist, str(mbid), imported)
                return HttpResponsePermanentRedirect(imported.get_absolute_url())
            artist = Artist.objects.get(pk=imported.pk)
    if needs_enrichment(artist):
        enqueue_enrichment(artist)
    return render(request, "catalog/artist_detail.html", _artist_context(artist))


def artist_enrichment(request, mbid):
    artist = get_object_or_404(Artist, mbid=mbid)
    if needs_enrichment(artist):
        enqueue_enrichment(artist)
    n = _poll_n(request)
    return render(request, "catalog/_artist_sections.html", {**_artist_context(artist, n), "oob_photo": True})
