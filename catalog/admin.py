from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _

from sources.http import SourceUnavailable

from .models import Album, Artist, Award, Credit, ExternalLink, Genre, Quote, Story
from .services.album_import import import_album_core
from .services.manual import hide_or_delete, rekeyed_original
from .services.refresh import enqueue_enrichment

# Bookkeeping fields are never locked (and never editable by hand).
UNLOCKABLE = {"locked_fields", "search_name", "imported_at", "enriched_at", "enrichment_queued_at"}
READONLY = ("locked_fields", "search_name", "imported_at", "enriched_at")


class LockingAdmin(admin.ModelAdmin):
    """Fields edited by hand are appended to ``locked_fields`` so a refresh never overwrites them."""

    readonly_fields = READONLY
    actions = ["unlock_all", "refresh_now"]

    def save_model(self, request, obj, form, change):
        model_fields = {f.name for f in obj._meta.concrete_fields}
        locked = list(obj.locked_fields)
        for name in form.changed_data:
            if name in model_fields and name not in UNLOCKABLE and name not in locked:
                locked.append(name)
        obj.locked_fields = locked
        super().save_model(request, obj, form, change)

    @admin.action(description=_("Unlock all fields"))
    def unlock_all(self, request, queryset):
        n = queryset.update(locked_fields=[])
        self.message_user(request, _("Unlocked %(n)d item(s).") % {"n": n})

    def refresh_now(self, request, queryset):  # pragma: no cover - overridden
        raise NotImplementedError


MANUAL_MODELS = (Credit, Story, Quote, Award, ExternalLink)  # inline rows created/changed here become is_manual
HIDEABLE_MODELS = (Credit, Quote, Award, ExternalLink)  # deleting an imported row hides it instead


class ManualFormsetAdmin(admin.ModelAdmin):
    def save_formset(self, request, form, formset, change):
        if not issubclass(formset.model, MANUAL_MODELS):
            return super().save_formset(request, form, formset, change)
        instances = formset.save(commit=False)
        for obj in instances:
            tombstone = rekeyed_original(obj) if isinstance(obj, HIDEABLE_MODELS) else None
            obj.is_manual = True
            obj.save()
            if tombstone:
                tombstone.save()
        for obj in formset.deleted_objects:
            if isinstance(obj, HIDEABLE_MODELS):
                hide_or_delete(obj)
            else:
                obj.delete()
        formset.save_m2m()


class CreditInline(admin.TabularInline):
    model = Credit
    fk_name = "album"
    extra = 0
    # A full import can carry hundreds of credits; the album page only links to them.
    # Editing happens in CreditAdmin (searchable, filterable), which keeps the form small.
    fields = ("role", "person", "track", "is_hidden")
    readonly_fields = ("role", "person", "track", "is_hidden")
    show_change_link = True
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Credit)
class CreditAdmin(admin.ModelAdmin):
    list_display = ("album", "role", "person", "track", "is_manual", "is_hidden")
    list_filter = ("role", "is_manual", "is_hidden")
    search_fields = ("album__title", "person__name", "role")
    raw_id_fields = ("album", "track", "person", "place")
    readonly_fields = ("is_manual",)

    def save_model(self, request, obj, form, change):
        tombstone = rekeyed_original(obj)
        obj.is_manual = True
        super().save_model(request, obj, form, change)
        if tombstone:
            tombstone.save()

    def delete_model(self, request, obj):
        hide_or_delete(obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            hide_or_delete(obj)


class StoryInline(admin.StackedInline):
    model = Story
    fk_name = "album"
    extra = 0
    readonly_fields = ("is_manual",)


class QuoteInline(admin.StackedInline):
    model = Quote
    fk_name = "album"
    extra = 0
    readonly_fields = ("is_manual",)


class AwardInline(admin.TabularInline):
    model = Award
    fk_name = "album"
    extra = 0
    readonly_fields = ("is_manual",)


class LinkInline(admin.TabularInline):
    model = ExternalLink
    fk_name = "album"
    extra = 0
    readonly_fields = ("is_manual",)


def _artist_inline(inline_cls):
    return type(f"Artist{inline_cls.__name__}", (inline_cls,), {"fk_name": "artist"})


@admin.register(Album)
class AlbumAdmin(ManualFormsetAdmin, LockingAdmin):
    list_display = ("title", "artist", "year", "enriched_at")
    search_fields = ("title", "artist__name", "artist_credit")
    raw_id_fields = ("artist", "reference_release")
    inlines = [CreditInline, StoryInline, QuoteInline, AwardInline, LinkInline]

    @admin.action(description=_("Refresh now"))
    def refresh_now(self, request, queryset):
        for album in queryset:
            try:
                import_album_core(str(album.mbid), foreground=False)
            except SourceUnavailable:
                self.message_user(
                    request,
                    _("Could not refresh “%(title)s”: source unavailable.") % {"title": album.title},
                    messages.ERROR,
                )
                continue
            enqueue_enrichment(album)
            self.message_user(request, _("Refresh started for “%(title)s”.") % {"title": album.title})


@admin.register(Artist)
class ArtistAdmin(ManualFormsetAdmin, LockingAdmin):
    list_display = ("name", "country", "begin_year", "enriched_at")
    search_fields = ("name", "sort_name")
    inlines = [
        _artist_inline(StoryInline), _artist_inline(QuoteInline),
        _artist_inline(AwardInline), _artist_inline(LinkInline),
    ]

    @admin.action(description=_("Refresh now"))
    def refresh_now(self, request, queryset):
        for artist in queryset:
            enqueue_enrichment(artist)
        self.message_user(request, _("Refresh started for %(n)d artist(s).") % {"n": queryset.count()})


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "featured")
    list_filter = ("featured",)
    search_fields = ("name", "slug")
    readonly_fields = ("search_name",)
