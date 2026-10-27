"""Curated starting data for `manage.py seed`.

Every MBID is a MusicBrainz release-group id, looked up on musicbrainz.org's web service. The
reference albums cover the cases the pages must handle (see comments); the rest give each featured
genre room a few well-known records.
"""

# Slugs, each checked against MusicBrainz's genre list (slug = slugify of the MusicBrainz name).
FEATURED_GENRES: list[str] = [
    "rock", "jazz", "hip-hop", "electronic", "shoegaze", "fado", "punk", "soul",
]

SEED_ALBUMS: list[str] = [
    # Reference albums
    "1b022e01-4da6-387b-8658-8678046e4cef",  # Nirvana – Nevermind (1991): very well known, full coverage
    "022ee031-46a7-3dfb-8377-9bfe05a15c94",  # Madredeus – Existir (1990): Portuguese; pt + en Wikipedia; no vinyl edition on MusicBrainz
    "65790705-6d7b-3596-a427-fe5b8ab6481d",  # Novos Baianos – Acabou Chorare (1972): pt Wikipedia article
    "4ff18a50-33fa-37aa-a355-ea2a70e35ae3",  # Ride – Nowhere (1990): English-only Wikipedia article
    "c6ad23a6-501b-4050-b584-6d41dd796fa8",  # Capitão Fausto – Gazela (2011): small indie release, no Wikipedia article
    "a1b915c6-2da1-3338-8b08-0a92f8ec543f",  # Sétima Legião – Mar d'Outubro (1987): no vinyl edition, English-only Wikipedia
    # rock
    "2e61da88-39e9-3473-81d2-c964cb394952",  # Led Zeppelin – Led Zeppelin IV (1971)
    "9162580e-5df4-32de-80cc-f45a8d8a9b1d",  # The Beatles – Abbey Road (1969)
    "f5093c06-23e3-404f-aeaa-40f72885ee3a",  # Pink Floyd – The Dark Side of the Moon (1973)
    # jazz
    "8e8a594f-2175-38c7-a871-abb68ec363e7",  # Miles Davis – Kind of Blue (1959)
    "77cf47ba-58cd-3f3d-a5f9-79bf89860421",  # John Coltrane – A Love Supreme (1965)
    "035a7881-3e2c-39d2-b110-fe26a4de94e5",  # The Dave Brubeck Quartet – Time Out (1959)
    # hip-hop
    "28298e2c-4d70-3eed-a0f5-a3280c662b3d",  # Nas – Illmatic (1994)
    "c3733436-fcba-3c08-b082-d548df5c5139",  # A Tribe Called Quest – The Low End Theory (1991)
    "610fb60f-900a-3c42-ac7d-f6b6aa8035f9",  # Wu-Tang Clan – Enter the Wu-Tang (36 Chambers) (1993)
    # electronic
    "33101a28-ae05-3a69-873c-684e336fe2df",  # Kraftwerk – Trans Europa Express (1977)
    "48117b90-a16e-34ca-a514-19c702df1158",  # Daft Punk – Discovery (2001)
    "6842c81d-ea77-3dfd-abf7-4323add3f4d4",  # Aphex Twin – Selected Ambient Works 85–92 (1992)
    # shoegaze
    "cb76227e-3ac0-3002-9a10-615a5b73cc59",  # My Bloody Valentine – Loveless (1991)
    "46482030-ef12-319c-9c5a-5d04c39d574b",  # Slowdive – Souvlaki (1993)
    # fado
    "f55f7f69-97ac-343d-b588-48216f463a62",  # Mariza – Fado em mim (2001)
    "d50ea045-e2de-4517-baf9-8053cefae692",  # Amália Rodrigues – Amália Rodrigues (1958)
    # punk
    "7de1e321-4a53-3feb-b83e-f1dab88bf952",  # Ramones – Ramones (1976)
    "e959a4b3-6306-3c45-9df6-e7241dae9ea3",  # Sex Pistols – Never Mind the Bollocks, Here's the Sex Pistols (1977)
    "8d73e45e-7ca1-3cb4-ae28-6da76196c17c",  # The Clash – London Calling (1979)
    # soul
    "c1fa4d2c-ec62-37d5-b01d-6df7f8fd2c90",  # Marvin Gaye – What's Going On (1971)
    "7d8f07a7-4c64-3afb-8daf-8f1d4df89a78",  # Aretha Franklin – I Never Loved a Man the Way I Love You (1967)
    "2c8fd4f3-1523-3604-97dd-18ba222e2f3b",  # Otis Redding – Otis Blue / Otis Redding Sings Soul (1965)
]
