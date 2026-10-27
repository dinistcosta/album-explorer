Recorded from the live MusicBrainz API (real requests, 1 req/s, project User-Agent).
nevermind_rg.json, nevermind_releases.json: release group 1b022e01-4da6-387b-8658-8678046e4cef (Nevermind)
nevermind_reference.json: release 006cb56d-6eff-4b7d-853f-ecd2db97f3b2 (1991-09-24 US Vinyl, tracks numbered 1..12) —
  the release choose_reference_release picks from nevermind_releases.json (earliest full date, US, then lowest id)
release_<id>.json: full releases under their own MusicBrainz id, served as-is by the mb_fixtures fixture:
  8e061dc4-790e-4587-ba53-011e7852f88d (1991-09-24 US CD, 12 tracks; the previous reference)
  f922ec87-4758-421d-a839-3193455345ff (1991-09-24 US 12" Vinyl promo, tracks A1..B6)
  3723c24b-a5a7-3295-b8ab-409a0650efac (1991 GB Vinyl, tracks 1..12)
  704a8006-4ec5-424c-afe2-f4561c4dd79c (1991 XE 12" Vinyl, tracks 1..12)
nevermind_vinyl.json: release 0fb1bdd3-1443-4569-943f-fc69c6424f99 (2009-11-03 US 12" Vinyl, tracks A1..B6)
nirvana_artist.json: artist 5b11f4ce-a62d-471e-81fc-a69a8278c7da (Nirvana)
nirvana_rgs_page1.json: release-group browse for Nirvana, type=album|ep, limit=100, offset=0
