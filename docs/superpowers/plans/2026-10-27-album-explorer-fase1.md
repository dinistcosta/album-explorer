# Album Explorer — Fase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A bilingual (pt/en) Django site, published as a portfolio demo, where anyone can search a band or album and get a "museum" page for it: album page (layout A, vinyl sleeve, sides A/B, liner-note story, quotes, credits, awards, listen/buy links), band page, and genre rooms by decade — all from open sources, every block showing its source.

**Architecture:** Server-rendered Django + HTMX. A `sources` app wraps every external API behind a cached, rate-limited HTTP layer. A `catalog` app holds the data model, import/enrichment services and views. A first visit fetches the minimum from MusicBrainz synchronously; the rest is enriched by a database-backed task queue and filled in via HTMX polling.

**Tech Stack:** Python 3.14, Django 6.0.x, django-tasks (database backend), httpx, BeautifulSoup4, Pillow, dj-database-url, WhiteNoise, gunicorn, HTMX 2 (vendored), pytest + pytest-django + respx, Babel (to compile `.po` files — this machine has no GNU gettext).

**Spec:** `docs/superpowers/specs/2026-10-27-album-explorer-fase1-design.md` (Portuguese). Mockup: `docs/superpowers/mockups/album-page-layout.html` (variant A).

## Global Constraints

- Environment: no Homebrew, Docker or PostgreSQL on the dev machine. Use `python3 -m venv .venv` + pip. Local dev and tests use SQLite with `"OPTIONS": {"transaction_mode": "IMMEDIATE"}`; production uses PostgreSQL via `DATABASE_URL`.
- Languages: `LANGUAGES = [("pt", "Português"), ("en", "English")]`, `LANGUAGE_CODE = "pt"`, URLs via `i18n_patterns` (`/pt/…`, `/en/…`), `LocaleMiddleware`. Code and source strings in English; Portuguese in `locale/pt/LC_MESSAGES/django.po`, compiled with `pybabel compile -d locale -D django` and the `.mo` committed.
- **No machine translation, no AI-generated text.** Every content block renders its source (and licence when CC BY-SA).
- Sources and minimum intervals between requests (seconds): `musicbrainz 1.0`, `discogs 1.0`, `lastfm 0.25`, `wikipedia 0.1`, `wikidata 0.1`, `wikiquote 0.1`, `coverart 0.1`.
- User-Agent on every request: `AlbumExplorer/0.1 ( {settings.CONTACT_URL} )`; `CONTACT_URL` from env (default `https://github.com/album-explorer`). Never put the user's e-mail in it.
- Secrets from env: `SECRET_KEY`, `DATABASE_URL`, `LASTFM_API_KEY`, `DISCOGS_TOKEN`, `CONTACT_URL`, `DEBUG`, `ALLOWED_HOSTS`. A missing Last.fm or Discogs key skips that source; it never errors.
- Tests never hit the network: respx mocks httpx; recorded responses live in `tests/fixtures/<source>/`.
- Staleness: an entity is refreshed when visited and `enriched_at` is older than 30 days.
- Manual edits survive refresh: fields listed in `locked_fields` are never overwritten; rows with `is_manual=True` are never deleted or replaced.
- Visual tokens (from the mockup): `--bg #141210`, `--bg-2 #1d1a17`, `--ink #ece4d4`, `--muted #9a907f`, `--cream #efe4cb`, `--cream-ink #2b241b`, `--line #2e2a25`; default accent `#c8a45a`. Fonts: Playfair Display (titles), Source Serif 4 (text), IBM Plex Mono (labels). Mobile: single column, 16 px gutters. The disc animation respects `prefers-reduced-motion`.
- Museum tone: no play counts or popularity numbers shown, no infinite scroll, nothing autoplays.
- A source failure never produces a 500; the page renders what is in the database.

## Review Focus

1. **Album without cover art** (Cover Art Archive 404): placeholder sleeve in the default accent, page otherwise complete. → test in Task 6.
2. **Source down or rate-limited** (MusicBrainz 503, timeout) on a first visit: friendly "try again shortly" page with status 503, not a 500; for a cached album, the page renders from the DB. → tests in Tasks 2 and 5.
3. **Unknown or malformed MBID in the URL**: 404 page. → test in Task 5.
4. **Searches with Lucene syntax or accents** (`AC/DC`, `"Sigur Rós"`, `Björk`, `sigur ros`): no MusicBrainz error, accent-insensitive local suggestions. → tests in Task 13.
5. **Artists with more than 100 release groups**: discography is paginated through all pages, not truncated at 100. → test in Task 12.

---

## File Structure

```
requirements.txt / requirements-dev.txt
pytest.ini
manage.py
config/settings.py, urls.py, wsgi.py
sources/
  models.py          HttpCacheEntry, SourceThrottle
  throttle.py        acquire_slot()
  http.py            fetch(), SourceUnavailable, SourceNotFound
  musicbrainz.py  coverart.py  wikidata.py  wikipedia.py  wikiquote.py  lastfm.py  discogs.py
catalog/
  models.py          LockableModel + all catalog models
  admin.py
  tasks.py           enrich_album, enrich_artist, resolve_genre_room
  urls.py  views.py
  services/
    text.py          normalize()
    editions.py      reference edition + vinyl sides
    album_import.py  artist_import.py
    color.py  links.py  genres.py
    wikidata_import.py  stories.py  quotes.py
    refresh.py       staleness + enqueue
    search.py
  management/commands/seed.py
  templates/catalog/…   templates/base.html
  static/css/site.css  static/js/vinyl.js  static/js/htmx.min.js
locale/pt/LC_MESSAGES/django.po (+ .mo)
scripts/record_fixture.py
tests/…  tests/fixtures/…
.github/workflows/ci.yml
README.md
```

---

### Task 1: Project skeleton, i18n and home page

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `manage.py`, `config/settings.py`, `config/urls.py`, `config/wsgi.py`, `catalog/` (app), `catalog/urls.py`, `catalog/views.py`, `templates/base.html`, `catalog/templates/catalog/home.html`, `catalog/static/css/site.css`, `catalog/static/js/htmx.min.js`, `locale/pt/LC_MESSAGES/django.po`
- Test: `tests/test_home.py`

**Interfaces:**
- Produces: URL names `home`; `base.html` blocks `title`, `content`, `accent` (sets `--accent` on `<body style>`); a language switcher (Django `set_language`); CSS tokens from Global Constraints.

- [ ] **Step 1: Create the venv and pin dependencies**

`requirements.txt`: `Django>=6.0,<6.1`, `django-tasks`, `httpx`, `beautifulsoup4`, `Pillow`, `dj-database-url`, `whitenoise`, `gunicorn`, `psycopg[binary]`. `requirements-dev.txt`: `-r requirements.txt`, `pytest`, `pytest-django`, `pytest-freezer`, `respx`, `Babel`.
Run: `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt` → installs without errors.

- [ ] **Step 2: Write the failing tests**

```python
def test_home_portuguese(client):
    r = client.get("/pt/")
    assert r.status_code == 200
    assert "Pesquisa uma banda ou um álbum" in r.content.decode()

def test_home_english(client):
    r = client.get("/en/")
    assert "Search for a band or an album" in r.content.decode()

def test_root_redirects_by_accept_language(client):
    r = client.get("/", HTTP_ACCEPT_LANGUAGE="en-GB,en;q=0.9")
    assert r.status_code == 302 and r.url.startswith("/en/")

def test_home_links_genre_rooms(client, genre_factory):
    genre_factory(slug="shoegaze", name="shoegaze", featured=True)
    assert "/pt/genre/shoegaze/" in client.get("/pt/").content.decode()
```
(`genre_factory` is added to `tests/conftest.py` in Task 14; mark this last test `xfail(strict=True)` until then, and remove the mark in Task 14.)

