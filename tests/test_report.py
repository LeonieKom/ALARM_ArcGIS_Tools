import csv
from datetime import datetime

from alarm_core import report

ROWS = [
    ("S1", 5.0, 2.0, 100.0, "N"),
    ("S2", 30.0, 10.0, 600.0, "NE"),
    ("S2", 120.0, 50.0, None, "W"),       # no elevation
    ("S3", None, None, 2100.0, ""),        # no PPR, no aspect
    (None, 250.0, 100.0, 1200.0, "180"),   # degrees instead of a direction
]


def test_missing_elevation_is_unknown_not_zero():
    stats = report.collect(ROWS)
    assert stats['elevation']['<500m'] == 1                  # only the 100 m building
    assert stats['elevation'][report.UNKNOWN] == 1
    s = report.summary(stats)
    assert s['elevation_range'] == (100.0, 2100.0)           # 0 m does not appear
    assert s['elevation_unknown'] == 1


def test_counts_and_classes():
    stats = report.collect(ROWS)
    assert stats['total'] == 5
    assert stats['saf'] == {"S1": 1, "S2": 2, "S3": 1, report.UNKNOWN: 1}
    assert stats['ppr'] == {"0-25 kPa": 2, "25-50 kPa": 1, "50-100 kPa": 0, "100-200 kPa": 1, ">200 kPa": 1}
    assert stats['aspect'] == {"N": 1, "NE": 1, "W": 1, report.UNKNOWN: 1, "S": 1}
    assert report.summary(stats)['mean_ppr_average'] == (2 + 10 + 50 + 100) / 4


def test_tables_are_in_a_sensible_order():
    t = {title: rows for title, _, rows in report.tables(report.collect(ROWS))}
    assert [k for k, _ in t["Buildings by Aspect"]] == ["N", "NE", "S", "W", report.UNKNOWN]   # compass order
    assert [k for k, _ in t["Buildings by Safety Class"]][-1] == report.UNKNOWN
    assert [k for k, _ in t["Buildings by Elevation Range"]][-1] == report.UNKNOWN


def test_no_unknown_elevation_row_when_all_have_elevation():
    t = {title: rows for title, _, rows in report.tables(report.collect(ROWS[:2]))}
    assert report.UNKNOWN not in [k for k, _ in t["Buildings by Elevation Range"]]


def test_empty_layer():
    stats = report.collect([])
    s = report.summary(stats)
    assert s['buildings'] == 0 and s['max_ppr_range'] == (None, None) and s['mean_ppr_average'] is None


def test_context_states_filter_and_selection():
    assert report.context_lines("lyr", "", 0) == [("Layer", "lyr"), ("Filter", "none - all features of the layer")]
    ctx = report.context_lines("lyr", "max_ppr >= 10", 7, source=r"L:\x\risk.shp")
    assert ("Filter", "max_ppr >= 10") in ctx
    assert ("Data source", r"L:\x\risk.shp") in ctx
    assert any(k == "Selection" and "7 selected" in v for k, v in ctx)


def test_html_contains_the_context_and_is_escaped(tmp_path):
    ctx = report.context_lines("risk <B>", "saf_class IN ('S2') AND max_ppr >= 10", 3)
    path = tmp_path / "r.html"
    report.write_html(path, report.collect(ROWS), ctx, generated=datetime(2026, 1, 2, 3, 4, 5))
    html = path.read_text(encoding="utf-8")
    assert "saf_class IN (&#x27;S2&#x27;) AND max_ppr &gt;= 10" in html
    assert "3 selected features" in html
    assert "risk &lt;B&gt;" in html and "risk <B>" not in html
    assert "2026-01-02 03:04:05" in html
    assert "1 buildings without elevation not included" in html


def test_csv_contains_the_context(tmp_path):
    ctx = report.context_lines("lyr", "max_ppr >= 10", 0)
    path = tmp_path / "r.csv"
    report.write_csv(path, report.collect(ROWS), ctx)
    rows = list(csv.reader(open(path, encoding="utf-8")))
    assert ["Filter", "max_ppr >= 10"] in rows
    assert ["Buildings without elevation", "1"] in rows
    assert ["Elevation Min", "100"] in rows


def test_merge_buildings_keeps_each_building_once_with_the_highest_pressure():
    records = [
        {'bld_id': 1, 'max_ppr': 10.0, 'layer': 'a'},
        {'bld_id': 2, 'max_ppr': 5.0, 'layer': 'a'},
        {'bld_id': 1, 'max_ppr': 40.0, 'layer': 'b'},          # same building, higher in the other region
        {'bld_id': 2, 'max_ppr': None, 'layer': 'b'},
        {'bld_id': None, 'max_ppr': 1.0, 'layer': 'b'},         # no id: always kept
        {'bld_id': None, 'max_ppr': 1.0, 'layer': 'b'},
    ]
    kept, dropped = report.merge_buildings(records)
    assert dropped == 2
    assert [(r['bld_id'], r['max_ppr'], r['layer']) for r in kept] == [
        (2, 5.0, 'a'), (1, 40.0, 'b'), (None, 1.0, 'b'), (None, 1.0, 'b')]


def test_merge_of_one_layer_changes_nothing():
    records = [{'bld_id': i, 'max_ppr': float(i)} for i in range(5)]
    assert report.merge_buildings(records) == (records, 0)


def test_context_for_one_layer_is_the_plain_context():
    entry = {'name': 'lyr', 'sql': 'max_ppr >= 10', 'description': None, 'selected': 0, 'source': None}
    assert report.context_for_layers([entry]) == report.context_lines('lyr', 'max_ppr >= 10', 0)


def test_context_for_several_layers_lists_each_with_its_filter():
    entries = [{'name': 'risk_A', 'sql': 'x', 'description': 'ALARM: Kommune Tromsø', 'selected': 0},
               {'name': 'risk_B', 'sql': '', 'description': None, 'selected': 3}]
    lines = dict(report.context_for_layers(entries, duplicates=4))
    assert lines["Layers"].startswith("2 risk assessment layers")
    assert lines["Layer 1 filter"] == "ALARM: Kommune Tromsø"
    assert lines["Layer 2 filter"].startswith("none")
    assert "3 selected" in lines["Layer 2 selection"]
    assert lines["Duplicates"].startswith("4 buildings")
