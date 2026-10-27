from django.db.models import Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from sources.http import SourceNotFound, SourceUnavailable

from .models import Album
from .services.album_import import import_album_core

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


def _sections_context(album, n=0):
    credits = {}
    for c in album.credits.select_related("person", "place"):
        name = c.person.name if c.person else (c.place.name if c.place else "")
        if not name:
            continue
        names = credits.setdefault(c.role, [])
        if name not in names:
            names.append(name)
    polling = album.enriched_at is None and n < MAX_POLLS
    return {
        "album": album,
        "credits": list(credits.items()),
        "other_releases": album.releases.exclude(pk=album.reference_release_id).order_by("date")[:12],
        "quotes": list(album.quotes.all()),
        "stories": list(album.stories.all()),
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
    release = album.reference_release
    total_ms = release.tracks.aggregate(t=Sum("length_ms"))["t"] if release else None
    context = {
        "album": album,
        "tracks_by_side": _tracks_by_side(album),
        "total_minutes": round(total_ms / 60000) if total_ms else None,
        **_sections_context(album),
    }
    return render(request, "catalog/album_detail.html", context)


def album_enrichment(request, mbid):
    album = get_object_or_404(Album, mbid=mbid)
    try:
        n = max(0, int(request.GET.get("n", 0)))
    except ValueError:
        n = 0
    return render(request, "catalog/_album_sections.html", _sections_context(album, n))