- [ ] **Step 3: Run** `.venv/bin/pytest tests/test_home.py -v` → FAIL (no project).

- [ ] **Step 4: Implement settings, URLs, base template and home**

Settings read env (Global Constraints); `DATABASES` from `dj_database_url.config(default="sqlite:///db.sqlite3")` plus the SQLite `transaction_mode` option when the engine is SQLite. Home: a large centred search form (`GET` to `search`, `name="q"`) with `hx-get` to `suggest` (wired in Task 13; leave the attributes off until then). Root `/` uses `LocaleMiddleware` redirect. Write the Portuguese strings in `django.po` and compile with `.venv/bin/pybabel compile -d locale -D django`.

- [ ] **Step 5: Run** `.venv/bin/pytest tests/test_home.py -v` → 3 PASS, 1 XFAIL.

- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: project skeleton with pt/en home page"`

---

### Task 2: Cached, rate-limited HTTP layer

**Files:**
- Create: `sources/models.py`, `sources/throttle.py`, `sources/http.py`, `sources/apps.py`
- Test: `tests/sources/test_http.py`, `tests/sources/test_throttle.py`

**Interfaces:**
- Produces:
  - `class SourceUnavailable(Exception)`, `class SourceNotFound(Exception)` in `sources/http.py`
  - `fetch(source: str, url: str, *, params: dict | None = None, headers: dict | None = None, ttl: timedelta = timedelta(days=30), foreground: bool = False, as_json: bool = True) -> dict | str | bytes` — `as_json=False` returns text; pass `binary=True` to get bytes.
  - `MIN_INTERVAL: dict[str, float]` (values from Global Constraints)
  - `acquire_slot(source: str, *, foreground: bool) -> None` in `sources/throttle.py`
  - Models `HttpCacheEntry(key: CharField unique sha256 of source+url+sorted params, status: int, body: BinaryField, fetched_at: DateTime)` and `SourceThrottle(source: unique, next_allowed_at: DateTime, last_foreground_at: DateTime null)`

- [ ] **Step 1: Write the failing tests**

```python
@respx.mock
def test_second_fetch_uses_cache(db):
    route = respx.get("https://musicbrainz.org/ws/2/artist/x").respond(json={"id": "x"})
    fetch("musicbrainz", "https://musicbrainz.org/ws/2/artist/x")
    assert fetch("musicbrainz", "https://musicbrainz.org/ws/2/artist/x") == {"id": "x"}
    assert route.call_count == 1

@respx.mock
def test_expired_cache_refetches(db, freezer): ...  # ttl=1 day, advance 2 days → call_count == 2

@respx.mock
def test_sends_user_agent(db, settings):
    settings.CONTACT_URL = "https://example.org"
    route = respx.get("https://musicbrainz.org/ws/2/x").respond(json={})
    fetch("musicbrainz", "https://musicbrainz.org/ws/2/x")
    assert route.calls[0].request.headers["User-Agent"] == "AlbumExplorer/0.1 ( https://example.org )"

@respx.mock
def test_503_retries_then_raises(db, no_sleep):
    respx.get("https://musicbrainz.org/ws/2/x").respond(503)
    with pytest.raises(SourceUnavailable):
        fetch("musicbrainz", "https://musicbrainz.org/ws/2/x")
    # exactly 3 attempts

@respx.mock
def test_404_raises_not_found_and_is_not_cached(db): ...

def test_timeout_raises_source_unavailable(db): ...  # respx side_effect=httpx.ConnectTimeout

def test_slots_are_spaced_by_min_interval(db, fake_clock):
    acquire_slot("musicbrainz", foreground=True)
    acquire_slot("musicbrainz", foreground=True)
    assert fake_clock.slept == pytest.approx(1.0)

def test_background_yields_to_recent_foreground(db, fake_clock):
    acquire_slot("musicbrainz", foreground=True)
    acquire_slot("musicbrainz", foreground=False)
    assert fake_clock.slept >= 2.0
```
`fake_clock` / `no_sleep` fixtures in `tests/conftest.py` monkeypatch `sources.throttle.now` and `sources.throttle.sleep` (and `sources.http.sleep`). `freezer` comes from `pytest-freezer`.

- [ ] **Step 2: Run** `.venv/bin/pytest tests/sources -v` → FAIL.

- [ ] **Step 3: Implement**

`acquire_slot`: inside `transaction.atomic()`, `select_for_update()` the `SourceThrottle` row (get_or_create), compute `start = max(now, next_allowed_at)`; for background calls also `start = max(start, last_foreground_at + 2s)`; write `next_allowed_at = start + MIN_INTERVAL[source]` (and `last_foreground_at = now` if foreground), commit, then sleep until `start`. `fetch`: cache lookup → `acquire_slot` → httpx GET (timeout 10 s) → on 503/429/timeout retry up to 3 attempts with 1 s, 2 s backoff → 404 raises `SourceNotFound` → 2xx stored in cache.

- [ ] **Step 4: Run** `.venv/bin/pytest tests/sources -v` → PASS.

- [ ] **Step 5: Commit** `git commit -am "feat: cached rate-limited fetch for external sources"` (add new files first).

---

### Task 3: Catalog models and MusicBrainz client

**Files:**
- Create: `catalog/models.py`, `catalog/services/text.py`, `sources/musicbrainz.py`, `scripts/record_fixture.py`
- Test: `tests/catalog/test_models.py`, `tests/sources/test_musicbrainz.py`, fixtures `tests/fixtures/musicbrainz/*.json`

**Interfaces:**
- Produces (`catalog/models.py`):
  - `LockableModel` (abstract): `locked_fields = JSONField(default=list)`; `apply_source_fields(self, **values) -> list[str]` sets every non-locked field, returns changed field names.
  - `Artist(LockableModel)`: `mbid UUID unique`, `name`, `sort_name`, `search_name` (indexed), `country`, `begin_year int null`, `end_year int null`, `artist_type`, `wikidata_id`, `discogs_id`, `image_url`, `image_source_url`, `imported_at null`, `enriched_at null`.
  - `Album(LockableModel)`: `mbid UUID unique`, `title`, `search_name`, `artist FK Artist null`, `artist_credit`, `year int null`, `primary_type`, `secondary_types JSON`, `reference_release FK Release null`, `cover_url`, `accent_color` (default `""`), `wikidata_id`, `discogs_master_id`, `lastfm_listeners int null` (sorting only, never displayed), `imported_at null`, `enriched_at null`.
  - `Release`: `mbid unique`, `album FK`, `title`, `date` (str, partial allowed), `country`, `status`, `formats JSON list[str]`, `label`, `track_count int`.
  - `Track`: `release FK`, `disc int`, `position int`, `number str`, `side str null`, `title`, `length_ms int null`, `recording_mbid`.
  - `Place`: `mbid unique`, `name`, `area`.
  - `Credit`: `album FK`, `track FK null`, `person FK Artist null`, `place FK Place null`, `role`, `attributes JSON`, `is_manual bool`.
  - `Membership`: `band FK Artist`, `member FK Artist`, `begin_year null`, `end_year null`, `instruments JSON`.
  - `Genre`: `slug unique`, `name`, `search_name`, `featured bool`, `description`, `description_source_url`; through models `AlbumGenre(album, genre, source)` and `ArtistGenre(artist, genre, source)`, unique per triple.
  - `Story`: `album FK null`, `artist FK null`, `lang`, `source` (`wikipedia|lastfm|manual`), `url`, `license`, `sections JSON list[{"heading": str|None, "paragraphs": list[str]}]`, `is_manual`, `fetched_at`.
  - `Quote`: `album FK null`, `artist FK null`, `text`, `speaker`, `source_label`, `source_url`, `origin` (`wikiquote|wikipedia|manual`), `lang`, `is_manual`.
  - `Award`: `album FK null`, `artist FK null`, `wikidata_id`, `name_pt`, `name_en`, `year null`, `is_manual`.
  - `Influence`: `artist FK`, `target_wikidata_id`, `target_label`, `target_artist FK Artist null`.
  - `ExternalLink`: `album FK null`, `artist FK null`, `kind` (`listen|buy|official|social`), `service`, `url`; unique `(album, artist, url)`.
  - `GenreRanking`: `genre FK`, `rank`, `lastfm_artist`, `lastfm_title`, `album FK null`, `resolved_at null`; unique `(genre, rank)`.
