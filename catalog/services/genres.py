"""Album genres: tags from MusicBrainz, Last.fm and Discogs, kept only when they match a curated Genre."""
from django.db import transaction

from catalog.models import Album, AlbumGenre, ArtistGenre, Genre
from catalog.services.text import normalize
from catalog.tasks import register_album_enricher
from sources import lastfm
from sources import musicbrainz as mb


def match_genre(name: str) -> Genre | None:
    candidates = list(dict.fromkeys(
        c for c in (normalize(name), normalize(name.replace("&", " and ")), normalize(name.replace("-", ""))) if c))
    if not candidates:
        return None
    found = Genre.objects.filter(search_name__in=candidates).order_by("id").first()
    if found:
        return found
    compact = {c.replace(" ", "") for c in candidates}  # "hiphop" == "hip hop"
    for genre in Genre.objects.exclude(search_name="").order_by("id"):
        if genre.search_name.replace(" ", "") in compact:
            return genre
    return None


def attach_genres(entity, names: list[str], source: str) -> None:
    """Make `entity`'s genres for `source` exactly the known genres among `names`."""
    through, owner = (AlbumGenre, "album") if isinstance(entity, Album) else (ArtistGenre, "artist")
    genres = {g.pk: g for g in (match_genre(n) for n in names if n) if g}
    with transaction.atomic():
        through.objects.filter(**{owner: entity, "source": source}).exclude(genre_id__in=genres).delete()
        for genre in genres.values():
            through.objects.get_or_create(**{owner: entity, "genre": genre, "source": source})


def import_album_genres(album: Album) -> None:
    group = mb.get_release_group(str(album.mbid))
    artist = album.artist.name if album.artist else album.artist_credit
    attach_genres(album, [g["name"] for g in group.get("genres") or [] if g.get("name")], "musicbrainz")
    attach_genres(album, lastfm.album_top_tags(artist, album.title), "lastfm")
    attach_genres(album, list(album.discogs_styles or []), "discogs")


register_album_enricher(import_album_genres)
