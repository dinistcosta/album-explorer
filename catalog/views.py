from django.db.models import Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils.translation import get_language

from sources.http import SourceNotFound, SourceUnavailable

from .models import Album
from .services.album_import import import_album_core
from .services.links import discogs_search_url, listen_and_buy
from .services.stories import select_story
from .services.refresh import enqueue_enrichment, needs_enrichment

MAX_POLLS = 15


def home(request):
    return render(request, "catalog/home.html")


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


def album_detail(request, mbid):
    album = Album.objects.select_related("artist", "reference_release").filter(mbid=mbid).first()
    if album is None:
        try:
            import_album_core(str(mbid), foreground=True)
        except SourceNotFound:
            raise Http404("album not found")
        except SourceUnavailable:
            return render(request, "catalog/503.html", status=503)
        album = Album.objects.select_related("artist", "reference_release").get(mbid=mbid)
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
    try:
        n = max(0, int(request.GET.get("n", 0)))
    except ValueError:
        n = 0
    return render(request, "catalog/_album_sections.html", {**_links_context(album), **_sections_context(album, n), "oob_links": True})