- Produces `normalize(text: str) -> str` (casefold, strip accents via `unicodedata` NFKD, non-alphanumerics → space, collapse spaces). `search_name` is set from `normalize` in `save()`.
- Produces (`sources/musicbrainz.py`, all with `foreground: bool = False`, base `https://musicbrainz.org/ws/2/`, `fmt=json`):
  - `get_release_group(mbid) -> dict` — `inc=artist-credits+url-rels+genres`
  - `browse_releases(release_group_mbid) -> list[dict]` — `release?release-group=…&inc=media&limit=100`, every page
  - `get_release(mbid) -> dict` — `inc=recordings+artist-credits+labels+artist-rels+place-rels+recording-level-rels+url-rels`
  - `get_artist(mbid) -> dict` — `inc=url-rels+artist-rels+genres`
  - `browse_release_groups(artist_mbid) -> list[dict]` — `type=album|ep`, every page of 100
  - `search_artists(query, limit=8)`, `search_release_groups(query, limit=24) -> list[dict]`
  - `escape_lucene(text) -> str`, `list_genres() -> list[str]` (`genre/all?fmt=txt`)

- [ ] **Step 1: Record fixtures**

`scripts/record_fixture.py <source> <url> <out_path>` performs one real GET (with the User-Agent) and writes the body. Record: release group, release browse, reference release and the vinyl release for *Nevermind* (Nirvana), plus artist lookup and release-group browse for Nirvana; save under `tests/fixtures/musicbrainz/`. Look the MBIDs up with the MusicBrainz web search. Fixture names: `nevermind_rg.json`, `nevermind_releases.json`, `nevermind_reference.json`, `nevermind_vinyl.json`, `nirvana_artist.json`, `nirvana_rgs_page1.json`.

- [ ] **Step 2: Write the failing tests**

```python
def test_apply_source_fields_skips_locked(db, album_factory):
    a = album_factory(title="Old", locked_fields=["title"])
    changed = a.apply_source_fields(title="New", year=1991)
    assert a.title == "Old" and a.year == 1991 and changed == ["year"]

def test_normalize():
    assert normalize("Sigur Rós") == "sigur ros"
    assert normalize("AC/DC") == "ac dc"

@respx.mock
def test_browse_release_groups_follows_pagination(db):
    # mock offset=0 → 100 items, count=150; offset=100 → 50 items
    assert len(browse_release_groups(ARTIST)) == 150

def test_escape_lucene():
    assert escape_lucene('AC/DC "live"') == 'AC\\/DC \\"live\\"'
```
`album_factory`, `artist_factory` in `tests/conftest.py` (plain functions creating rows with defaults).

- [ ] **Step 3: Run** `.venv/bin/pytest tests/catalog/test_models.py tests/sources/test_musicbrainz.py -v` → FAIL.

- [ ] **Step 4: Implement models (+ `makemigrations`) and the client.**

- [ ] **Step 5: Run the tests** → PASS. Also `.venv/bin/python manage.py makemigrations --check` → "No changes detected".

- [ ] **Step 6: Commit** `git commit -m "feat: catalog models and MusicBrainz client"`

---

### Task 4: Reference edition, vinyl sides and album import

**Files:**
- Create: `catalog/services/editions.py`, `catalog/services/album_import.py`
- Test: `tests/catalog/test_editions.py`, `tests/catalog/test_album_import.py`

**Interfaces:**
- Consumes: `musicbrainz.get_release_group`, `browse_releases`, `get_release` (Task 3).
- Produces:
  - `choose_reference_release(releases: list[dict]) -> dict` — official releases only (else all), earliest `date` (partial dates sort by their prefix; missing dates last), ties by `id`.
  - `vinyl_candidates(releases: list[dict]) -> list[dict]` — releases where every medium format contains "Vinyl", earliest first.
  - `assign_sides(reference: dict, vinyl: dict) -> dict[str, str] | None` — returns `{recording_mbid: side_letter}` when the vinyl's tracks have the same recording sequence as the reference and positions like `A1`/`B3`; otherwise `None`. Side letter = leading letters of the track `number`.
  - `import_album_core(mbid: str, *, foreground: bool) -> Album` — upserts Artist (stub), Album, every Release (from browse), the reference release's Tracks, and Credits from the reference release's relations (`producer`, `mix`, `engineer`, `recording engineer`, `instrument`, `vocal` as roles; place relation `recorded at` → `Place` + Credit role `recorded at`). Sets `imported_at`. Raises `SourceNotFound` for an unknown MBID. Writes through `apply_source_fields`; never deletes rows with `is_manual=True`.
  - `apply_vinyl_sides(album: Album) -> None` — fetches the first vinyl candidate's full release and sets `Track.side`, or leaves them `None`.

- [ ] **Step 1: Write the failing tests** (synthetic dicts for the rules, fixtures for import)

