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
