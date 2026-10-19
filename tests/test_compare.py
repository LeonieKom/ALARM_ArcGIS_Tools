import csv
from datetime import datetime

import pytest

from alarm_core import compare, filters as f
from dbf_fixture import make_scenario

TRACKS = [(100.0, 10), (200.0, 100), (300.0, 200), (400.0, 350), (None, 90)]
PRAS = [(100, 10), (200, 100), (300, 200), (400, 350), (500, None)]
RISK = [("S1", 5.0, 100.0, "N"), ("S2", 30.0, 200.0, "E"), ("S3", 120.0, 300.0, "S"),
        ("S3", 250.0, 400.0, "W"), (None, None, 500.0, "NW")]


@pytest.fixture
def sdir(tmp_path):
    return make_scenario(tmp_path, TRACKS, PRAS, RISK)


def test_no_filter_counts_everything(sdir):
    r = compare.compute_scenario("D", sdir, f.make_criteria(), label="lbl")
    assert r['id'] == "D" and r['label'] == "lbl" and r['dir'] == sdir.name
    assert r['tracks'] == {'total': 5, 'matched': 5}
    assert r['pras'] == {'total': 5, 'matched': 5}
    assert r['risk']['total'] == 5 and r['risk']['matched'] == 5


def test_elevation_filter_applies_to_all_three(sdir):
    r = compare.compute_scenario("D", sdir, f.make_criteria(elev_min=200, elev_max=400))
    assert r['tracks']['matched'] == 3          # 200, 300, 400; the row without elevation is excluded
    assert r['pras']['matched'] == 3            # text values are read as numbers
    assert r['risk']['matched'] == 3


def test_aspect_cardinal(sdir):
    c = f.make_criteria(aspect_type=f.ASPECT_CARDINAL, cardinal=["N", "NE"])
    r = compare.compute_scenario("D", sdir, c)
    assert r['tracks']['matched'] == 2          # 10 and 350 -> N
    assert r['pras']['matched'] == 2
    assert r['risk']['matched'] == 1            # pra_aspct 'N' only


def test_degree_range_does_not_filter_buildings(sdir):
    c = f.make_criteria(aspect_type=f.ASPECT_DEGREES, aspect_min=300, aspect_max=60)
    r = compare.compute_scenario("D", sdir, c)
    assert r['tracks']['matched'] == 2
    assert r['risk']['matched'] == 5


def test_building_statistics(sdir):
    r = compare.compute_scenario("D", sdir, f.make_criteria(saf_classes=["S2", "S3"], min_max_ppr=30))
    risk = r['risk']
    assert risk['matched'] == 3
    assert risk['saf'] == {"S2": 1, "S3": 2}
    assert risk['ppr_classes'] == {"0-25 kPa": 0, "25-50 kPa": 1, "50-100 kPa": 0, "100-200 kPa": 1, ">200 kPa": 1}
    assert risk['ppr_max'] == 250.0
    assert risk['ppr_mean'] == pytest.approx((30 + 120 + 250) / 3)
    assert sum(risk['ppr_classes'].values()) == risk['matched']


def test_missing_ppr_counts_as_zero_and_missing_class_as_unknown(sdir):
    r = compare.compute_scenario("D", sdir, f.make_criteria())
    assert r['risk']['saf']["Unknown"] == 1
    assert r['risk']['ppr_classes']["0-25 kPa"] == 2      # 5.0 and the missing value


def test_empty_result_has_no_statistics(sdir):
    r = compare.compute_scenario("D", sdir, f.make_criteria(elev_min=10000))
    assert r['risk']['matched'] == 0 and r['risk']['ppr_max'] is None and r['risk']['ppr_mean'] is None


def test_a_backup_risk_table_is_not_used(sdir):
    """reprocess_cell.py leaves '<name>.backup.shp' next to the risk table; it sorts first."""
    from dbf_fixture import write_dbf
    real = next((sdir / "risk_assessment").glob("risk_*.dbf"))
    backup = real.with_name(real.stem + ".backup.dbf")
    assert sorted([real.name, backup.name])[0] == backup.name              # the trap: it sorts first
    write_dbf(backup, [("saf_class", "C", 4, 0), ("max_ppr", "N", 12, 3), ("pra_elev", "N", 12, 3),
                       ("pra_aspct", "C", 4, 0)], [("S1", 1.0, 1.0, "N")])
    backup.with_suffix(".shp").touch()
    r = compare.compute_scenario("D", sdir, f.make_criteria())
    assert r['risk']['total'] == len(RISK)


def test_missing_files_warn_and_give_none(tmp_path):
    (tmp_path / "S").mkdir()
    warnings = []
    r = compare.compute_scenario("S", tmp_path / "S", f.make_criteria(), warn=warnings.append)
    assert r['tracks'] is None and r['pras'] is None and r['risk'] is None
    assert len(warnings) == 3
    rows = compare.build_rows([r])
    assert [v for k, _, v in rows if k == "row"][0] == ["n/a"]      # does not crash


# ------------------------------------------------------------------------ output --

def two_scenarios(tmp_path):
    a = make_scenario(tmp_path / "a", TRACKS, PRAS, RISK, scenario="A_80-60_prox0_rel1.2m")
    d = make_scenario(tmp_path / "d", TRACKS[:3], PRAS[:3], RISK[:2], scenario="D_75-55_prox0_rel2.3m")
    crit = f.make_criteria(saf_classes=["S2", "S3"])
    return crit, [compare.compute_scenario("A", a, crit, label="first"), compare.compute_scenario("D", d, crit, label="second")]


def test_rows_have_one_value_per_scenario(tmp_path):
    crit, results = two_scenarios(tmp_path)
    rows = compare.build_rows(results)
    for kind, label, values in rows:
        assert kind in ("section", "row")
        if kind == "row":
            assert len(values) == 2, label
    by_label = {label: values for kind, label, values in rows if kind == "row"}
    assert by_label["Buildings"] == ["3 / 5", "1 / 2"]
    assert by_label["S3"] == ["2", "0"]            # a class missing in one scenario is shown as 0


def test_text_table(tmp_path):
    crit, results = two_scenarios(tmp_path)
    lines = compare.table_lines(compare.build_rows(results), results)
    assert lines[0].split() == ["A", "D"]
    assert any(l.startswith("Buildings") and "3 / 5" in l for l in lines)


def test_csv(tmp_path):
    crit, results = two_scenarios(tmp_path)
    path = tmp_path / "out.csv"
    compare.write_csv(path, results, compare.build_rows(results))
    rows = list(csv.reader(open(path, encoding="utf-8-sig"), delimiter=";"))
    assert rows[0] == ["Metric", "A (A_80-60_prox0_rel1.2m)", "D (D_75-55_prox0_rel2.3m)"]
    assert ["Buildings", "3 / 5", "1 / 2"] in rows


def test_html_contains_filter_and_is_escaped(tmp_path):
    crit, results = two_scenarios(tmp_path)
    results[0]['label'] = "<b>bad</b> & co"
    path = tmp_path / "out.html"
    compare.write_html(path, "Region <X>", results, compare.build_rows(results), crit, generated=datetime(2026, 1, 2, 3, 4, 5))
    html = path.read_text(encoding="utf-8")
    assert "Safety class: S2, S3" in html
    assert "2026-01-02 03:04:05" in html
    assert "&lt;b&gt;bad&lt;/b&gt; &amp; co" in html and "<b>bad</b>" not in html
    assert "Region &lt;X&gt;" in html
    assert html.count("<tr") == len(compare.build_rows(results)) + 1