```python
def test_reference_is_earliest_official():
    rels = [rel("b", "1992-01", "Official"), rel("a", "1991-09-24", "Official"), rel("c", "1990", "Bootleg")]
    assert choose_reference_release(rels)["id"] == "a"

def test_partial_date_sorts_before_later_full_date():
    assert choose_reference_release([rel("x", "1991-10-01"), rel("y", "1991")])["id"] == "y"

def test_missing_date_sorts_last(): ...

def test_sides_from_matching_vinyl():
    ref = release_with(["r1", "r2", "r3"], numbers=["1", "2", "3"])
    vin = release_with(["r1", "r2", "r3"], numbers=["A1", "A2", "B1"])
    assert assign_sides(ref, vin) == {"r1": "A", "r2": "A", "r3": "B"}

def test_no_sides_when_tracklists_differ():
    assert assign_sides(release_with(["r1", "r2"]), release_with(["r1", "r9"], numbers=["A1", "B1"])) is None

def test_no_sides_when_vinyl_numbers_are_plain():
    assert assign_sides(release_with(["r1"]), release_with(["r1"], numbers=["1"])) is None

@respx.mock
def test_import_nevermind(db, mb_fixtures):
    album = import_album_core(NEVERMIND_RG, foreground=True)
    assert album.title == "Nevermind" and album.artist.name == "Nirvana" and album.year == 1991
    assert album.reference_release.track_set.count() >= 12
    assert Credit.objects.filter(album=album, role="producer", person__name="Butch Vig").exists()

@respx.mock
def test_import_keeps_manual_credit(db, mb_fixtures): ...  # pre-existing is_manual Credit survives re-import

@respx.mock
def test_import_unknown_mbid_raises_not_found(db): ...
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `.venv/bin/pytest tests/catalog -v` → PASS.

- [ ] **Step 5: Commit** `git commit -m "feat: album import with reference edition and vinyl sides"`

---

### Task 5: Album page (synchronous core) and the vinyl sleeve

**Files:**
- Create: `catalog/templates/catalog/album_detail.html`, `catalog/templates/catalog/_album_sections.html`, `catalog/templates/catalog/503.html`, `templates/404.html`, `catalog/static/js/vinyl.js`
- Modify: `catalog/views.py`, `catalog/urls.py`, `catalog/static/css/site.css`
- Test: `tests/catalog/test_album_view.py`

**Interfaces:**
- Consumes: `import_album_core` (Task 4).
- Produces: URL names `album_detail` (`album/<uuid:mbid>/`) and `album_enrichment` (`album/<uuid:mbid>/sections/`). `album_detail` renders the layout-A hero and tracklist; `_album_sections.html` renders quotes, liner-note story, credits, awards, other editions and genres from the DB, each guarded so an empty section is omitted. While `album.enriched_at is None`, the sections container has `hx-get="{% url 'album_enrichment' … %}" hx-trigger="load delay:2s" hx-swap="outerHTML"` and shows a discreet "a carregar…"; the enrichment view returns the same container, polling again until enriched (max 15 polls via a `?n=` counter, then it stops polling and shows what is there).
- Produces: template context key `album`, `tracks_by_side: list[tuple[str | None, list[Track]]]` (`[("A", […]), ("B", […])]`, or `[(None, all)]` → heading "Alinhamento" / "Tracklist").

- [ ] **Step 1: Write the failing tests**

```python
def test_album_page_imports_on_first_visit(client, db, mb_fixtures_respx):
    r = client.get(f"/pt/album/{NEVERMIND_RG}/")
    assert r.status_code == 200
    html = r.content.decode()
    assert "Nevermind" in html and "Smells Like Teen Spirit" in html

def test_sides_shown_when_known(client, album_with_sides):
    html = client.get(album_with_sides.url_pt).content.decode()
    assert "Lado A" in html and "Lado B" in html

def test_single_list_without_sides(client, album_without_sides):
    html = client.get(album_without_sides.url_pt).content.decode()
    assert "Alinhamento" in html and "Lado A" not in html

def test_unknown_mbid_is_404(client, db, mb_404):
    assert client.get("/pt/album/00000000-0000-0000-0000-000000000000/").status_code == 404

def test_malformed_mbid_is_404(client, db):
    assert client.get("/pt/album/not-a-uuid/").status_code == 404

def test_source_down_on_first_visit_is_503(client, db, mb_503):
    r = client.get(f"/pt/album/{NEVERMIND_RG}/")
    assert r.status_code == 503 and "Tenta outra vez" in r.content.decode()

def test_cached_album_renders_when_source_down(client, imported_album, mb_503):
    assert client.get(imported_album.url_pt).status_code == 200

def test_polling_stops_once_enriched(client, imported_album):
    imported_album.enriched_at = timezone.now(); imported_album.save()
    assert "hx-get" not in client.get(f"/pt/album/{imported_album.mbid}/sections/").content.decode()
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** the view (DB first; import with `foreground=True` if missing; `SourceNotFound` → 404; `SourceUnavailable` → `503.html` with status 503), the template following mockup variant A, and `vinyl.js`: on load add a class that slides the disc out (CSS transition as in the mockup); with `prefers-reduced-motion: reduce` the disc is shown already out and nothing moves. Durations render as `m:ss`; `None` renders as `—`.

- [ ] **Step 4: Run** `.venv/bin/pytest tests/catalog/test_album_view.py -v` → PASS.

- [ ] **Step 5: Commit** `git commit -m "feat: album page with vinyl sleeve and sides"`

---

### Task 6: Cover art and accent colour

**Files:**
- Create: `sources/coverart.py`, `catalog/services/color.py`
- Test: `tests/catalog/test_color.py`, `tests/sources/test_coverart.py`

**Interfaces:**
- Produces:
  - `cover_url(release_group_mbid: str) -> str` → `https://coverartarchive.org/release-group/{mbid}/front-500`
  - `fetch_cover(release_group_mbid: str) -> bytes | None` (None on 404)
  - `DEFAULT_ACCENT = "#c8a45a"`, `BACKGROUND = "#141210"`
  - `contrast_ratio(a: str, b: str) -> float` (WCAG relative luminance)
  - `ensure_contrast(color: str, background: str = BACKGROUND, minimum: float = 3.0) -> str` — raise HLS lightness in 0.05 steps until the ratio is met.
  - `extract_accent(image: bytes) -> str` — downscale to 64×64, `quantize(8)`, discard colours with HLS saturation < 0.25 or lightness < 0.12 or > 0.92, pick the max of `saturation * sqrt(pixel_count)`; none left → `DEFAULT_ACCENT`; result passed through `ensure_contrast`.
  - Enricher `apply_cover_and_accent(album: Album) -> None` (sets `cover_url` only when a cover exists, `accent_color` unless locked). Registered in Task 7.

- [ ] **Step 1: Write the failing tests**

```python
def test_contrast_ratio_black_white():
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, rel=1e-3)

def test_dark_colour_is_lightened():
    out = ensure_contrast("#1d1a40")
    assert contrast_ratio(out, "#141210") >= 3.0

def test_extract_accent_picks_saturated_blue():
    img = solid_png("#2f7cc0", 60) + grey_patch  # helper builds a PNG: mostly blue, some grey
    assert extract_accent(img) == ensure_contrast("#2f7cc0")  # within quantize tolerance: compare hue ±10°

def test_greyscale_cover_uses_default():
    assert extract_accent(solid_png("#808080")) == DEFAULT_ACCENT

@respx.mock
def test_missing_cover_keeps_placeholder(db, imported_album, client):
    respx.get(cover_url(str(imported_album.mbid))).respond(404)
    apply_cover_and_accent(imported_album)
    imported_album.refresh_from_db()
    assert imported_album.cover_url == "" and imported_album.accent_color == ""
    assert 'class="sleeve placeholder"' in client.get(imported_album.url_pt).content.decode()
```
Templates use `album.accent_color|default:"#c8a45a"`.

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.

- [ ] **Step 5: Commit** `git commit -m "feat: cover art and accent colour"`

---

### Task 7: Task queue, enrichment pipeline and refresh

**Files:**
- Create: `catalog/tasks.py`, `catalog/services/refresh.py`
- Modify: `config/settings.py` (`TASKS`), `catalog/views.py` (enqueue)
- Test: `tests/catalog/test_enrichment.py`

