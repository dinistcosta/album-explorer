import pytest

from catalog.models import Credit, Place, Release
from catalog.services.stories import build_fact_sheet, build_artist_fact_sheet
from tests.ids import NEVERMIND_RG


def add_release(album, formats, label="", date="1995", reference=False):
    import uuid
    r = Release.objects.create(mbid=uuid.uuid4(), album=album, title=album.title, date=date,
                               formats=formats, label=label)
    if reference:
        album.reference_release = r
        album.save()
    return r


def add_studio(album, name="Estúdios Valentim de Carvalho", area="Paço de Arcos", begin=""):
    import uuid
    place = Place.objects.create(mbid=uuid.uuid4(), name=name, area=area)
    return Credit.objects.create(album=album, place=place, role="recorded at", begin_date=begin)


def add_producers(album, artist_factory, *names):
    for n in names:
        Credit.objects.create(album=album, person=artist_factory(name=n), role="producer")


@pytest.fixture
def full(album_factory, artist_factory):
    album = album_factory(year=1995)
    add_release(album, ["Vinyl", "Digital Media"], "EMI", reference=True)
    add_release(album, ["CD"], "EMI")
    add_studio(album, begin="1994-03")
    add_producers(album, artist_factory, "Ana Silva", "Rui Costa")
    return album


def test_fact_sheet_pt_full(full):
    assert build_fact_sheet(full, "pt") == [
        "Gravado em 1994 em Estúdios Valentim de Carvalho, Paço de Arcos. "
        "Produzido por Ana Silva e Rui Costa. "
        "Editado em 1995 pela editora EMI, em vinil, CD e digital."
    ]


def test_fact_sheet_en_full(full):
    assert build_fact_sheet(full, "en") == [
        "Recorded in 1994 at Estúdios Valentim de Carvalho, Paço de Arcos. "
        "Produced by Ana Silva and Rui Costa. "
        "Released in 1995 by EMI on vinyl, CD and digital."
    ]


def test_formats_order_and_ignored(album_factory):
    album = album_factory(year=1995)
    add_release(album, ["Cassette", "8-Track Cartridge"], "EMI", reference=True)
    add_release(album, ["CD", "Vinyl"], "EMI")
    assert build_fact_sheet(album, "en") == ["Released in 1995 by EMI on vinyl, CD and cassette."]


def test_fact_sheet_en_without_studio(album_factory, artist_factory):
    album = album_factory(year=1995)
    add_release(album, ["CD"], "EMI", reference=True)
    add_producers(album, artist_factory, "Ana Silva")
    assert build_fact_sheet(album, "en") == ["Produced by Ana Silva. Released in 1995 by EMI on CD."]


def test_studio_without_year(album_factory):
    album = album_factory()
    add_studio(album)
    assert build_fact_sheet(album, "pt") == ["Gravado em Estúdios Valentim de Carvalho, Paço de Arcos."]
    assert build_fact_sheet(album, "en") == ["Recorded at Estúdios Valentim de Carvalho, Paço de Arcos."]


def test_studio_without_area(album_factory):
    album = album_factory()
    add_studio(album, name="Abbey Road", area="", begin="1969")
    assert build_fact_sheet(album, "en") == ["Recorded in 1969 at Abbey Road."]


def test_earliest_dated_studio_wins_and_three_producers(album_factory, artist_factory):
    album = album_factory()
    add_studio(album, name="Late", area="X", begin="1992")
    add_studio(album, name="Early", area="Y", begin="1991-05")
    add_producers(album, artist_factory, "A", "B", "C", "A")
    assert build_fact_sheet(album, "en") == ["Recorded in 1991 at Early, Y. Produced by A, B and C."]


def test_label_without_formats_or_year(album_factory):
    album = album_factory()
    add_release(album, [], "EMI", reference=True)
    assert build_fact_sheet(album, "en") == ["Released by EMI."]
    assert build_fact_sheet(album, "pt") == ["Editado pela editora EMI."]


def test_empty_album_yields_no_paragraphs(album_factory):
    assert build_fact_sheet(album_factory(), "pt") == []


def test_artist_group_variants(artist_factory):
    a = artist_factory(name="Os Xis", artist_type="Group", country="PT", begin_year=1980)
    assert build_artist_fact_sheet(a, "pt") == ["Os Xis é uma banda de Portugal, formada em 1980."]
    assert build_artist_fact_sheet(a, "en") == ["Os Xis is a band from Portugal, formed in 1980."]
    a.begin_year = None
    assert build_artist_fact_sheet(a, "en") == ["Os Xis is a band from Portugal."]
    a.country, a.begin_year = "", 1980
    assert build_artist_fact_sheet(a, "pt") == ["Os Xis é uma banda formada em 1980."]
    a.begin_year = None
    assert build_artist_fact_sheet(a, "en") == ["Os Xis is a band."]


def test_artist_person_variants(artist_factory):
    a = artist_factory(name="Zé", artist_type="Person", country="BR", begin_year=1970)
    assert build_artist_fact_sheet(a, "pt") == ["Artista de Brasil, em atividade desde 1970."]
    assert build_artist_fact_sheet(a, "en") == ["Artist from Brazil, active since 1970."]
    a.begin_year = None
    assert build_artist_fact_sheet(a, "en") == ["Artist from Brazil."]
    a.country, a.begin_year = "", 1970
    assert build_artist_fact_sheet(a, "pt") == ["Artista em atividade desde 1970."]
    a.begin_year = None
    assert build_artist_fact_sheet(a, "pt") == []


def test_import_stores_recorded_at_begin_date(imported_album):
    dates = set(imported_album.credits.filter(role="recorded at").values_list("begin_date", flat=True))
    assert "1991-05" in dates
