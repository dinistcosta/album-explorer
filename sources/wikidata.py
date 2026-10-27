from . import http

ENDPOINT = "https://www.wikidata.org/w/api.php"
SOURCE = "wikidata"
MAX_IDS = 50
WIKI_KEYS = ("ptwiki", "enwiki", "ptwikiquote", "enwikiquote")


def get_entities(
    ids: list[str], props: str = "claims|sitelinks|labels", languages: str = "pt|en",
    foreground: bool = False,
) -> dict:
    """wbgetentities for `ids` (chunked to 50 per call); returns {id: entity}."""
    unique = list(dict.fromkeys(ids))
    entities: dict = {}
    for start in range(0, len(unique), MAX_IDS):
        data = http.fetch(
            SOURCE, ENDPOINT,
            params={
                "action": "wbgetentities", "format": "json", "ids": "|".join(unique[start:start + MAX_IDS]),
                "props": props, "languages": languages,
            },
            foreground=foreground,
        )
        entities.update(data.get("entities") or {})
    return entities


def get_entity(qid: str, props: str = "claims|sitelinks|labels", foreground: bool = False) -> dict | None:
    """One item, or None when Wikidata says it is missing. A redirected item comes back keyed by its
    target id, so a response holding a single other entity is that target."""
    entities = get_entities([qid], props=props, foreground=foreground)
    entity = entities.get(qid)
    if entity is None and len(entities) == 1:
        entity = next(iter(entities.values()))
    if not entity or "missing" in entity:
        return None
    return entity


def wikidata_id_from_rels(relations: list[dict]) -> str | None:
    for rel in relations or []:
        if rel.get("type") != "wikidata":
            continue
        resource = (rel.get("url") or {}).get("resource") or ""
        qid = resource.rstrip("/").rsplit("/", 1)[-1]
        if qid[:1] == "Q" and qid[1:].isdigit():
            return qid
    return None


def wiki_titles(entity: dict) -> dict[str, str]:
    sitelinks = entity.get("sitelinks") or {}
    return {k: sitelinks[k]["title"] for k in WIKI_KEYS if k in sitelinks and sitelinks[k].get("title")}