**Interfaces:**
- Consumes: `apply_vinyl_sides` (Task 4), `apply_cover_and_accent` (Task 6).
- Produces:
  - `ALBUM_ENRICHERS: list[Callable[[Album], None]]` and `ARTIST_ENRICHERS: list[Callable[[Artist], None]]` in `catalog/tasks.py`; later tasks append to them in their own module and import it from `catalog/apps.py` `ready()`.
  - Tasks (Django 6 `django.tasks.task` decorator, database backend from the `django-tasks` package — check the backend import path and worker command (`db_worker`) against the installed version; if the backend is incompatible with Django 6.0, switch to `django-q2` with the ORM broker and keep the same function names): `enrich_album(album_id: int)`, `enrich_artist(artist_id: int)`, `resolve_genre_room(genre_id: int)` (body in Task 14). Each enricher runs in its own `try`; a `SourceUnavailable` or unexpected exception is logged and the next enricher runs. `enriched_at` is set at the end.
  - `STALE_AFTER = timedelta(days=30)`; `needs_enrichment(obj) -> bool` (`enriched_at` is None or older than `STALE_AFTER`); `enqueue_enrichment(obj) -> None` (dedupes: skips if a queued/running task already exists for that object).
  - In tests, `TASKS` uses the immediate backend.

- [ ] **Step 1: Write the failing tests**

```python
def test_failing_enricher_does_not_stop_others(db, imported_album, monkeypatch):
    calls = []
    monkeypatch.setattr(tasks, "ALBUM_ENRICHERS", [boom, lambda a: calls.append(a.pk)])
    tasks.enrich_album.call(imported_album.pk)
    imported_album.refresh_from_db()
    assert calls == [imported_album.pk] and imported_album.enriched_at is not None

def test_visit_enqueues_when_stale(client, imported_album, freezer, enqueued):
    imported_album.enriched_at = timezone.now() - timedelta(days=31); imported_album.save()
    client.get(imported_album.url_pt)
    assert enqueued == [("enrich_album", imported_album.pk)]

def test_visit_does_not_enqueue_when_fresh(...): ...
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS. Also run the worker once by hand: `.venv/bin/python manage.py db_worker --batch` (or the installed equivalent) → exits cleanly with no tasks.

- [ ] **Step 5: Commit** `git commit -m "feat: background enrichment pipeline with staleness refresh"`

---

### Task 8: Wikidata — sitelinks, awards, influences, artist image

**Files:**
- Create: `sources/wikidata.py`, `catalog/services/wikidata_import.py`
- Test: `tests/catalog/test_wikidata_import.py`, fixtures `tests/fixtures/wikidata/nevermind.json`, `awards_labels.json`, `nirvana.json`

**Interfaces:**
- Produces:
  - `get_entities(ids: list[str], props: str = "claims|sitelinks|labels", languages: str = "pt|en") -> dict` (`wbgetentities`, ≤50 ids per call)
  - `wikidata_id_from_rels(relations: list[dict]) -> str | None` (MusicBrainz url-rel of type `wikidata`)
  - `wiki_titles(entity: dict) -> dict[str, str]` — keys `ptwiki`, `enwiki`, `ptwikiquote`, `enwikiquote` when present
  - Enrichers `import_album_wikidata(album)` and `import_artist_wikidata(artist)`: set `wikidata_id`; replace non-manual `Award`s from P166 (labels pt/en, year from qualifier P585); for artists, replace `Influence`s from P737 (link `target_artist` when an `Artist` with that `wikidata_id` exists) and set `image_url` from P18 as `https://commons.wikimedia.org/wiki/Special:FilePath/{file}?width=600` with `image_source_url` the Commons file page.
  - Stored for later tasks: the sitelinks dict is returned by `wiki_titles` on demand from the cached entity — no new model fields.

- [ ] **Step 1: Write the failing tests**

```python
def test_awards_imported_with_both_labels(db, imported_album, wikidata_fixtures): ...
    # asserts an Award with name_en and name_pt set and year from P585
def test_manual_award_survives(db, ...): ...
def test_album_without_wikidata_link_is_skipped(db, ...): ...  # no requests made
def test_influence_links_existing_artist(db, ...): ...
def test_wiki_titles():
    assert wiki_titles({"sitelinks": {"enwiki": {"title": "Nevermind"}}}) == {"enwiki": "Nevermind"}
```

- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.

- [ ] **Step 5: Commit** `git commit -m "feat: awards, influences and images from Wikidata"`

---

### Task 9: Wikipedia stories

**Files:**
- Create: `sources/wikipedia.py`, `catalog/services/stories.py`
- Test: `tests/catalog/test_wikipedia_story.py`, fixtures `tests/fixtures/wikipedia/nevermind_en.json`, `<a pt album>_pt.json`

**Interfaces:**
- Consumes: `wiki_titles` (Task 8).
- Produces:
  - `get_article_html(lang: str, title: str) -> str` (`https://{lang}.wikipedia.org/w/api.php?action=parse&page=…&prop=text&formatversion=2&redirects=1`)
  - `KEEP_HEADINGS = {"en": ["background", "recording", "production", "composition", "release", "reception", "critical reception"], "pt": ["antecedentes", "contexto", "gravação", "produção", "composição", "lançamento", "recepção", "receção", "recepção crítica", "receção crítica"]}` — matched with `normalize()` on the heading text, prefix match.
  - `parse_wikipedia_html(html: str, lang: str) -> list[dict]` — intro paragraphs (heading `None`) + kept sections; reference markers (`sup.reference`), tables, infoboxes, figures, "edit" links removed; empty paragraphs dropped.
  - Enricher `import_wikipedia_stories(entity: Album | Artist)` — for each of `pt`, `en` with a sitelink, upsert the non-manual `Story(source="wikipedia", lang, url, license="CC BY-SA 4.0")`.

- [ ] **Step 1: Write the failing tests**

```python
def test_intro_and_recording_kept_tables_dropped(wiki_en_html):
    sections = parse_wikipedia_html(wiki_en_html, "en")
    assert sections[0]["heading"] is None and sections[0]["paragraphs"]
    assert any(s["heading"].lower().startswith("recording") for s in sections[1:])
    assert all("[1]" not in p for s in sections for p in s["paragraphs"])

def test_portuguese_headings_with_accents(wiki_pt_html):
    assert any(normalize(s["heading"] or "").startswith("gravacao") for s in parse_wikipedia_html(wiki_pt_html, "pt"))

def test_story_saved_per_language(db, imported_album, respx_wiki): ...
```

- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.

- [ ] **Step 5: Commit** `git commit -m "feat: liner-note stories from Wikipedia"`

---

### Task 10: Last.fm and Discogs, fact sheet and the story chain

**Files:**
- Create: `sources/lastfm.py`, `sources/discogs.py`
- Modify: `catalog/services/stories.py`, `catalog/templates/catalog/_album_sections.html`, `locale/pt/LC_MESSAGES/django.po`
- Test: `tests/catalog/test_story_chain.py`, `tests/catalog/test_fact_sheet.py`, fixtures under `tests/fixtures/lastfm/`, `tests/fixtures/discogs/`

**Interfaces:**
- Produces (`sources/lastfm.py`, base `https://ws.audioscrobbler.com/2.0/`, `format=json`; every function returns `None` when `LASTFM_API_KEY` is unset):
  - `album_info(artist: str, title: str, mbid: str | None, lang: str) -> dict | None`, `artist_info(name, mbid, lang)`, `album_top_tags(artist, title) -> list[str]`, `tag_top_albums(tag: str, limit: int = 100) -> list[dict]`, `tag_info(tag, lang) -> dict | None`
  - `clean_lastfm_wiki(text: str) -> str` — strips the trailing `<a href=…>Read more on Last.fm</a>` and the "User-contributed text…" licence line.
