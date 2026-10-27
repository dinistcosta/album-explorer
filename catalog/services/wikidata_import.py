"""Wikidata enrichers: awards (albums, artists), influences and the image (artists).

All network I/O happens before the short `transaction.atomic()` that writes rows.
"""
from urllib.parse import quote

from django.db import transaction

from catalog.models import Album, Artist, Award, Influence
from catalog.services.manual import manual_keys
from catalog.tasks import register_album_enricher, register_artist_enricher
from sources import musicbrainz as mb
from sources import wikidata

COMMONS = "https://commons.wikimedia.org/wiki/"


def _item_ids(entity: dict, prop: str) -> list[str]:
    out = []
    for claim in (entity.get("claims") or {}).get(prop, []):
        value = (claim.get("mainsnak") or {}).get("datavalue", {}).get("value")
        if isinstance(value, dict) and value.get("id"):
            out.append(value["id"])
    return out


def _awards(entity: dict) -> list[tuple[str, int | None]]:
    out = []
    for claim in (entity.get("claims") or {}).get("P166", []):
        value = (claim.get("mainsnak") or {}).get("datavalue", {}).get("value")
        if not (isinstance(value, dict) and value.get("id")):
            continue
        year = None
        for qualifier in (claim.get("qualifiers") or {}).get("P585", []):
            time = ((qualifier.get("snak") or {}).get("datavalue") or {}).get("value", {}).get("time", "")
            if time[1:5].isdigit():
                year = int(time[1:5])
                break
        if (value["id"], year) not in out:
            out.append((value["id"], year))
    return out


def _label(entity: dict | None, lang: str) -> str:
    return (((entity or {}).get("labels") or {}).get(lang) or {}).get("value", "")


def _replace_awards(owner_field: str, owner, awards, labels: dict) -> None:
    kept = manual_keys(Award.objects.filter(**{owner_field: owner}))  # edited or deleted by hand
    rows = []
    for qid, year in awards:
        if qid in kept:
            continue
        name_en, name_pt = _label(labels.get(qid), "en"), _label(labels.get(qid), "pt")
        if not (name_en or name_pt):  # nothing to show in either language
            continue
        rows.append(Award(
            **{owner_field: owner}, wikidata_id=qid, year=year,
            name_en=name_en or name_pt, name_pt=name_pt or name_en,
        ))
    Award.objects.filter(**{owner_field: owner}, is_manual=False).delete()
    Award.objects.bulk_create(rows)


@register_album_enricher
def import_album_wikidata(album: Album) -> None:
    qid = album.wikidata_id if "wikidata_id" in album.locked_fields else None
    if not qid:
        group = mb.get_release_group(str(album.mbid))
        qid = wikidata.wikidata_id_from_rels(group.get("relations") or []) or album.wikidata_id
    if not qid:
        return
    entity = wikidata.get_entity(qid)
    if entity is None:  # deleted on Wikidata: keep what we have
        return
    awards = _awards(entity)
    labels = wikidata.get_entities([q for q, _ in awards], props="labels") if awards else {}
    with transaction.atomic():
        if album.apply_source_fields(wikidata_id=qid):
            album.save(update_fields=["wikidata_id"])
        _replace_awards("album", album, awards, labels)


@register_artist_enricher
def import_artist_wikidata(artist: Artist) -> None:
    qid = artist.wikidata_id if "wikidata_id" in artist.locked_fields else None
    if not qid:
        data = mb.get_artist(str(artist.mbid))
        qid = wikidata.wikidata_id_from_rels(data.get("relations") or []) or artist.wikidata_id
    if not qid:
        return
    entity = wikidata.get_entity(qid)
    if entity is None:  # deleted on Wikidata: keep what we have
        return
    awards = _awards(entity)
    influence_ids = list(dict.fromkeys(_item_ids(entity, "P737")))
    label_ids = [q for q, _ in awards] + influence_ids
    labels = wikidata.get_entities(label_ids, props="labels") if label_ids else {}

    values = {"wikidata_id": qid}
    files = [
        c["mainsnak"]["datavalue"]["value"]
        for c in (entity.get("claims") or {}).get("P18", [])
        if (c.get("mainsnak") or {}).get("datavalue")
    ]
    if files:
        values["image_url"] = f"{COMMONS}Special:FilePath/{quote(files[0])}?width=600"
        values["image_source_url"] = f"{COMMONS}File:{quote(files[0].replace(' ', '_'))}"

    with transaction.atomic():
        changed = artist.apply_source_fields(**values)
        if changed:
            artist.save(update_fields=changed)
        _replace_awards("artist", artist, awards, labels)
        artist.influences.all().delete()
        targets = {
            a.wikidata_id: a for a in Artist.objects.filter(wikidata_id__in=influence_ids)
        }
        Influence.objects.bulk_create(
            Influence(
                artist=artist, target_wikidata_id=target,
                target_label=_label(labels.get(target), "en") or _label(labels.get(target), "pt"),
                target_artist=targets.get(target),
            )
            for target in influence_ids
        )
