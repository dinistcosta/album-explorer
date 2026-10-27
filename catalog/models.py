from django.db import models
from django.urls import reverse

from catalog.services.text import normalize


def _sync_search_name(kwargs, source_field):
    uf = kwargs.get("update_fields")
    if uf is not None and source_field in uf and "search_name" not in uf:
        kwargs["update_fields"] = [*uf, "search_name"]


class LockableModel(models.Model):
    locked_fields = models.JSONField(default=list, blank=True)

    class Meta:
        abstract = True

    def apply_source_fields(self, **values) -> list[str]:
        """Set every non-locked field; return names of fields whose value changed."""
        changed = []
        for name, value in values.items():
            if name in self.locked_fields:
                continue
            if getattr(self, name) != value:
                setattr(self, name, value)
                changed.append(name)
        return changed


class Artist(LockableModel):
    mbid = models.UUIDField(unique=True)
    name = models.CharField(max_length=300)
    sort_name = models.CharField(max_length=300, blank=True)
    search_name = models.CharField(max_length=300, db_index=True, blank=True)
    country = models.CharField(max_length=8, blank=True)
    begin_year = models.IntegerField(null=True, blank=True)
    end_year = models.IntegerField(null=True, blank=True)
    artist_type = models.CharField(max_length=32, blank=True)
    wikidata_id = models.CharField(max_length=32, blank=True)
    discogs_id = models.CharField(max_length=32, blank=True)
    image_url = models.URLField(max_length=500, blank=True)
    image_source_url = models.URLField(max_length=500, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    enriched_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        self.search_name = normalize(self.name)
        _sync_search_name(kwargs, "name")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Album(LockableModel):
    mbid = models.UUIDField(unique=True)
    title = models.CharField(max_length=500)
    search_name = models.CharField(max_length=500, db_index=True, blank=True)
    artist = models.ForeignKey(Artist, null=True, blank=True, on_delete=models.SET_NULL, related_name="albums")
    artist_credit = models.CharField(max_length=500, blank=True)
    year = models.IntegerField(null=True, blank=True)
    primary_type = models.CharField(max_length=32, blank=True)
    secondary_types = models.JSONField(default=list, blank=True)
    reference_release = models.ForeignKey(
        "Release", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    cover_url = models.URLField(max_length=500, blank=True)
    accent_color = models.CharField(max_length=16, blank=True, default="")
    wikidata_id = models.CharField(max_length=32, blank=True)
    discogs_master_id = models.CharField(max_length=32, blank=True)
    discogs_styles = models.JSONField(default=list, blank=True)
    discogs_notes = models.TextField(blank=True)
    lastfm_listeners = models.IntegerField(null=True, blank=True)  # sorting only, never displayed
    imported_at = models.DateTimeField(null=True, blank=True)
    enriched_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        self.search_name = normalize(self.title)
        _sync_search_name(kwargs, "title")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("album_detail", kwargs={"mbid": self.mbid})

    def __str__(self):
        return self.title


class Release(models.Model):
    mbid = models.UUIDField(unique=True)
    album = models.ForeignKey(Album, on_delete=models.CASCADE, related_name="releases")
    title = models.CharField(max_length=500)
    date = models.CharField(max_length=10, blank=True)  # partial dates allowed
    country = models.CharField(max_length=8, blank=True)
    status = models.CharField(max_length=32, blank=True)
    formats = models.JSONField(default=list, blank=True)
    label = models.CharField(max_length=300, blank=True)
    track_count = models.IntegerField(default=0)

    def __str__(self):
        return self.title


class Track(models.Model):
    release = models.ForeignKey(Release, on_delete=models.CASCADE, related_name="tracks")
    disc = models.IntegerField(default=1)
    position = models.IntegerField()
    number = models.CharField(max_length=16, blank=True)
    side = models.CharField(max_length=8, null=True, blank=True)
    title = models.CharField(max_length=500)
    length_ms = models.IntegerField(null=True, blank=True)
    recording_mbid = models.UUIDField(null=True, blank=True)

    class Meta:
        ordering = ["disc", "position"]

    def __str__(self):
        return self.title


class Place(models.Model):
    mbid = models.UUIDField(unique=True)
    name = models.CharField(max_length=300)
    area = models.CharField(max_length=300, blank=True)

    def __str__(self):
        return self.name


class Credit(models.Model):
    album = models.ForeignKey(Album, on_delete=models.CASCADE, related_name="credits")
    track = models.ForeignKey(Track, null=True, blank=True, on_delete=models.SET_NULL, related_name="credits")
    person = models.ForeignKey(Artist, null=True, blank=True, on_delete=models.SET_NULL, related_name="credits")
    place = models.ForeignKey(Place, null=True, blank=True, on_delete=models.SET_NULL, related_name="credits")
    role = models.CharField(max_length=100)
    attributes = models.JSONField(default=list, blank=True)
    begin_date = models.CharField(max_length=10, blank=True)  # partial date from the MB relation, e.g. "1991-05"
    is_manual = models.BooleanField(default=False)


class Membership(models.Model):
    band = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name="memberships")
    member = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name="member_of")
    begin_year = models.IntegerField(null=True, blank=True)
    end_year = models.IntegerField(null=True, blank=True)
    instruments = models.JSONField(default=list, blank=True)


