"""The SQL built for the map layers and the Python predicates must select the same features."""

import sqlite3

import pytest

from alarm_core import filters as f

ALL_DIRS = list(f.CARDINAL_RANGES)


# --------------------------------------------------------------- cardinal ranges --

def test_ranges_cover_the_circle_without_gaps_or_overlap():
    ranges = sorted(r for d in ALL_DIRS for r in f.CARDINAL_RANGES[d])
    assert ranges[0][0] == 0 and ranges[-1][1] == 360
    for (_, hi), (lo, _) in zip(ranges, ranges[1:]):
        assert hi == lo


def test_neighbours_are_merged():
    assert f.merged_cardinal_ranges(["N", "NE", "E", "SE", "NW"]) == [(0, 157.5), (292.5, 360)]
    assert f.merged_cardinal_ranges(["N"]) == [(0, 22.5), (337.5, 360)]
    assert f.merged_cardinal_ranges(ALL_DIRS) == [(0, 360)]
    assert f.merged_cardinal_ranges([]) == []
    assert f.merged_cardinal_ranges(["X"]) == []          # unknown names are ignored


# -------------------------------------------------------------------- SQL text --

def test_numeric_query_text():
    c = f.make_criteria(elev_min=100, elev_max=900, aspect_type=f.ASPECT_CARDINAL, cardinal=["N", "NE"])
    assert f.numeric_query(c, "e", "a") == (
        "e >= 100 AND e <= 900 AND ((a >= 0 AND a < 67.5) OR (a >= 337.5 AND a <= 360))")


def test_numeric_query_degree_range_wraps():
    c = f.make_criteria(aspect_type=f.ASPECT_DEGREES, aspect_min=300, aspect_max=60)
    assert f.numeric_query(c, "e", "a") == "(a >= 300 OR a <= 60)"
    c = f.make_criteria(aspect_type=f.ASPECT_DEGREES, aspect_min=60, aspect_max=120)
    assert f.numeric_query(c, "e", "a") == "(a >= 60 AND a <= 120)"


def test_no_criteria_gives_none():
    c = f.make_criteria()
    assert f.numeric_query(c, "e", "a") is None
    assert f.risk_query(c) is None


def test_risk_query_text():
    c = f.make_criteria(elev_min=300, saf_classes=["S2", "S3"], aspect_type=f.ASPECT_CARDINAL,
                        cardinal=["N", "NW"], min_max_ppr=10)
    assert f.risk_query(c) == "pra_elev >= 300 AND saf_class IN ('S2', 'S3') AND pra_aspct IN ('N', 'NW') AND max_ppr >= 10"


def test_risk_query_ignores_degree_range():
    c = f.make_criteria(aspect_type=f.ASPECT_DEGREES, aspect_min=1, aspect_max=2, min_max_ppr=5)
    assert f.risk_query(c) == "max_ppr >= 5"


def test_combine_refine():
    assert f.combine_refine("", "a > 1") == "a > 1"
    assert f.combine_refine("a > 1", "b < 2") == "(a > 1) AND (b < 2)"


# ----------------------------------------------- SQL and Python select the same --

ASPECTS = [x / 2 for x in range(0, 721)]        # 0, 0.5, ... 360


def sql_count_numeric(query, rows):
    db = sqlite3.connect(":memory:")
    db.execute("create table t (e real, a real)")
    db.executemany("insert into t values (?, ?)", rows)
    return db.execute("select count(*) from t" + (f" where {query}" if query else "")).fetchone()[0]


NUMERIC_CASES = [
    f.make_criteria(),
    f.make_criteria(elev_min=100),
    f.make_criteria(elev_max=500),
    f.make_criteria(elev_min=100, elev_max=500),
    f.make_criteria(aspect_type=f.ASPECT_CARDINAL, cardinal=["N"]),
    f.make_criteria(aspect_type=f.ASPECT_CARDINAL, cardinal=["N", "NE", "E", "SE", "NW"]),
    f.make_criteria(aspect_type=f.ASPECT_CARDINAL, cardinal=ALL_DIRS),
    f.make_criteria(aspect_type=f.ASPECT_CARDINAL, cardinal=["S", "W"], elev_min=200),
    f.make_criteria(aspect_type=f.ASPECT_DEGREES, aspect_min=60, aspect_max=120),
    f.make_criteria(aspect_type=f.ASPECT_DEGREES, aspect_min=300, aspect_max=60),
    f.make_criteria(aspect_type=f.ASPECT_DEGREES, aspect_min=350, aspect_max=10, elev_max=300),
]