- Produces (`sources/discogs.py`, header `Authorization: Discogs token=…`; `None` when `DISCOGS_TOKEN` unset): `get_master(id) -> dict | None`, `get_release(id) -> dict | None`.
- Produces (`catalog/services/stories.py`):
  - Enrichers `import_lastfm_stories(entity)` (for `pt` and `en`, upsert `Story(source="lastfm", license="CC BY-SA 3.0")` when the wiki is non-empty and not identical to the English one), `import_discogs_notes(album)` (Discogs master id from the MB url-rel; stores `discogs_master_id`, the master's `styles` in `Album.discogs_styles` (JSON list) and the main release `notes` in `Album.discogs_notes` (TextField) — add both fields in this task's migration; Task 11 turns the styles into genres).
  - `build_fact_sheet(album: Album, lang: str) -> list[str]` — one paragraph built from optional sentences, in this order, skipping any whose data is missing:
    - pt: `"Gravado em {ano} em {estúdio}, {local}."` (year from a `recorded at` credit's date when known, else omitted: `"Gravado em {estúdio}, {local}."`), `"Produzido por {nomes}."`, `"Editado em {ano} pela editora {editora}, em {formatos}."`
    - en: `"Recorded in {year} at {studio}, {area}."`, `"Produced by {names}."`, `"Released in {year} by {label} on {formats}."`
    - Name lists: `"A, B e C"` / `"A, B and C"`. Formats are the distinct release formats mapped to `vinil`, `CD`, `cassete`, `digital` / `vinyl`, `CD`, `cassette`, `digital`, in that order.
    - `discogs_notes`, when present, is a second paragraph shown under the label "Notas da edição (Discogs)".
  - `StoryView` dataclass: `sections: list[dict]`, `source: str`, `url: str`, `license: str`, `lang: str`, `is_other_language: bool`, `is_generated: bool`.
  - `select_story(entity, lang: str) -> StoryView` — order: manual story in `lang` → Wikipedia `lang` → Wikipedia `en` (`is_other_language=True`) → Last.fm `lang` → Last.fm `en` (`is_other_language=True`) → generated fact sheet (albums) / `"{name} é uma banda de {país}, formada em {ano}."`-style sheet from artist fields (artists). Generated sheets set `is_generated=True` and the template shows the "Conheces a história deste disco?" placeholder (no link, no form).

- [ ] **Step 1: Write the failing tests**

```python
def test_fact_sheet_pt_full(album_with_full_facts):
    assert build_fact_sheet(album_with_full_facts, "pt") == [
        "Gravado em 1994 em Estúdios Valentim de Carvalho, Paço de Arcos. "
        "Produzido por Ana Silva e Rui Costa. "
        "Editado em 1995 pela editora EMI, em vinil e CD."
    ]

def test_fact_sheet_en_without_studio(album_without_studio):
    assert build_fact_sheet(album_without_studio, "en") == ["Produced by Ana Silva. Released in 1995 by EMI on CD."]

def test_chain_prefers_reader_language(db, album, stories("wikipedia/pt", "wikipedia/en")):
    assert select_story(album, "pt").lang == "pt"

def test_chain_falls_back_to_english_with_flag(db, album, stories("wikipedia/en")):
    v = select_story(album, "pt"); assert v.lang == "en" and v.is_other_language

def test_chain_lastfm_before_generated(db, album, stories("lastfm/en")): ...
def test_chain_generated_when_nothing(db, album): assert select_story(album, "pt").is_generated
def test_manual_story_wins(db, album, stories("manual/pt", "wikipedia/pt")): ...
def test_clean_lastfm_wiki_strips_read_more(): ...
def test_lastfm_skipped_without_key(db, settings, album): ...  # settings.LASTFM_API_KEY = "" → no request

def test_other_language_notice_rendered(client, album_with_en_only_story):
    assert "Disponível apenas em inglês" in client.get(album_with_en_only_story.url_pt).content.decode()
```

- [ ] **Step 2–4:** run → FAIL, implement (including the liner-note template: cream panel, source + licence footer, notice for other-language text), run → PASS.

- [ ] **Step 5: Commit** `git commit -m "feat: story fallback chain with Last.fm, Discogs notes and fact sheet"`

---

### Task 11: Quotes, listen/buy links and album genres

**Files:**
- Create: `sources/wikiquote.py`, `catalog/services/quotes.py`, `catalog/services/links.py`, `catalog/services/genres.py`
- Modify: `catalog/templates/catalog/album_detail.html`, `_album_sections.html`
- Test: `tests/catalog/test_quotes.py`, `tests/catalog/test_links.py`, `tests/catalog/test_genres.py`, fixtures `tests/fixtures/wikiquote/nirvana_en.json`

**Interfaces:**
- Consumes: `get_article_html` (Task 9), `wiki_titles` (Task 8), `album_top_tags` (Task 10).
- Produces:
  - `get_wikiquote_html(lang, title) -> str` (same API shape as Wikipedia on `{lang}.wikiquote.org`).
  - `QuoteData` dataclass: `text, speaker, source_label, source_url, origin`.
  - `extract_wikiquote_quotes(html: str, album_title: str, track_titles: list[str], speaker: str) -> list[QuoteData]` — top-level `<li>` quotes whose own text or nested source line mentions the album title or a track title (matched with `normalize`, whole-word); `source_label` from the nested `<li>`.
  - `extract_wikipedia_quotes(html: str, people: list[str]) -> list[QuoteData]` — sentences containing a quoted passage of ≥ 6 words (`"…"`, `“…”`, `«…»`) **and** a full name or surname from `people` in the same sentence **and** a reference marker; `source_label`/`source_url` resolved from the reference list entry the marker points to. Exactly one matching person, or the sentence is dropped.
  - Enricher `import_quotes(album)` — replaces non-manual quotes; keeps at most 2 per album (prefer Wikiquote, then Wikipedia). `people` = members (if imported), album artist name, producers from credits.
  - `classify_url(url: str) -> tuple[str, str] | None` → `("listen", "spotify"|"apple_music"|"youtube"|"bandcamp")`, `("buy", "bandcamp")` is added alongside listen for Bandcamp, `("official", "website")`, `("social", "instagram"|"facebook"|"x"|"tiktok"|"soundcloud")`. YouTube Music counts as `youtube`.
  - Enricher `import_album_links(album)` — from the release group and every release's url-rels (releases fetched lazily only if the release group has none); plus a computed buy link `https://www.discogs.com/search/?q={artist}+{title}&type=all` rendered as "Procurar no Discogs" (not stored).
  - `match_genre(name: str) -> Genre | None` (by `normalize(name)` == `Genre.search_name`; also tries replacing `&` with `and` and removing hyphens) and `attach_genres(entity, names: list[str], source: str) -> None`. Enricher `import_album_genres(album)` uses MB genres (from the release-group lookup), Last.fm top tags and `album.discogs_styles` (Task 10), each with its own `source`.
  - Template: "Nas palavras da banda" block between tracklist and liner notes; a pull-quote inside the liner notes when a Wikipedia-origin quote exists; listen buttons only for services with links; genre chips link to `genre_detail`.

- [ ] **Step 1: Write the failing tests**

```python
def test_wikiquote_keeps_only_album_mentions(wikiquote_html):
    qs = extract_wikiquote_quotes(wikiquote_html, "Nevermind", ["Lithium"], "Kurt Cobain")
    assert qs and all("nevermind" in normalize(q.text + q.source_label) or "lithium" in normalize(q.text + q.source_label) for q in qs)

def test_wikipedia_quote_requires_person_and_reference():
    html = '<p>Vig said "we wanted it to sound like a huge record from the start" in 1992.<sup class="reference"><a href="#cite_note-1">[1]</a></sup></p><ol class="references"><li id="cite_note-1"><cite><a href="https://example.org/i">Interview, Spin</a></cite></li></ol>'
    [q] = extract_wikipedia_quotes(html, ["Butch Vig"])
    assert q.speaker == "Butch Vig" and q.source_url == "https://example.org/i"

def test_wikipedia_quote_dropped_without_reference(): ...
def test_wikipedia_quote_dropped_when_two_people_named(): ...

@pytest.mark.parametrize("url,expected", [
    ("https://open.spotify.com/album/x", ("listen", "spotify")),
    ("https://music.apple.com/pt/album/x", ("listen", "apple_music")),
    ("https://music.youtube.com/playlist?list=x", ("listen", "youtube")),
    ("https://band.bandcamp.com/album/x", ("listen", "bandcamp")),
    ("https://www.instagram.com/band", ("social", "instagram")),
])
def test_classify_url(url, expected): assert classify_url(url) == expected

def test_match_genre_normalises(db): Genre.objects.create(slug="hip-hop", name="hip hop"); assert match_genre("Hip-Hop")
def test_unknown_tag_ignored(db): assert match_genre("seen live") is None

def test_listen_button_hidden_without_link(client, album_with_only_spotify):
    html = client.get(album_with_only_spotify.url_pt).content.decode()
    assert "Spotify" in html and "Apple Music" not in html
```

- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.

- [ ] **Step 5: Commit** `git commit -m "feat: quotes, listen and buy links, album genres"`

---

### Task 12: Band page

**Files:**
- Create: `catalog/services/artist_import.py`, `catalog/templates/catalog/artist_detail.html`, `catalog/templates/catalog/_artist_sections.html`, `catalog/templates/catalog/_cover_grid.html`
- Modify: `catalog/views.py`, `catalog/urls.py`, `catalog/tasks.py`
- Test: `tests/catalog/test_artist.py`

**Interfaces:**
- Consumes: `get_artist`, `browse_release_groups` (Task 3); `import_artist_wikidata` (Task 8); `import_wikipedia_stories`, `import_lastfm_stories`, `select_story` (Tasks 9–10); `classify_url`, `attach_genres` (Task 11).
- Produces:
  - `import_artist_core(mbid: str, *, foreground: bool) -> Artist` — artist fields, url links, MB genres, `Membership`s from `member of band` relations (backward direction; `begin`/`end` years; `attributes` → instruments), and album stubs for every release group (title, year from `first-release-date`, `primary_type`, `secondary_types`) without importing their releases.
  - URL names `artist_detail` (`artist/<uuid:mbid>/`), `artist_enrichment` (`artist/<uuid:mbid>/sections/`) with the same polling pattern as Task 5.
  - `discography_sections(artist) -> list[tuple[str, list[Album]]]` — keys `studio` (primary Album, no secondary types), `ep`, `live`, `compilation`, `other`, each sorted by year (None last); only `studio` is expanded by default (`<details open>`), the rest are collapsed `<details>`.
  - `_cover_grid.html` (cover tiles linking to `album_detail`, lazy-loaded images from `cover_url()` with a placeholder) — reused by search and genre pages.
  - Header image: `artist.image_url` with its Commons source link; otherwise the cover of the studio album with the highest `lastfm_listeners`, else the first studio album.
  - Album page: band name links to `artist_detail`.

- [ ] **Step 1: Write the failing tests**

```python
def test_artist_page_lists_studio_albums_first(client, db, nirvana_respx):
    html = client.get(f"/pt/artist/{NIRVANA}/").content.decode()
    assert html.index("Nevermind") < html.index("Ao vivo")

def test_members_with_years(client, imported_nirvana):
    assert "Dave Grohl" in client.get(imported_nirvana.url_pt).content.decode()

def test_discography_paginates_past_100(db, respx_150_release_groups):
    artist = import_artist_core(BIG_ARTIST, foreground=True)
    assert artist.album_set.count() == 150

def test_artist_story_falls_back_to_generated(client, artist_without_stories):
    assert "Conheces a história" in client.get(artist_without_stories.url_pt).content.decode()
```

- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.

- [ ] **Step 5: Commit** `git commit -m "feat: band page with story, discography and members"`

---

### Task 13: Search and suggestions

**Files:**
- Create: `catalog/services/search.py`, `catalog/templates/catalog/search.html`, `catalog/templates/catalog/_suggestions.html`
- Modify: `catalog/views.py`, `catalog/urls.py`, `catalog/templates/catalog/home.html`, `templates/base.html` (compact search in the header)
- Test: `tests/catalog/test_search.py`

**Interfaces:**
- Consumes: `search_artists`, `search_release_groups`, `escape_lucene` (Task 3); `normalize` (Task 3); `_cover_grid.html` (Task 12).
- Produces:
  - `suggest(query: str) -> dict[str, list]` — local only; `{"artists": ≤5 Artist, "albums": ≤5 Album}` by `search_name__contains=normalize(query)`, prefix matches first; queries shorter than 2 normalised characters return empty lists. Never calls a source.
  - `SearchResults` dataclass: `artists: list[Artist]`, `albums: list[Album]`, `source_error: bool`.
  - `search(query: str) -> SearchResults` — merges local matches with MusicBrainz (`search_artists(escape_lucene(q))`, `search_release_groups(f'releasegroup:({escape_lucene(q)}) AND (primarytype:album OR primarytype:ep)')`, `foreground=True`), upserting Artist/Album stubs so later suggestions find them; de-duplicates by MBID; albums ordered by MB score, ties by `lastfm_listeners` desc. On `SourceUnavailable`, returns local results with `source_error=True` (page shows a short notice).
  - URL names `search` (`search/?q=`) and `suggest` (`search/suggest/?q=`); the home and header inputs use `hx-get` to `suggest` with `hx-trigger="input changed delay:250ms"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_suggest_is_accent_insensitive(db, artist_factory):
    artist_factory(name="Sigur Rós")
    assert [a.name for a in suggest("sigur ros")["artists"]] == ["Sigur Rós"]

def test_suggest_never_calls_sources(db, respx_mock):
    suggest("radiohead"); assert not respx_mock.calls

def test_suggest_short_query_empty(db): assert suggest("a") == {"artists": [], "albums": []}

@respx.mock
def test_search_escapes_lucene(db):
    route = respx.get(url__startswith="https://musicbrainz.org/ws/2/artist").respond(json={"artists": []})
    respx.get(url__startswith="https://musicbrainz.org/ws/2/release-group").respond(json={"release-groups": []})
    search('AC/DC')
    assert "AC\\/DC" in route.calls[0].request.url.params["query"]

def test_search_upserts_stubs(db, mb_search_respx): ...
def test_search_survives_source_down(db, mb_503, artist_factory):
    artist_factory(name="Björk")
    r = search("bjork"); assert r.source_error and r.artists

def test_results_page_shows_bands_then_cover_grid(client, db, mb_search_respx): ...
```

- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.

- [ ] **Step 5: Commit** `git commit -m "feat: search with local suggestions and MusicBrainz results"`

---

### Task 14: Genre rooms and seed command

**Files:**
- Create: `catalog/management/commands/seed.py`, `catalog/seed_data.py`, `catalog/templates/catalog/genre_detail.html`
- Modify: `catalog/tasks.py` (`resolve_genre_room` body), `catalog/views.py`, `catalog/urls.py`, `catalog/templates/catalog/home.html`, `tests/conftest.py` (`genre_factory`), `tests/test_home.py` (remove xfail)
- Test: `tests/catalog/test_genres_room.py`, `tests/catalog/test_seed.py`

**Interfaces:**
- Consumes: `list_genres` (Task 3), `tag_top_albums`, `tag_info` (Task 10), `search_release_groups` (Task 3), `import_album_core` (Task 4), `enqueue_enrichment` (Task 7).
- Produces:
  - URL name `genre_detail` (`genre/<slug:slug>/`); 404 for an unknown slug.
  - `resolve_genre_room(genre_id)`: store/refresh `GenreRanking` rows from `tag_top_albums(genre.name, 100)`; for each unresolved row, find the release group by `search_release_groups(f'releasegroup:"{title}" AND artist:"{artist}"', limit=1)` and accept it only if `normalize` of title and artist match; set `album`, `resolved_at`. Background priority (`foreground=False`).
  - `room_by_decade(genre) -> list[tuple[int, list[Album]]]` — resolved albums grouped by `year // 10 * 10`, decades ascending, albums by `rank` within each; albums without a year go to a final "Sem data" group. Popularity numbers are never rendered. While unresolved rows exist, the page shows "Esta sala ainda está a ser montada." and enqueues `resolve_genre_room` (deduped).
  - `seed_data.py`: `FEATURED_GENRES: list[str]` (about 8 slugs, e.g. rock, jazz, hip-hop, electronic, shoegaze, fado, punk, soul — check each exists in the MB genre list) and `SEED_ALBUMS: list[str]` (release-group MBIDs: the test reference albums — a very well-known one (Nevermind), a Portuguese album, one with an English-only Wikipedia article, one with no Wikipedia article, one without a vinyl edition — plus a few more per featured genre). Look the MBIDs up on musicbrainz.org.
  - `manage.py seed`: creates/updates every `Genre` from `list_genres()` (slug = `slugify(name)`), marks `FEATURED_GENRES` as `featured`, sets genre descriptions from `tag_info`, imports and enriches each seed album synchronously (`enrich_album.call`), resolves each featured room. Idempotent; prints progress; resumable after interruption.

- [ ] **Step 1: Write the failing tests**

```python
def test_room_groups_by_decade(db, genre_with_ranked_albums):  # years 1967, 1991, 1994, None
    assert [d for d, _ in room_by_decade(genre_with_ranked_albums)] == [1960, 1990, None]

def test_room_hides_numbers(client, genre_with_ranked_albums):
    assert "listeners" not in client.get("/pt/genre/shoegaze/").content.decode()

def test_incomplete_room_notice(client, genre_with_unresolved): ...
def test_unknown_genre_404(client, db): assert client.get("/pt/genre/nope/").status_code == 404
def test_resolution_rejects_mismatched_artist(db, respx_mismatch): ...
def test_seed_is_idempotent(db, seed_respx):
    call_command("seed"); call_command("seed")
    assert Genre.objects.filter(featured=True).count() == len(FEATURED_GENRES)
```

- [ ] **Step 2–4:** run → FAIL, implement, run → PASS (including `tests/test_home.py` without the xfail).

- [ ] **Step 5: Commit** `git commit -m "feat: genre rooms by decade and seed command"`

---

### Task 15: Admin with locked fields

**Files:**
- Modify: `catalog/admin.py`
- Test: `tests/catalog/test_admin.py`

**Interfaces:**
- Consumes: `LockableModel`, `is_manual` fields (Task 3); `import_album_core` / `enqueue_enrichment` (Tasks 4, 7).
- Produces: admin for Artist, Album (inlines: Credits, Stories, Quotes, Awards, ExternalLinks), Genre. `save_model` on lockable models appends `form.changed_data` to `locked_fields` (deduped); inline rows created or changed in the admin get `is_manual=True`. A "Unlock all fields" action clears `locked_fields`; a "Refresh now" action calls `enqueue_enrichment` (and `import_album_core` for albums).

- [ ] **Step 1: Write the failing tests**

```python
def test_admin_edit_locks_field(admin_client, imported_album):
    admin_client.post(change_url(imported_album), form_data(imported_album, title="Nevermind (corrigido)"))
    imported_album.refresh_from_db()
    assert "title" in imported_album.locked_fields

def test_locked_field_survives_reimport(db, imported_album, mb_fixtures):
    imported_album.title = "X"; imported_album.locked_fields = ["title"]; imported_album.save()
    import_album_core(str(imported_album.mbid), foreground=False)
    imported_album.refresh_from_db(); assert imported_album.title == "X"

def test_inline_story_marked_manual(admin_client, imported_album): ...
```

- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.

- [ ] **Step 5: Commit** `git commit -m "feat: admin corrections that survive refresh"`

---

### Task 16: Production readiness, CI and README

**Files:**
- Modify: `config/settings.py`
- Create: `.github/workflows/ci.yml`, `README.md`, `.env.example`, `docs/screenshots/` (PNG)
- Test: `tests/test_deploy_settings.py`

**Interfaces:**
- Produces: production settings (`DEBUG` false by default, `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS` from env, WhiteNoise with `CompressedManifestStaticFilesStorage`, secure cookies and `SECURE_PROXY_SSL_HEADER` when not DEBUG, logging to stdout); start commands documented: `gunicorn config.wsgi` (web) and the task worker; `manage.py migrate && manage.py seed` on first deploy.

- [ ] **Step 1: Write the failing test**

```python
def test_check_deploy_passes(monkeypatch):
    # env: DEBUG=0, SECRET_KEY=50+ random chars, ALLOWED_HOSTS=example.org
    out = run_manage("check", "--deploy", "--fail-level", "WARNING", env=prod_env)
    assert out.returncode == 0
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** settings; CI workflow on push/PR to `main`: Python 3.14, `pip install -r requirements-dev.txt`, `pytest`, `manage.py makemigrations --check`, `manage.py check --deploy` with dummy env.

- [ ] **Step 4: Run** `.venv/bin/pytest -q` → all PASS.

- [ ] **Step 5: README** (English, portfolio-oriented): what it is and the "museum" idea, link to the live demo (placeholder until deployed), screenshots of home, album page, band page and a genre room (take them from the local server after `manage.py seed`), the architecture (sources layer, cache + rate limiter, background enrichment, story fallback chain), the data sources with licences, how to run locally (venv, `.env.example`, `migrate`, `seed`, `runserver`, worker), the roadmap (phases 2–5).

- [ ] **Step 6: Commit** `git commit -m "chore: production settings, CI and README"`

- [ ] **Step 7: Stop and ask the user** to choose the host (propose one free/near-free Python web service + managed PostgreSQL, with the trade-offs: sleeping instances, free database expiry) before creating any account or deploying.

---

## Self-review notes

- Spec coverage: search (13), band page (12), album page (5–6, 10–11), stories chain (9–10), quotes (11), credits (4), awards (8), listen/buy (11), other editions (5, rendered from `Release` rows), genre rooms (14), pt/en (1, every template task), sources shown (every enricher stores url/licence), phase-2 data (Credit, Place, Influence in 3–4, 8), demo publication (16), seed (14), locked fields (3, 15), staleness (7), DB-backed queue (7), rate limiter with foreground priority (2).
- Not implemented on purpose (spec non-goals): track ranking, charts, similar albums, concerts, accounts, reviews, the "Conheces a história" form (placeholder only).
