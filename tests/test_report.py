import csv
import re
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


# ------------------------------------------------- scenario and building table --

def test_scenario_parameters_from_names_folders_and_config():
    expected = {'t_high': 80, 't_low': 60, 'proximity': 0, 'release': 1.2}
    assert report.scenario_params("risk_assessment_2_Tromso_80-60_prox0_rel1_2m.shp") == expected
    assert report.scenario_params(r"L:\ALARM\Results\05_Tromso\merged\A_80-60_prox0_rel1.2m\x.shp") == expected
    assert report.scenario_params("80-60, prox0, rel1.2m") == expected
    assert report.scenario_params("75-55, prox150, rel2.3m")['proximity'] == 150
    assert report.scenario_params("risk - Tromsø - D") is None
    assert report.describe_params(expected) == "PRA thresholds 80 / 60 %, proximity 0 m, release thickness 1.2 m"


def test_scenario_id_from_paths():
    assert report.scenario_id(r"L:\ALARM\Results\05_Tromso\merged\A_80-60_prox0_rel1.2m\risk.shp") == "A"
    assert report.scenario_id("risk_assessment_05_Tromso_D_75-55_prox0_rel2_3m") == "D"
    assert report.scenario_id("risk_assessment_2_Tromso_80-60_prox0_rel1_2m") is None


def test_avalanche_problem_from_the_layer_filters():
    none = {'elev_min': None, 'elev_max': None, 'aspects': None}
    assert report.problem_from_filters([none]) == (["N", "NE", "E", "SE", "S", "SW", "W", "NW"], None, None)
    a = {'elev_min': 300.0, 'elev_max': None, 'aspects': ['SW', 'W']}
    b = {'elev_min': 400.0, 'elev_max': None, 'aspects': ['NW']}
    assert report.problem_from_filters([a, b]) == (['SW', 'W', 'NW'], 300.0, None)    # union of the layers
    assert report.problem_from_filters([a, none])[1] is None


def test_scenario_section_shows_the_symbols():
    html = report.scenario_section([("A", report.scenario_params("80-60, prox0, rel1.2m"))], ["SW", "W"], 300.0, None)
    assert "Scenario A:</strong> PRA thresholds 80 / 60 %" in html
    assert "Avalanche problem (as in Varsom)" in html and "above 300 m" in html
    assert "SW, W" in html and "(from the layer filter)" in html
    plain = report.scenario_section([("x", None)], ["N", "NE", "E", "SE", "S", "SW", "W", "NW"], None, None)
    assert "all aspects" in plain and "all elevations" in plain and "parameters not known" in plain
    assert "(from the layer filter)" not in plain


def test_building_row_uses_all_pras_reaching_the_building():
    assert report.building_row({'pra_asplst': "E, SW, S", 'pra_elvls': "230, 255, 157"}) == (["E", "S", "SW"], "160-260 m")
    assert report.building_row({'pra_aspct': "N", 'pra_elev': 401.0}) == (["N"], "400 m")
    assert report.building_row({}) == ([], "-")


def building_records():
    return [{'bld_id': 1, 'saf_class': "S1", 'max_ppr': 90.0, 'address': "Storgata 1, Tromsø", 'area': 1,
             'pra_asplst': "N", 'pra_elvls': "400"},
            {'bld_id': 2, 'saf_class': "S2", 'max_ppr': 50.0, 'address': "near Vengsøya 565", 'area': 2,
             'pra_asplst': "S, SW", 'pra_elvls': "130, 300"},
            {'bld_id': 3, 'saf_class': "S3", 'max_ppr': 80.0, 'address': None, 'area': 1,
             'pra_aspct': "E", 'pra_elev': 200.0}]


def test_building_table_sorted_by_pressure_with_s1_hidden():
    html = report.buildings_table(building_records(), {1: "Kårvik", 2: "Vengsøya <x>"})
    rows = re.findall(r"<tr(?: class=\"alarm-hidden-class\")?><td>(\d*)</td><td>(S\d)</td><td>([^<]*)</td><td>([^<]*)</td>"
                      r"<td class=\"num\">([^<]*)</td>", html)
    assert rows == [("", "S1", "Storgata 1, Tromsø", "1. Kårvik", "90.0"),      # hidden, no rank
                    ("1", "S3", "-", "1. Kårvik", "80.0"),
                    ("2", "S2", "near Vengsøya 565", "2. Vengsøya &lt;x&gt;", "50.0")]
    assert "Also show the 1 buildings of class S1" in html
    assert '<symbol id="rose-S-SW"' in html and '<use href="#rose-S-SW"/>' in html
    assert "130-300 m" in html


def test_report_html_order_and_csv_building_list(tmp_path):
    path = tmp_path / "r.html"
    report.write_html(path, report.collect(ROWS), report.context_lines("lyr", "", 0),
                      scenario_html=report.scenario_section([("A", None)], ["N"], None, None),
                      buildings_html=report.buildings_table(building_records()))
    html = path.read_text(encoding="utf-8")
    assert html.index("Avalanche problem") < html.index("Summary") < html.index("Exposed buildings") \
        < html.index("Buildings by Safety Class")
    csv_path = tmp_path / "r.csv"
    report.write_csv(csv_path, report.collect(ROWS), report.context_lines("lyr", "", 0),
                     buildings=building_records(), area_names={1: "Kårvik"})
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("BUILDINGS,"))
    assert lines[start + 1] == "1,1,S1,\"Storgata 1, Tromsø\",1,Kårvik,90.0,N,400 m"
    assert len(lines) - start - 1 == 3                                 # all classes in the CSV


def test_with_a_filter_only_the_release_areas_inside_it_are_listed():
    r = {'pra_asplst': "N, NE, S", 'pra_elvls': "240, 400, 900"}
    assert report.building_row(r, (["N", "S"], None, None)) == (["N", "S"], "240-900 m")
    assert report.building_row(r, (["N", "NE", "S"], 300.0, 800.0)) == (["NE"], "400 m")
    assert report.building_row(r, (["W"], None, None)) == (["N", "NE", "S"], "240-900 m")   # none inside: all
    odd = {'pra_asplst': "N, NE", 'pra_elvls': "240"}                                      # lists do not pair
    assert report.building_row(odd, (["N"], None, None)) == (["N", "NE"], "240 m")