@pytest.mark.parametrize("criteria", NUMERIC_CASES, ids=lambda c: f.numeric_query(c, "e", "a") or "no filter")
def test_numeric_sql_equals_python(criteria):
    rows = [(e, a) for e in (50.0, 100.0, 300.0, 500.0, 800.0) for a in ASPECTS]
    sql = sql_count_numeric(f.numeric_query(criteria, "e", "a"), rows)
    py = sum(1 for e, a in rows if f.matches_numeric(e, a, criteria))
    assert sql == py


def test_aspect_360_belongs_to_north_and_boundaries_are_half_open():
    north = f.make_criteria(aspect_type=f.ASPECT_CARDINAL, cardinal=["N"])
    assert f.matches_numeric(None, 360, north) and f.matches_numeric(None, 0, north)
    assert f.matches_numeric(None, 22.4, north) and not f.matches_numeric(None, 22.5, north)
    assert not f.matches_numeric(None, 337.4, north) and f.matches_numeric(None, 337.5, north)


def test_missing_values_never_match_a_set_criterion():
    assert not f.matches_numeric(None, 10, f.make_criteria(elev_min=0))
    assert not f.matches_numeric(10, None, f.make_criteria(aspect_type=f.ASPECT_CARDINAL, cardinal=["N"]))
    assert f.matches_numeric(None, None, f.make_criteria())


RISK_ROWS = [(s, p, e, a)
             for s in ("S1", "S2", "S3", "S4")
             for p in (0.0, 9.9, 10.0, 60.0)
             for e in (100.0, 300.0, 900.0)
             for a in ("N", "NE", "E", "SE", "S", "SW", "W", "NW")]

RISK_CASES = [
    f.make_criteria(),
    f.make_criteria(saf_classes=["S2", "S3", "S4"]),
    f.make_criteria(min_max_ppr=10),
    f.make_criteria(elev_min=300, elev_max=900),
    f.make_criteria(aspect_type=f.ASPECT_CARDINAL, cardinal=["N", "NW"]),
    f.make_criteria(saf_classes=["S3"], min_max_ppr=10, elev_min=200, aspect_type=f.ASPECT_CARDINAL, cardinal=["S"]),
    f.make_criteria(aspect_type=f.ASPECT_DEGREES, aspect_min=1, aspect_max=2),   # not applicable to buildings
]


@pytest.mark.parametrize("criteria", RISK_CASES, ids=lambda c: f.risk_query(c) or "no filter")
def test_risk_sql_equals_python(criteria):
    db = sqlite3.connect(":memory:")
    db.execute("create table t (saf_class text, max_ppr real, pra_elev real, pra_aspct text)")
    db.executemany("insert into t values (?, ?, ?, ?)", RISK_ROWS)
    query = f.risk_query(criteria)
    sql = db.execute("select count(*) from t" + (f" where {query}" if query else "")).fetchone()[0]
    py = sum(1 for r in RISK_ROWS if f.matches_risk(*r, criteria))
    assert sql == py


# ------------------------------------------------- tracks of several PRAs (clusters) --

def test_degree_range_classes():
    assert f.degree_range_classes(60, 120) == ["NE", "E", "SE"]
    assert f.degree_range_classes(350, 10) == ["N"]
    assert f.degree_range_classes(22.5, 22.5) == ["NE"]          # boundaries are half-open
    assert f.degree_range_classes(300, 30) == ["N", "NE", "NW"]
    assert sorted(f.degree_range_classes(0, 360)) == sorted(ALL_DIRS)


def test_track_query_without_member_fields_is_the_numeric_query():
    criteria = f.make_criteria(elev_min=100, aspect_type=f.ASPECT_CARDINAL, cardinal=["S"])
    assert f.track_query(criteria, has_members=False) == f.numeric_query(criteria, "pra_elev", "pra_aspdeg")
    assert f.track_query(f.make_criteria(), has_members=True) is None


def test_cluster_track_passes_when_any_member_matches():
    sw = f.make_criteria(aspect_type=f.ASPECT_CARDINAL, cardinal=["SW"])
    w = f.make_criteria(aspect_type=f.ASPECT_CARDINAL, cardinal=["W"])
    # cluster S + SW whose largest member is S (pra_aspdeg 180)
    assert f.matches_track(400, 180, 2, ",S,SW,", 380, 450, sw)
    assert not f.matches_track(400, 180, 2, ",S,SW,", 380, 450, w)
    # elevation: the member range has to overlap the filter
    assert f.matches_track(400, 180, 2, ",S,SW,", 380, 450, f.make_criteria(elev_min=440))
    assert not f.matches_track(400, 180, 2, ",S,SW,", 380, 450, f.make_criteria(elev_min=460))