class Genre(models.Model):
    slug = models.SlugField(max_length=120, unique=True)
    name = models.CharField(max_length=200)
    search_name = models.CharField(max_length=200, blank=True)
    featured = models.BooleanField(default=False)
    description = models.TextField(blank=True)
    description_source_url = models.URLField(max_length=500, blank=True)

    def save(self, *args, **kwargs):
        self.search_name = normalize(self.name)
        _sync_search_name(kwargs, "name")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class AlbumGenre(models.Model):
    album = models.ForeignKey(Album, on_delete=models.CASCADE, related_name="album_genres")
    genre = models.ForeignKey(Genre, on_delete=models.CASCADE, related_name="album_genres")
    source = models.CharField(max_length=32)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["album", "genre", "source"], name="uniq_album_genre_source")
        ]


class ArtistGenre(models.Model):
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name="artist_genres")
    genre = models.ForeignKey(Genre, on_delete=models.CASCADE, related_name="artist_genres")
    source = models.CharField(max_length=32)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["artist", "genre", "source"], name="uniq_artist_genre_source")
        ]


class Story(models.Model):
    class Source(models.TextChoices):
        WIKIPEDIA = "wikipedia"
        LASTFM = "lastfm"
        MANUAL = "manual"

    album = models.ForeignKey(Album, null=True, blank=True, on_delete=models.CASCADE, related_name="stories")
    artist = models.ForeignKey(Artist, null=True, blank=True, on_delete=models.CASCADE, related_name="stories")
    lang = models.CharField(max_length=8)
    source = models.CharField(max_length=16, choices=Source.choices)
    url = models.URLField(max_length=500, blank=True)
    license = models.CharField(max_length=100, blank=True)
    sections = models.JSONField(default=list, blank=True)  # [{"heading": str|None, "paragraphs": [str]}]
    is_manual = models.BooleanField(default=False)
    fetched_at = models.DateTimeField(null=True, blank=True)


class Quote(models.Model):
    class Origin(models.TextChoices):
        WIKIQUOTE = "wikiquote"
        WIKIPEDIA = "wikipedia"
        MANUAL = "manual"

    album = models.ForeignKey(Album, null=True, blank=True, on_delete=models.CASCADE, related_name="quotes")
    artist = models.ForeignKey(Artist, null=True, blank=True, on_delete=models.CASCADE, related_name="quotes")
    text = models.TextField()
    speaker = models.CharField(max_length=300, blank=True)
    source_label = models.CharField(max_length=300, blank=True)
    source_url = models.URLField(max_length=500, blank=True)
    origin = models.CharField(max_length=16, choices=Origin.choices)
    lang = models.CharField(max_length=8, blank=True)
    is_manual = models.BooleanField(default=False)


class Award(models.Model):
    album = models.ForeignKey(Album, null=True, blank=True, on_delete=models.CASCADE, related_name="awards")
    artist = models.ForeignKey(Artist, null=True, blank=True, on_delete=models.CASCADE, related_name="awards")
    wikidata_id = models.CharField(max_length=32, blank=True)
    name_pt = models.CharField(max_length=300, blank=True)
    name_en = models.CharField(max_length=300, blank=True)
    year = models.IntegerField(null=True, blank=True)
    is_manual = models.BooleanField(default=False)


class Influence(models.Model):
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name="influences")
    target_wikidata_id = models.CharField(max_length=32)
    target_label = models.CharField(max_length=300, blank=True)
    target_artist = models.ForeignKey(
        Artist, null=True, blank=True, on_delete=models.SET_NULL, related_name="influenced_by"
    )


class ExternalLink(models.Model):
    class Kind(models.TextChoices):
        LISTEN = "listen"
        BUY = "buy"
        OFFICIAL = "official"
        SOCIAL = "social"

    album = models.ForeignKey(Album, null=True, blank=True, on_delete=models.CASCADE, related_name="links")
    artist = models.ForeignKey(Artist, null=True, blank=True, on_delete=models.CASCADE, related_name="links")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    service = models.CharField(max_length=64, blank=True)
    url = models.URLField(max_length=1000)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["album", "url"], condition=models.Q(artist__isnull=True),
                name="uniq_link_album_url",
            ),
            models.UniqueConstraint(
                fields=["artist", "url"], condition=models.Q(album__isnull=True),
                name="uniq_link_artist_url",
            ),
        ]


class GenreRanking(models.Model):
    genre = models.ForeignKey(Genre, on_delete=models.CASCADE, related_name="rankings")
    rank = models.IntegerField()
    lastfm_artist = models.CharField(max_length=300)
    lastfm_title = models.CharField(max_length=500)
    album = models.ForeignKey(Album, null=True, blank=True, on_delete=models.SET_NULL, related_name="rankings")
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["rank"]
        constraints = [
            models.UniqueConstraint(fields=["genre", "rank"], name="uniq_genre_rank")
        ]
