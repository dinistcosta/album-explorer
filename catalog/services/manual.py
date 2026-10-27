"""Hand-edited rows in multi-row blocks (credits, awards, quotes, links).

An editor's row is ``is_manual``; an imported row the editor deleted stays as an ``is_manual`` +
``is_hidden`` tombstone. Importers never delete manual rows and never create an imported row whose
natural key matches a manual or hidden one, so a refresh brings neither duplicates nor deleted rows back.
"""
from catalog.models import Award, Credit, ExternalLink, Quote
from catalog.services.text import normalize

MANUAL_MODELS = (Credit, Award, Quote, ExternalLink)


def credit_key(role, person_id, place_id, track_id):
    return (role, ("person", person_id) if person_id else ("place", place_id), track_id)


def natural_key(obj):
    if isinstance(obj, Credit):
        return credit_key(obj.role, obj.person_id, obj.place_id, obj.track_id)
    if isinstance(obj, Award):
        return obj.wikidata_id or None
    if isinstance(obj, Quote):
        return normalize(obj.text)
    if isinstance(obj, ExternalLink):
        return obj.url
    raise TypeError(obj)


def manual_keys(queryset) -> set:
    """Natural keys of the manual (including hidden) rows in ``queryset``."""
    return {natural_key(o) for o in queryset.filter(is_manual=True)} - {None}


def hide_or_delete(obj) -> None:
    """Deleting an imported row hides it (so a refresh does not bring it back); a manual row goes."""
    if obj.is_manual:
        obj.delete()
    else:
        obj.is_manual = obj.is_hidden = True
        obj.save()


def rekeyed_original(obj):
    """Call before saving an editor's change to a row. If the change alters an imported row's
    natural key, return an unsaved hidden copy of the original; the caller saves it after the
    change, so the next refresh does not re-add the original alongside the edited row."""
    if obj.pk is None:
        return None
    original = type(obj).objects.filter(pk=obj.pk).first()
    if original is None or original.is_manual or natural_key(original) == natural_key(obj):
        return None
    original.pk = original.id = None
    original.is_manual = original.is_hidden = True
    return original
