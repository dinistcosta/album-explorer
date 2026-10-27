"""MusicBrainz merges ids: an old URL's import answers with the canonical entity."""
from django.db import transaction

from catalog.models import (
    Album, Artist, Award, Credit, GenreRanking, Influence, Membership, Quote, Story,
)


def _has_manual_data(obj) -> bool:
    if obj.locked_fields:
        return True
    owner = {"album" if isinstance(obj, Album) else "artist": obj}
    if any(m.objects.filter(is_manual=True, **owner).exists() for m in (Story, Quote, Award)):
        return True
    if isinstance(obj, Album):
        return Credit.objects.filter(album=obj, is_manual=True).exists()
    return False


def fold_merged_stub(model, old_mbid: str, canonical) -> None:
    """Delete the never-imported row still filed under the old id, pointing its references
    at the canonical row first. Rows with any manual data are left for an editor to resolve."""
    if str(canonical.mbid) == str(old_mbid):
        return
    stub = model.objects.filter(mbid=old_mbid).first()
    if stub is None or stub.imported_at is not None or _has_manual_data(stub):
        return
    with transaction.atomic():
        if isinstance(stub, Artist):
            Album.objects.filter(artist=stub).update(artist=canonical)
            Credit.objects.filter(person=stub).update(person=canonical)
            Membership.objects.filter(member=stub).exclude(band=canonical).update(member=canonical)
            Influence.objects.filter(target_artist=stub).update(target_artist=canonical)
        else:
            GenreRanking.objects.filter(album=stub).update(album=canonical)
        stub.delete()
