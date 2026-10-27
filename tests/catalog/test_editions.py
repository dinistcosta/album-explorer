from catalog.services.editions import assign_sides, choose_reference_release, vinyl_candidates


def rel(id, date="", status="Official", formats=("CD",)):
    r = {"id": id, "status": status, "media": [{"format": f} for f in formats]}
    if date:
        r["date"] = date
    return r


def release_with(recordings, numbers=None, titles=None):
    numbers = numbers or [str(i + 1) for i in range(len(recordings))]
    titles = titles or [f"Song {r}" for r in recordings]
    tracks = [
        {"number": n, "title": t, "recording": {"id": r}}
        for r, n, t in zip(recordings, numbers, titles)
    ]
    return {"media": [{"tracks": tracks}]}


def test_reference_is_earliest_official():
    rels = [rel("b", "1992-01"), rel("a", "1991-09-24"), rel("c", "1990", "Bootleg")]
    assert choose_reference_release(rels)["id"] == "a"


def test_falls_back_to_all_when_none_official():
    rels = [rel("b", "1992", "Bootleg"), rel("a", "1991", "Promotion")]
    assert choose_reference_release(rels)["id"] == "a"


def test_partial_date_sorts_before_later_full_date():
    assert choose_reference_release([rel("x", "1991-10-01"), rel("y", "1991")])["id"] == "y"


def test_missing_date_sorts_last():
    assert choose_reference_release([rel("x"), rel("y", "2020")])["id"] == "y"


def test_ties_broken_by_id():
    assert choose_reference_release([rel("b", "1991"), rel("a", "1991")])["id"] == "a"


def test_vinyl_candidates_only_all_vinyl_earliest_first():
    rels = [
        rel("v2", "2009", formats=('12" Vinyl',)),
        rel("cd", "1991"),
        rel("mixed", "1992", formats=("CD", "Vinyl")),
        rel("v1", "1991-10", formats=("Vinyl", "Vinyl")),
    ]
    assert [r["id"] for r in vinyl_candidates(rels)] == ["v1", "v2"]


def test_sides_from_matching_vinyl():
    ref = release_with(["r1", "r2", "r3"], numbers=["1", "2", "3"])
    vin = release_with(["r1", "r2", "r3"], numbers=["A1", "A2", "B1"])
    assert assign_sides(ref, vin) == {"r1": "A", "r2": "A", "r3": "B"}


def test_no_sides_when_tracklists_differ():
    assert assign_sides(release_with(["r1", "r2"]), release_with(["r1", "r9"], numbers=["A1", "B1"])) is None


def test_no_sides_when_vinyl_numbers_are_plain():
    assert assign_sides(release_with(["r1"]), release_with(["r1"], numbers=["1"])) is None


def test_sides_when_vinyl_title_extends_reference_title():
    ref = release_with(["r1", "r2"], titles=["Polly", "Something in the Way"])
    vin = release_with(
        ["r1", "r9"], numbers=["A1", "B1"], titles=["Polly", "Something in the Way / Endless, Nameless"]
    )
    assert assign_sides(ref, vin) == {"r1": "A", "r2": "B"}


def test_no_sides_when_titles_unrelated_and_recordings_differ():
    ref = release_with(["r1", "r2"], titles=["Polly", "Lithium"])
    vin = release_with(["r1", "r9"], numbers=["A1", "B1"], titles=["Polly", "Breed"])
    assert assign_sides(ref, vin) is None


def test_no_sides_when_track_counts_differ():
    assert assign_sides(release_with(["r1", "r2"]), release_with(["r1"], numbers=["A1"])) is None