# pra_elev, pra_aspdeg, n_pras, asp_set, elev_lo, elev_hi
TRACK_ROWS = (
    [(e, a, 1, None, e, e) for e in (50.0, 300.0, 800.0) for a in ASPECTS[::10]]
    + [(e, a, None, None, None, None) for e in (300.0,) for a in ASPECTS[::30]]
    + [(e, 180.0, 2, s, lo, hi)
       for e, lo, hi in ((300.0, 280.0, 340.0), (90.0, 60.0, 120.0), (700.0, 650.0, 900.0))
       for s in (",S,SW,", ",SW,W,", ",N,NE,", ",NW,N,", ",E,", ",SE,S,")]
)


@pytest.mark.parametrize("criteria", NUMERIC_CASES,
                         ids=lambda c: f.track_query(c, has_members=True) or "no filter")
def test_track_sql_equals_python(criteria):
    db = sqlite3.connect(":memory:")
    db.execute("create table t (pra_elev real, pra_aspdeg real, n_pras integer, asp_set text, "
               "elev_lo real, elev_hi real)")
    db.executemany("insert into t values (?, ?, ?, ?, ?, ?)", TRACK_ROWS)
    query = f.track_query(criteria, has_members=True)
    sql = db.execute("select count(*) from t" + (f" where {query}" if query else "")).fetchone()[0]
    py = sum(1 for r in TRACK_ROWS if f.matches_track(*r, criteria))
    assert sql == py


# ------------------------------------------------------------------------ notes --

def test_criteria_notes():
    assert f.criteria_notes(f.make_criteria()) == ["No filter - all features"]
    notes = f.criteria_notes(f.make_criteria(elev_min=100, saf_classes=["S3"], min_max_ppr=25,
                                             aspect_type=f.ASPECT_CARDINAL, cardinal=["N"]))
    assert any("Elevation: 100 to - m" in n for n in notes)
    assert any("Aspect: N" in n for n in notes)
    assert any("Safety class: S3" in n and "buildings only" in n for n in notes)
    assert any("Max PPR at least 25 kPa" in n for n in notes)
    degrees = f.criteria_notes(f.make_criteria(aspect_type=f.ASPECT_DEGREES, aspect_min=10, aspect_max=20))
    assert any("not available for buildings" in n for n in degrees)


# ------------------------------------------------------------------- validation --

def keys(problems):
    return [(k, level) for k, level, _ in problems]


def test_valid_criteria_have_no_problems():
    assert f.validate(f.make_criteria(elev_min=100, elev_max=900)) == []
    assert f.validate(f.make_criteria(aspect_type=f.ASPECT_DEGREES, aspect_min=0, aspect_max=360)) == []
    assert f.validate(f.make_criteria()) == []                        # comparing without a filter is fine


def test_min_above_max():
    assert keys(f.validate(f.make_criteria(elev_min=900, elev_max=100))) == [('elev_max', 'error')]
    assert f.validate(f.make_criteria(elev_min=500, elev_max=500)) == []


def test_cardinal_without_directions():
    assert keys(f.validate(f.make_criteria(aspect_type=f.ASPECT_CARDINAL))) == [('cardinal', 'error')]


def test_degree_range_needs_both_values_in_0_360():
    assert keys(f.validate(f.make_criteria(aspect_type=f.ASPECT_DEGREES, aspect_min=10))) == [('aspect_max', 'error')]
    assert keys(f.validate(f.make_criteria(aspect_type=f.ASPECT_DEGREES))) == [('aspect_min', 'error'), ('aspect_max', 'error')]
    assert keys(f.validate(f.make_criteria(aspect_type=f.ASPECT_DEGREES, aspect_min=-5, aspect_max=400))) == [
        ('aspect_min', 'error'), ('aspect_max', 'error')]
    # values of a disabled degree range do not matter
    assert f.validate(f.make_criteria(aspect_min=-5)) == []


def test_negative_pressure():
    assert keys(f.validate(f.make_criteria(min_max_ppr=-1))) == [('min_max_ppr', 'error')]


def test_require_any():
    assert keys(f.validate(f.make_criteria(), require_any=True)) == [('any', 'warning')]
    assert f.validate(f.make_criteria(saf_classes=["S3"]), require_any=True) == []
    # an aspect type without values is an error, not additionally "no criterion"
    assert keys(f.validate(f.make_criteria(aspect_type=f.ASPECT_CARDINAL), require_any=True)) == [('cardinal', 'error')]


def test_has_any_matches_the_queries():
    """has_any() is True exactly when one of the queries restricts something."""
    for c in NUMERIC_CASES + RISK_CASES:
        restricts = f.numeric_query(c, "e", "a") is not None or f.risk_query(c) is not None
        assert f.has_any(c) == restricts, c
