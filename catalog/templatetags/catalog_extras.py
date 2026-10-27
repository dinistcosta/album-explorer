from django import template

register = template.Library()


@register.filter
def duration(ms):
    """Milliseconds as m:ss; None as an em dash."""
    if ms is None:
        return "—"
    seconds = round(ms / 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"
