"""Municipality helpers: labels, names, the object-ID SQL, and counting inside municipalities."""

import random
import sqlite3

import pytest

from alarm_core import compare, filters as f, kommune
from alarm_core.dbf import RECORD, read_dbf_columns
from dbf_fixture import make_scenario, write_dbf


def test_labels_and_numbers():
    assert kommune.label("5501", "Tromsø - Romsa") == "Tromsø - Romsa (5501)"
    assert kommune.label("5501", None) == "Kommune 5501 (5501)"
    assert kommune.number_of("Tromsø - Romsa (5501)") == "5501"
    assert kommune.number_of("no number") is None
    assert kommune.short_names(["Tromsø - Romsa (5501)", "Bodø (1804)"]) == ["Tromsø", "Bodø"]


def test_official_names_are_joined_in_their_order():
    rows = [("Romsa", 2, "sme", 7), ("Tromsø", 1, "nor", 7), ("Bodø", 1, "nor", 9), (None, 3, "fkv", 9)]
    assert kommune.names_by_key(rows) == {7: "Tromsø - Romsa", 9: "Bodø"}


def run_sql(condition, ids):
    db = sqlite3.connect(":memory:")
    db.execute("create table t (FID integer)")
    db.executemany("insert into t values (?)", [(i,) for i in ids])
    return {r[0] for r in db.execute(f"select FID from t where {condition}")}


@pytest.mark.parametrize("wanted", [
    set(), {0}, {5}, {1, 2}, {1, 2, 3}, {0, 1, 2, 3, 10, 12, 13, 14, 15, 40},
    set(random.Random(1).sample(range(5000), 700)),
    set(range(100, 3000)) | {5, 7, 4000},
])
def test_oid_condition_selects_exactly_the_ids(wanted):
    all_ids = range(0, 5001)
    assert run_sql(kommune.oid_condition("FID", wanted), all_ids) == wanted


def test_oid_condition_is_short_for_runs():
    condition = kommune.oid_condition("OBJECTID", range(1, 20001))
    assert condition == "(OBJECTID >= 1 AND OBJECTID <= 20000)"


def test_oid_condition_splits_long_lists():
    condition = kommune.oid_condition("FID", range(0, 5000, 2), max_in=1000)
    assert condition.count(" IN (") == 3


# ------------------------------------------------------------------- criteria text --

def test_kommune_counts_as_a_criterion_and_is_described():
    c = f.make_criteria(kommuner=["Tromsø - Romsa (5501)"])
    assert f.has_any(c)
    assert f.validate(c, require_any=True) == []
    assert f.criteria_notes(c)[0].startswith("Municipality: Tromsø - Romsa (5501)")
    assert f.describe(c) == "Kommune Tromsø"


def test_describe_lists_every_criterion():
    c = f.make_criteria(elev_min=300, elev_max=900, aspect_type=f.ASPECT_CARDINAL, cardinal=["N", "NE"],
                        saf_classes=["S2", "S3"], min_max_ppr=10, kommuner=["Tromsø - Romsa (5501)", "Bodø (1804)"])
    assert f.describe(c) == "Kommune Tromsø, Bodø; 300-900 m; N/NE; S2,S3; PPR >= 10 kPa"
    assert f.describe(f.make_criteria()) == "no criteria"
    assert f.describe(f.make_criteria(elev_max=500)) == "<= 500 m"


# ------------------------------------------------------- counting inside a selection --

def test_dbf_record_positions_are_the_fids(tmp_path):
    write_dbf(tmp_path / "t.dbf", [("id", "N", 8, 0)], [(10,), (11,), (12,), (13,)], deleted={1})
    cols, n = read_dbf_columns(tmp_path / "t.dbf", ["id"], record_index=True)
    assert n == 3 and cols[RECORD] == [0, 2, 3] and cols["id"] == [10.0, 12.0, 13.0]


TRACKS = [(100.0, 10), (200.0, 100), (300.0, 200), (400.0, 350)]
PRAS = [(100, 10), (200, 100), (300, 200), (400, 350), (500, 20)]
RISK = [("S1", 5.0, 100.0, "N"), ("S2", 30.0, 200.0, "E"), ("S3", 120.0, 300.0, "S")]


def test_counts_inside_the_municipality_only(tmp_path):
    sdir = make_scenario(tmp_path, TRACKS, PRAS, RISK)
    inside_sets = {"tracks": {0, 1}, "pra": {1, 2, 4}, "risk": {2}}

    def inside(shp):
        return inside_sets[shp.name.split("_")[0]]

    r = compare.compute_scenario("D", sdir, f.make_criteria(elev_min=150), inside=inside)
    assert r['tracks'] == {'total': 2, 'matched': 1}          # FID 0 (100 m) and 1 (200 m): one >= 150
    assert r['pras'] == {'total': 3, 'matched': 3}
    assert r['risk']['total'] == 1 and r['risk']['matched'] == 1
    assert r['risk']['saf'] == {"S3": 1}


def test_inside_none_means_no_restriction(tmp_path):
    sdir = make_scenario(tmp_path, TRACKS, PRAS, RISK)
    r = compare.compute_scenario("D", sdir, f.make_criteria(), inside=lambda shp: None)
    assert r['tracks']['total'] == 4 and r['risk']['total'] == 3


def test_an_empty_municipality_gives_zero(tmp_path):
    sdir = make_scenario(tmp_path, TRACKS, PRAS, RISK)
    r = compare.compute_scenario("D", sdir, f.make_criteria(), inside=lambda shp: set())
    assert r['tracks'] == {'total': 0, 'matched': 0}
    assert r['risk']['matched'] == 0 and r['risk']['ppr_max'] is None


def test_bundled_list_has_all_municipalities_with_boxes():
    items = kommune.load_list()
    assert len(items) == 357 and len({k["nr"] for k in items}) == 357
    tromso = next(k for k in items if k["nr"] == "5501")
    assert tromso["name"] == "Tromsø" and tromso["bbox"][0] < tromso["bbox"][2]


def test_labels_for_a_box_list_only_overlapping_municipalities():
    lyngen_area = (653380.0, 7685620.0, 709952.7, 7771960.0)       # ALARM2.2 1_Lyngen tracks
    labels = kommune.labels_for(lyngen_area)
    assert "Lyngen (5536)" in labels and "Tromsø (5501)" in labels
    assert not any(l.startswith("Oslo") for l in labels) and len(labels) < 20
    assert labels == sorted(labels, key=str.lower)
    assert len(kommune.labels_for(None)) == 357
    assert kommune.labels_for((0, 0, 1, 1)) == []                    # far away from Norway
