from django import template

register = template.Library()


@register.filter
def duration(ms):
    """Milliseconds as m:ss; None as an em dash."""
    if ms is None:
        return "—"
    seconds = round(ms / 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"


@register.filter
def role_label(role):
    from catalog.services.roles import role_label as label

    return label(role)


@register.filter
def cover_thumb(album):
    """Tile image: the stored cover, else the Cover Art Archive thumbnail (404s fall back client-side)."""
    return album.cover_url or f"https://coverartarchive.org/release-group/{album.mbid}/front-250"


@register.filter
def instrument_labels(instruments):
    """MusicBrainz instrument names, translated where known, as a comma-separated string."""
    from catalog.services.instruments import instrument_label

    return ", ".join(str(instrument_label(i)) for i in instruments or [])
