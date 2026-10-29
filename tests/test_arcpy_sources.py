"""Data source switch and single-scenario runs (flat merged folder), with real arcpy.

They need ArcGIS Pro's Python and a project file with a map (ALARM_TEST_APRX, see
test_arcpy_integration.py) but NOT the results on L:: the data are tiny shapefiles that this
module creates in the layout the pipeline writes for a single-scenario run:

    <data folder>/1_Lyngen/merged/tracks_1_Lyngen_A_80-60_prox0_rel1_2m.shp
                                  pra_1_Lyngen_A_...shp
                                  risk_assessment/risk_1_Lyngen_A_...shp
"""

import os
from pathlib import Path

import pytest

arcpy = pytest.importorskip("arcpy")

from alarm_core import config, data, filters as f   # noqa: E402
from arcpy_helpers import P, compare_params, env_context, filter_params, load_params   # noqa: E402

APRX = os.environ.get("ALARM_TEST_APRX")
pytestmark = pytest.mark.skipif(not APRX or not Path(APRX).exists(), reason="set ALARM_TEST_APRX to a .aprx file")

OTHER = "Other folder..."
REGION = "1_Lyngen"
PARAMS = "80-60_prox0_rel1_2m"

# (pra_elev, pra_aspdeg) and (elev_med, aspect_deg) as the pipeline writes them
TRACKS = [(100.0, 10), (200.0, 100), (300.0, 200), (400.0, 350)]
PRAS = [(100, 10), (200, 100), (300, 200), (400, 350), (500, 20)]
RISK = [("S1", 5.0, 100.0, "N"), ("S2", 30.0, 200.0, "E"), ("S3", 120.0, 300.0, "S")]


def _square(x):
    return arcpy.Polygon(arcpy.Array([arcpy.Point(x, 0), arcpy.Point(x + 1, 0), arcpy.Point(x + 1, 1),
                                      arcpy.Point(x, 1)]), arcpy.SpatialReference(25833))


def _shapefile(folder, name, fields, rows):
    """Polygon shapefile with the given fields [(name, type, length)] and rows (tuples)."""
    arcpy.management.CreateFeatureclass(str(folder), name, "POLYGON", spatial_reference=arcpy.SpatialReference(25833))
    path = str(Path(folder) / name)
    for fname, ftype, length in fields:
        arcpy.management.AddField(path, fname, ftype, field_length=length)
    with arcpy.da.InsertCursor(path, ["SHAPE@"] + [x[0] for x in fields]) as cursor:
        for i, row in enumerate(rows):
            cursor.insertRow((_square(i * 2),) + tuple(row))


def make_flat_run(base, region=REGION, scenario_id="A", params=PARAMS, risk_fields=None, risk_rows=None):
    """A single-scenario run: all files directly in <base>/<region>/merged/."""
    merged = Path(base) / region / "merged"
    (merged / "risk_assessment").mkdir(parents=True)
    stem = f"{scenario_id}_{params}" if scenario_id else params
    _shapefile(merged, f"tracks_{region}_{stem}.shp",
               [("pra_elev", "DOUBLE", None), ("pra_aspdeg", "LONG", None), ("med_pres", "DOUBLE", None)],
               [(e, a, 50.0) for e, a in TRACKS])
    _shapefile(merged, f"pra_{region}_{stem}.shp",
               [("elev_med", "TEXT", 20), ("aspect_deg", "TEXT", 20), ("area_m2", "TEXT", 20),
                ("T_HIGH", "TEXT", 20), ("T_LOW", "TEXT", 20)],
               [(str(e), str(a), "1000", "80", "60") for e, a in PRAS])
    _shapefile(merged / "risk_assessment", f"risk_assessment_{region}_{stem}.shp",     # the name a single run uses
               risk_fields or [("saf_class", "TEXT", 4), ("max_ppr", "DOUBLE", None), ("mean_ppr", "DOUBLE", None),
                               ("pra_elev", "DOUBLE", None), ("pra_aspct", "TEXT", 4)],
               risk_rows or [(s, p, p / 2, e, a) for s, p, e, a in RISK])
    return merged


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    yield from env_context(tmp_path_factory, APRX)


@pytest.fixture(scope="module")
def run_folder(tmp_path_factory):
    """<tmp>/run1 with 1_Lyngen (flat run, scenario A) and 2_Tromso (flat run without scenario id)."""
    base = tmp_path_factory.mktemp("data") / "run1"
    make_flat_run(base, REGION, "A")
    make_flat_run(base, "2_Tromso", None, "75-55_prox150_rel2_3m")
    return base


def by_name(params):
    return {p.name: p for p in params}


# ------------------------------------------------------------------------ dialog --

def test_load_dialog_has_the_source_parameters_first(env):
    params = env.mod.LoadALARMData().getParameterInfo()
    assert [p.name for p in params] == ["source", "source_folder", "load_by", "region", "municipalities", "scenario",
                                        "data_types", "use_group"]
    labels = params[0].filter.list
    assert labels[-1] == OTHER and len(labels) >= 2
    assert labels[0].startswith(config.STANDARD_SOURCE) and any(l.startswith("ALARM2.2") for l in labels)
    assert params[0].value == labels[0]                       # the standard results are the default
    assert params[1].enabled is False                         # the folder is only for 'Other folder...'


def test_choosing_other_folder_lists_its_regions_and_scenarios(env, run_folder):
    tool = env.mod.LoadALARMData()
    params = load_params(None, None, ["Tracks"], source=OTHER, folder=str(run_folder))
    p = by_name(params)
    p["source"].altered, p["source"].hasBeenValidated = True, False
    p["source_folder"].altered, p["source_folder"].hasBeenValidated = True, False
    tool.updateParameters(params)
    assert p["source_folder"].enabled is True
    assert p["region"].filter.list == [REGION, "2_Tromso"]
    assert p["scenario"].filter.list == ["Select regions first"]          # scenarios come from the chosen regions

    # choosing a region shows the scenarios found in it
    p["region"].value = [REGION]
    p["region"].altered, p["region"].hasBeenValidated = True, False
    tool.updateParameters(params)
    assert p["scenario"].filter.list == ["A - 80-60, prox0, rel1.2m"]
    p["region"].value = [REGION, "2_Tromso"]
    tool.updateParameters(params)
    assert [x.split(" - ")[0] for x in p["scenario"].filter.list] == ["A", data.FLAT_NO_ID]


def test_changing_the_source_drops_choices_that_do_not_exist_there(env, run_folder):
    tool = env.mod.LoadALARMData()
    params = load_params(["99_nowhere", REGION], ["A - old text", "Z - gone"], ["Tracks"], source=OTHER,
                         folder=str(run_folder))
    p = by_name(params)
    p["source"].altered, p["source"].hasBeenValidated = True, False
    tool.updateParameters(params)
    assert p["region"].value == [REGION]
    assert p["scenario"].value == ["A - 80-60, prox0, rel1.2m"]        # Z is gone, the description is current


def test_the_standard_source_offers_the_configured_scenarios(env):
    tool = env.mod.LoadALARMData()
    params = load_params(None, None, ["Tracks"])
    p = by_name(params)
    p["source"].altered, p["source"].hasBeenValidated = True, False
    tool.updateParameters(params)
    assert p["scenario"].filter.list == [f"{k} - {v}" for k, v in config.load_config()['scenarios'].items()]
    assert p["source_folder"].enabled is False


def test_dialog_errors_for_a_missing_folder_and_empty_choices(env, tmp_path):
    tool = env.mod.LoadALARMData()
    p = by_name(load_params(None, None, ["Tracks"], source=OTHER, folder=None))
    tool.updateMessages(list(p.values()))
    assert "Choose the data folder" in p["source_folder"].error

    p = by_name(load_params(None, None, ["Tracks"], source=OTHER, folder=str(tmp_path / "nope")))
    tool.updateMessages(list(p.values()))
    assert "Folder not found" in p["source_folder"].error

    empty = tmp_path / "empty"
    empty.mkdir()
    params = load_params(None, None, ["Tracks"], source=OTHER, folder=str(empty))
    p = by_name(params)
    p["source"].altered, p["source"].hasBeenValidated = True, False
    tool.updateParameters(params)
    p["region"].value = ["No regions found"]
    tool.updateMessages(params)
    assert "No regions found in" in p["region"].error and str(empty) in p["region"].error

    p["region"].value = [REGION]
    p["scenario"].value = ["Select regions first"]
    p["region"].error = None
    tool.updateMessages(params)
    assert "Select the regions first" in p["scenario"].error


# ------------------------------------------------------------------------- loading --

def test_a_flat_run_loads_into_a_group_named_after_the_source(env, run_folder, capfd):
    capfd.readouterr()
    env.mod.LoadALARMData().execute(
        load_params([REGION], ["A - x"], ["Tracks", "PRAs", "Risk Assessment"], True, source=OTHER,
                    folder=str(run_folder)), None)
    out = "".join(capfd.readouterr())
    assert "Data source: Other folder..." in out and str(run_folder) in out
    groups = [l.name for l in env.map.listLayers() if l.isGroupLayer]
    assert f"{REGION} - Scenario A [run1]" in groups
    names = [l.name for l in env.map.listLayers() if l.isFeatureLayer]
    assert any(n.startswith("tracks_1_Lyngen_A_") for n in names)
    assert any(n.startswith("risk_assessment_1_Lyngen_A_") for n in names)
    assert f"pra_{REGION}_A_s_run1" in names                          # the cached copy carries the source tag
    assert "Successfully loaded 3 layers" in out
    arcpy.env.workspace = env.gdb
    fcs = arcpy.ListFeatureClasses("pra_*")
    assert len(fcs) == 1 and "_s_run1_" in fcs[0]


def test_the_layers_of_a_flat_run_work_with_filter_report_and_export(env, run_folder, tmp_path):
    layers = {l.name: l for l in env.map.listLayers() if l.isFeatureLayer}
    tracks = next(n for n in layers if n.startswith("tracks_1_Lyngen_A_"))
    risk = next(n for n in layers if n.startswith("risk_assessment_1_Lyngen_A_"))
    pras = f"pra_{REGION}_A_s_run1"
    long = {l.name: l.longName for l in env.map.listLayers() if l.isFeatureLayer}
    tool = env.mod.FilterLayers()
    tool.execute(filter_params([long[tracks], long[pras], long[risk]],
                               f.make_criteria(elev_min=200, aspect_type=f.ASPECT_CARDINAL, cardinal=["E", "S", "N"],
                                               saf_classes=["S2", "S3"]), tool.MODE_REPLACE, True), None)
    layers = {l.name: l for l in env.map.listLayers() if l.isFeatureLayer}
    # from 200 m up, aspect E, S or N: tracks (200, 100 E), (300, 200 S), (400, 350 N)
    assert int(arcpy.management.GetCount(layers[tracks])[0]) == 3
    assert int(arcpy.management.GetCount(layers[pras])[0]) == 4         # ... and (500, 20 N)
    assert int(arcpy.management.GetCount(layers[risk])[0]) == 2         # S2 200 m E, S3 300 m S
    env.mod.GenerateReport().execute([P(layers[risk]), P(str(tmp_path)), P("HTML")], None)
    assert "Total Buildings Analyzed:</strong> 2<" in next(tmp_path.glob("risk_report_*.html")).read_text("utf-8")


def test_loading_the_same_flat_run_again_adds_nothing(env, run_folder, capfd):
    before = sorted(l.longName for l in env.map.listLayers())
    capfd.readouterr()
    env.mod.LoadALARMData().execute(
        load_params([REGION], ["A - x"], ["Tracks", "PRAs", "Risk Assessment"], True, source=OTHER,
                    folder=str(run_folder)), None)
    assert sorted(l.longName for l in env.map.listLayers()) == before
    assert "".join(capfd.readouterr()).count("Already in the map") == 3


def test_a_run_without_scenario_id_loads_as_single(env, run_folder, capfd):
    capfd.readouterr()
    env.mod.LoadALARMData().execute(
        load_params(["2_Tromso"], [f"{data.FLAT_NO_ID} - x"], ["Tracks"], True, source=OTHER, folder=str(run_folder)),
        None)
    assert "2_Tromso - Scenario single [run1]" in [l.name for l in env.map.listLayers() if l.isGroupLayer]


def test_a_scenario_that_is_not_in_the_folder_is_skipped(env, run_folder, capfd):
    capfd.readouterr()
    env.mod.LoadALARMData().execute(
        load_params([REGION], ["B - x"], ["Tracks"], True, source=OTHER, folder=str(run_folder)), None)
    out = "".join(capfd.readouterr())
    assert "No data found for 1_Lyngen, Scenario B" in out and "Successfully loaded 0 layers" in out


def test_a_missing_folder_is_an_error_not_a_crash(env, tmp_path, capfd):
    capfd.readouterr()
    env.mod.LoadALARMData().execute(
        load_params([REGION], ["A - x"], ["Tracks"], True, source=OTHER, folder=str(tmp_path / "nope")), None)
    assert "Data folder not found" in "".join(capfd.readouterr())


# ------------------------------------------------------------------------ compare --

def test_compare_reads_a_flat_run_and_names_the_source(env, run_folder, tmp_path):
    tool = env.mod.CompareScenarios()
    params = compare_params(REGION, ["A - x"], emin=200, aspect=f.ASPECT_CARDINAL, cardinal=["E", "S", "N"],
                            saf=["S2", "S3"], out=str(tmp_path), fmt="Both", source=OTHER, folder=str(run_folder))
    tool.execute(params, None)
    html = next(tmp_path.glob("compare_*.html")).read_text("utf-8")
    assert f"Data: Other folder...: {run_folder}" in html
    assert "<th>A<br><small>80-60, prox0, rel1.2m</small></th>" in html
    rows = {r[0]: r[1:] for r in __import__("csv").reader(open(next(tmp_path.glob("compare_*.csv")), encoding="utf-8-sig"),
                                                           delimiter=";")}
    assert rows["Avalanche tracks"] == ["3 / 4"]                        # same numbers as the layer filter above
    assert rows["PRAs"] == ["4 / 5"]
    assert rows["Buildings in risk assessment"] == ["2 / 3"]
    header = next(__import__("csv").reader(open(next(tmp_path.glob("compare_*.csv")), encoding="utf-8-sig"), delimiter=";"))
    assert header[1] == f"A ({REGION}/merged)"


def test_compare_dialog_follows_the_source(env, run_folder):
    tool = env.mod.CompareScenarios()
    params = compare_params(REGION, None, source=OTHER, folder=str(run_folder))
    p = by_name(params)
    p["source"].altered, p["source"].hasBeenValidated = True, False
    tool.updateParameters(params)
    assert p["region"].filter.list == [REGION, "2_Tromso"]
    assert p["region"].value == REGION                                  # single region stays single
    assert p["scenarios"].filter.list == ["A - 80-60, prox0, rel1.2m"]
    assert p["scenarios"].value == ["A - 80-60, prox0, rel1.2m"]         # nothing selected before: all of them


# --------------------------------------------------- the real ALARM2.2 test-run folder --

ALARM22 = config.load_config()['sources'].get("ALARM2.2")
needs_alarm22 = pytest.mark.skipif(
    ALARM22 is None or data.find_scenario_dir(ALARM22, "1_Lyngen", data.FLAT_NO_ID) is None,
    reason="the ALARM2.2 folder (1_Lyngen, single-scenario run) is not reachable")


def alarm22_label():
    return f"ALARM2.2  ({ALARM22})"


@needs_alarm22
def test_alarm22_regions_and_scenario_are_offered(env):
    tool = env.mod.LoadALARMData()
    params = load_params(["1_Lyngen"], None, ["Tracks"], source=alarm22_label())
    p = by_name(params)
    p["source"].altered, p["source"].hasBeenValidated = True, False
    tool.updateParameters(params)
    assert "1_Lyngen" in p["region"].filter.list and "2_Tromso" in p["region"].filter.list
    assert [x.split(" - ")[0] for x in p["scenario"].filter.list] == [data.FLAT_NO_ID]
    assert "single run without scenario id" in p["scenario"].filter.list[0]


@needs_alarm22
def test_alarm22_loads_and_matches_the_comparison(env, tmp_path, capfd):
    capfd.readouterr()
    env.mod.LoadALARMData().execute(
        load_params(["1_Lyngen"], [f"{data.FLAT_NO_ID} - x"], ["PPR Raster", "Tracks", "Risk Assessment"], True,
                    source=alarm22_label()), None)
    out = "".join(capfd.readouterr())
    assert "Several files match" not in out                              # the _clipped rasters are no ambiguity
    assert "Successfully loaded 3 layers" in out
    assert "1_Lyngen - Scenario single [ALARM2_2]" in [l.name for l in env.map.listLayers() if l.isGroupLayer]
    layers = {l.name: l for l in env.map.listLayers() if l.isFeatureLayer and "1_Lyngen" in l.name}
    tracks = next(l for n, l in layers.items() if n.startswith("tracks_"))
    risk = next(l for n, l in layers.items() if n.startswith("risk_assessment_"))
    assert not any(x.name.endswith("_clipped.tif") for x in env.map.listLayers() if x.isRasterLayer)

    env.mod.CompareScenarios().execute(
        compare_params("1_Lyngen", [f"{data.FLAT_NO_ID} - x"], out=str(tmp_path), fmt="CSV", source=alarm22_label()), None)
    rows = {r[0]: r[1:] for r in __import__("csv").reader(open(next(tmp_path.glob("compare_*.csv")), encoding="utf-8-sig"),
                                                           delimiter=";")}
    assert rows["Avalanche tracks"] == [f"{int(arcpy.management.GetCount(tracks)[0]):,} / {int(arcpy.management.GetCount(tracks)[0]):,}"]
    assert rows["Buildings in risk assessment"][0].endswith(f"/ {int(arcpy.management.GetCount(risk)[0]):,}")


# ---------------------------------------------------------------- municipality filter --

import csv as _csv
import json as _json
import re as _re
import shutil as _shutil


@pytest.fixture(scope="module")
def test_kommune(tmp_path_factory):
    """A geodatabase like the Kartverket one with one municipality covering the first two squares."""
    folder = tmp_path_factory.mktemp("kommune")
    arcpy.management.CreateFileGDB(str(folder), "k.gdb")
    gdb = folder / "k.gdb"
    arcpy.management.CreateFeatureclass(str(gdb), "kommune", "POLYGON", spatial_reference=arcpy.SpatialReference(25833))
    arcpy.management.AddField(str(gdb / "kommune"), "kommunenummer", "TEXT", field_length=4)
    arcpy.management.AddField(str(gdb / "kommune"), "kommunenavn", "TEXT", field_length=50)
    area = arcpy.Polygon(arcpy.Array([arcpy.Point(-0.5, -1), arcpy.Point(3.5, -1), arcpy.Point(3.5, 2),
                                      arcpy.Point(-0.5, 2)]), arcpy.SpatialReference(25833))
    with arcpy.da.InsertCursor(str(gdb / "kommune"), ["SHAPE@", "kommunenummer", "kommunenavn"]) as cursor:
        cursor.insertRow((area, "9901", "Testkommune"))
    return gdb


@pytest.fixture
def kommune_env(env, test_kommune, monkeypatch, tmp_path):
    monkeypatch.setenv("ALARM_KOMMUNE_GDB", str(test_kommune))
    monkeypatch.setattr(env.mod, "_KOMMUNE_CACHE", tmp_path / "kommune_cache")
    return env


TEST_KOMMUNE = ["Testkommune (9901)"]


def flat_layers(env):
    layers = {l.name: l for l in env.map.listLayers() if l.isFeatureLayer}
    tracks = next(n for n in layers if n.startswith("tracks_1_Lyngen_A_"))
    risk = next(n for n in layers if n.startswith("risk_assessment_1_Lyngen_A_"))
    pras = f"pra_{REGION}_A_s_run1"
    long = {l.name: l.longName for l in env.map.listLayers() if l.isFeatureLayer}
    return [long[tracks], long[pras], long[risk]], (tracks, pras, risk)


def current(env, name):
    return {l.name: l for l in env.map.listLayers() if l.isFeatureLayer}[name]


def active_names(layer):
    return [q['name'] for q in layer.listDefinitionQueries() if q['isActive']]


def test_filter_by_municipality_keeps_what_lies_inside(kommune_env, run_folder, test_kommune):
    env = kommune_env
    names, (tracks, pras, risk) = flat_layers(env)
    tool = env.mod.FilterLayers()
    tool.execute(filter_params(names, f.make_criteria(kommuner=TEST_KOMMUNE), tool.MODE_REPLACE, True), None)
    counts = [int(arcpy.management.GetCount(current(env, n))[0]) for n in (tracks, pras, risk)]
    assert counts == [2, 2, 2]                                 # the squares at x 0-1 and 2-3
    assert active_names(current(env, tracks)) == ["ALARM: Kommune Testkommune"]
    cached = list(env.mod._KOMMUNE_CACHE.glob("9901_*.json"))
    assert len(cached) == 1                                    # boundary cached locally ...
    assert cached[0].name == f"9901_{env.mod._dataset_stamp(test_kommune)}.json"   # ... under a stable key
    reads = []
    real_cursor = arcpy.da.SearchCursor
    try:
        arcpy.da.SearchCursor = lambda *a, **k: reads.append(a[0]) or real_cursor(*a, **k)
        env.mod._kommune_geometry(env.mod._config.load_config(), TEST_KOMMUNE)
    finally:
        arcpy.da.SearchCursor = real_cursor
    assert not any("kommune" in str(r) for r in reads)        # the second time it is not read again

    # refine: in the municipality AND from 200 m up -> only the track at 200 m
    tool.execute(filter_params([names[0]], f.make_criteria(elev_min=200), tool.MODE_REFINE, True), None)
    assert int(arcpy.management.GetCount(current(env, tracks))[0]) == 1
    assert active_names(current(env, tracks)) == ["ALARM: Kommune Testkommune + >= 200 m"]

    # reset removes the named filter as well
    tool.execute(filter_params([names[0]], None, tool.MODE_RESET), None)
    assert not current(env, tracks).definitionQuery
    assert active_names(current(env, tracks)) == []


def test_a_selection_does_not_shrink_the_municipality_set(kommune_env, run_folder):
    env = kommune_env
    names, (tracks, pras, risk) = flat_layers(env)
    layer = current(env, risk)
    layer.setSelectionSet([0], "NEW")                          # one building selected
    try:
        tool = env.mod.FilterLayers()
        tool.execute(filter_params([names[2]], f.make_criteria(kommuner=TEST_KOMMUNE)), None)
        layer = current(env, risk)
        assert len(layer.getSelectionSet() or []) == 1         # the selection is restored
        layer.setSelectionSet([], "NEW")
        assert int(arcpy.management.GetCount(layer)[0]) == 2   # the filter covers both buildings inside
    finally:
        current(env, risk).setSelectionSet([], "NEW")


def test_report_states_the_municipality_and_contains_the_map(kommune_env, run_folder, tmp_path):
    env = kommune_env
    names, (tracks, pras, risk) = flat_layers(env)
    tool = env.mod.FilterLayers()
    tool.execute(filter_params([names[2]], f.make_criteria(kommuner=TEST_KOMMUNE)), None)
    env.mod.GenerateReport().execute([P(current(env, risk)), P(str(tmp_path)), P("HTML"), P(True)], None)
    html = next(tmp_path.glob("risk_report_*.html")).read_text(encoding="utf-8")
    assert "<strong>Filter:</strong> ALARM: Kommune Testkommune" in html
    assert "Filter (SQL)" in html
    assert 'id="alarm-map"' in html and "leaflet" in html
    data = _json.loads(_re.search(r'<script type="application/json" id="alarm-data">(.*?)</script>', html,
                                  _re.S).group(1))
    points = [x for x in data['features'] if not x['properties'].get('outline')]
    assert len(points) == 2 and sum(a['buildings'] for a in data['areas']) == 2
    lon, lat = points[0]['geometry']['coordinates']
    assert -180 <= lon <= 180 and -90 <= lat <= 90                 # projected to WGS84
    assert len([x for x in data['features'] if x['properties'].get('outline')]) == 2   # building outlines
    props = points[0]['properties']
    assert props['saf_class'] in ("S1", "S2") and isinstance(props['max_ppr'], float)   # values under their own names
    assert 'bld_id' not in props                                    # this layer has no bld_id field


def test_report_without_map(kommune_env, run_folder, tmp_path):
    env = kommune_env
    names, (tracks, pras, risk) = flat_layers(env)
    env.mod.GenerateReport().execute([P(current(env, risk)), P(str(tmp_path)), P("HTML"), P(False)], None)
    assert "leaflet" not in next(tmp_path.glob("risk_report_*.html")).read_text(encoding="utf-8")


def test_compare_counts_inside_the_municipality(kommune_env, run_folder, tmp_path):
    env = kommune_env
    env.mod.CompareScenarios().execute(
        compare_params(REGION, ["A - x"], out=str(tmp_path), fmt="Both", source=OTHER, folder=str(run_folder),
                       kommuner=TEST_KOMMUNE), None)
    rows = {r[0]: r[1:] for r in _csv.reader(open(next(tmp_path.glob("compare_*.csv")), encoding="utf-8-sig"),
                                             delimiter=";")}
    assert rows["Avalanche tracks"] == ["2 / 2"]                   # totals refer to the municipality
    assert rows["PRAs"] == ["2 / 2"]
    assert rows["Buildings in risk assessment"] == ["2 / 2"]
    assert "Municipality: Testkommune (9901)" in next(tmp_path.glob("compare_*.html")).read_text(encoding="utf-8")


def test_a_shapefile_with_a_dot_in_its_name_can_be_used_spatially(env, run_folder, tmp_path, test_kommune):
    source = next((run_folder / REGION / "merged").glob("tracks_*.shp"))
    stem = "tracks_R_A_80-60_prox0_rel1.2m"
    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        if source.with_suffix(ext).exists():
            _shutil.copy(source.with_suffix(ext), tmp_path / (stem + ext))
    usable = env.mod._resolvable_shapefile(tmp_path / (stem + ".shp"))
    assert "." not in usable.stem
    geometry = next(arcpy.da.SearchCursor(str(test_kommune / "kommune"), ["SHAPE@"]))[0]
    assert env.mod._oids_inside(str(usable), geometry) == {0, 1}   # FIDs = record positions


def test_the_dialogs_offer_all_municipalities_without_layers(env):
    labels = env.mod._kommune.labels_for(None)
    assert len(labels) == 357 and "Tromsø (5501)" in labels and "Harstad - Hárstták (5503)" in labels
    params = filter_params([], None)
    by = {p.name: p for p in params}
    by["layers_to_filter"].altered, by["layers_to_filter"].hasBeenValidated = True, False
    env.mod.FilterLayers().updateParameters(params)
    assert by["municipalities"].filter.list == labels                # nothing to narrow it down with


@needs_alarm22
def test_real_municipality_filter_on_alarm22(env, tmp_path, monkeypatch):
    """Lyngen layers of the ALARM2.2 run: the list offers Lyngen, and filtering by it keeps features."""
    monkeypatch.setattr(env.mod, "_KOMMUNE_CACHE", tmp_path / "kommune_cache")
    env.mod.LoadALARMData().execute(
        load_params(["1_Lyngen"], [f"{data.FLAT_NO_ID} - x"], ["Risk Assessment"], True, source=alarm22_label()), None)
    layer = next(l for l in env.map.listLayers() if l.isFeatureLayer and l.name.startswith("risk_assessment_1_Lyngen"))
    tool = env.mod.FilterLayers()
    params = filter_params([layer], None)
    by = {p.name: p for p in params}
    by["layers_to_filter"].altered, by["layers_to_filter"].hasBeenValidated = True, False
    tool.updateParameters(params)
    offered = by["municipalities"].filter.list
    lyngen = [x for x in offered if x.startswith("Lyngen")]
    assert lyngen and not any(x.startswith("Oslo") for x in offered) and len(offered) < 40
    total = int(arcpy.management.GetCount(layer)[0])
    tool.execute(filter_params([layer.longName], f.make_criteria(kommuner=lyngen), tool.MODE_REPLACE, True), None)
    layer = next(l for l in env.map.listLayers() if l.isFeatureLayer and l.name.startswith("risk_assessment_1_Lyngen"))
    inside = int(arcpy.management.GetCount(layer)[0])
    assert 0 < inside <= total


# ------------------------------------------------- report over several risk layers --

def _map_data(html):
    return _json.loads(_re.search(r'<script type="application/json" id="alarm-data">(.*?)</script>', html,
                                  _re.S).group(1))


@pytest.fixture(scope="module")
def two_regions(env, tmp_path_factory):
    """Two risk layers sharing building 2, with tracks/PRAs of the same group and a boundary layer."""
    folder = tmp_path_factory.mktemp("two_regions")
    risk_fields = [("bld_id", "LONG", None), ("saf_class", "TEXT", 4), ("max_ppr", "DOUBLE", None),
                   ("mean_ppr", "DOUBLE", None), ("pra_elev", "DOUBLE", None), ("pra_aspct", "TEXT", 4)]
    _shapefile(folder, "risk_RA_A_x.shp", risk_fields, [(1, "S2", 10.0, 5.0, 100.0, "N"), (2, "S3", 20.0, 9.0, 200.0, "E")])
    _shapefile(folder, "risk_RB_A_x.shp", risk_fields, [(9, "S1", 1.0, 1.0, 50.0, "S"), (2, "S3", 50.0, 20.0, 200.0, "E"),
                                                        (3, "S2", 5.0, 2.0, 300.0, "W")])
    _shapefile(folder, "tracks_RA_A_x.shp", [("pra_elev", "DOUBLE", None), ("pra_aspdeg", "LONG", None),
                                             ("med_pres", "DOUBLE", None)], [(100.0, 10, 50.0)])
    # a track far away from every building must not be drawn
    path = str(folder / "tracks_RA_A_x.shp")
    with arcpy.da.InsertCursor(path, ["SHAPE@", "pra_elev", "pra_aspdeg", "med_pres"]) as cursor:
        cursor.insertRow((_square(100000), 100.0, 10, 50.0))
    _shapefile(folder, "pra_RA_A_x.shp", [("elev_med", "DOUBLE", None), ("aspect_deg", "DOUBLE", None)], [(100.0, 10.0)])
    _shapefile(folder, "kommune_9901.shp", [("navn", "TEXT", 50)], [("Testkommune",)])

    m = env.map
    group = m.createGroupLayer("Test regions - Scenario A")
    added = []
    for name in ("risk_RA_A_x", "risk_RB_A_x", "tracks_RA_A_x", "pra_RA_A_x"):
        layer = m.addDataFromPath(str(folder / f"{name}.shp"))
        m.addLayerToGroup(group, layer)
        m.removeLayer(layer)
        added.append(name)
    boundary = m.addDataFromPath(str(folder / "kommune_9901.shp"))
    boundary.name = "Kommune: Testkommune shapefile"      # unique: arcpy resolves layers by name here
    layers = {l.name: l for l in m.listLayers() if l.isFeatureLayer}
    return layers


def test_report_of_two_layers_counts_each_building_once(env, two_regions, tmp_path, capfd):
    risk_a, risk_b = two_regions["risk_RA_A_x"], two_regions["risk_RB_A_x"]
    capfd.readouterr()
    env.mod.GenerateReport().execute([P([risk_a, risk_b]), P(str(tmp_path)), P("Both"), P(True)], None)
    out = "".join(capfd.readouterr())
    assert "1 buildings are in more than one layer" in out
    html_file = next(tmp_path.glob("risk_report_*.html"))
    assert "_and_1_more_" in html_file.name
    html = html_file.read_text(encoding="utf-8")
    assert "Total Buildings Analyzed:</strong> 4<" in html           # 1, 2, 9, 3 - building 2 once
    assert "2 risk assessment layers" in html and "Duplicates" in html
    data = _map_data(html)
    points = [x for x in data['features'] if not x['properties'].get('outline')]
    b2 = [x for x in points if x['properties'].get('bld_id') == 2]
    assert len(b2) == 1 and b2[0]['properties']['max_ppr'] == 50.0     # the higher of the two results
    assert b2[0]['properties']['source'] == "risk_RB_A_x"
    assert data['areas'][0]['max_ppr'] == 50.0                       # priority: highest pressure first
    csv_text = next(tmp_path.glob("risk_report_*.csv")).read_text(encoding="utf-8")
    assert "Total Buildings,4" in csv_text


def test_report_map_has_tracks_pras_and_boundary_as_background(env, two_regions, tmp_path):
    risk_a = two_regions["risk_RA_A_x"]
    env.mod.GenerateReport().execute([P([risk_a]), P(str(tmp_path)), P("HTML"), P(True)], None)
    data = _map_data(next(tmp_path.glob("risk_report_*.html")).read_text(encoding="utf-8"))
    assert len(data['context']['tracks']['features']) == 1           # the far one is left out
    assert len(data['context']['pras']['features']) == 1
    assert any(f['properties'].get('name') == "Testkommune" for f in data['context']['boundaries']['features'])


def test_layers_can_also_be_given_by_name(env, two_regions, tmp_path):
    risk_b = two_regions["risk_RB_A_x"]
    env.mod.GenerateReport().execute([P([risk_b.longName]), P(str(tmp_path)), P("HTML"), P(False)], None)
    html = next(tmp_path.glob("risk_report_*.html")).read_text(encoding="utf-8")
    assert "Total Buildings Analyzed:</strong> 3<" in html


# ----------------------------------- report with tracks / PRA layers chosen as well --

def test_report_with_tracks_and_pras_chosen_too_draws_them(env, two_regions, tmp_path, capfd):
    """As in ArcGIS Pro: risk, PRA and tracks layer of a group all chosen in 'Risk Assessment Layers'."""
    chosen = [two_regions["risk_RA_A_x"], two_regions["pra_RA_A_x"], two_regions["tracks_RA_A_x"]]
    capfd.readouterr()
    env.mod.GenerateReport().execute([P(chosen), P(str(tmp_path)), P("HTML"), P(True)], None)
    out = "".join(capfd.readouterr())
    assert "pra_RA_A_x: not a Risk Assessment layer - drawn on the map" in out
    html = next(tmp_path.glob("risk_report_*.html")).read_text(encoding="utf-8")
    assert "Total Buildings Analyzed:</strong> 2<" in html           # statistics from the risk layer only
    data = _map_data(html)
    assert len(data['context']['tracks']['features']) == 1           # drawn once, not once per way it was found
    assert len(data['context']['pras']['features']) == 1


def test_report_without_any_risk_layer_is_an_error(env, two_regions, tmp_path, capfd):
    capfd.readouterr()
    env.mod.GenerateReport().execute([P([two_regions["tracks_RA_A_x"]]), P(str(tmp_path)), P("HTML"), P(True)], None)
    assert "None of the chosen layers is a Risk Assessment layer" in "".join(capfd.readouterr())
    assert not list(tmp_path.glob("*.html"))


def test_report_dialog_says_how_the_chosen_layers_are_used(env, two_regions):
    tool = env.mod.GenerateReport()
    params = [P([two_regions["risk_RA_A_x"], two_regions["tracks_RA_A_x"],
                 two_regions["Kommune: Testkommune shapefile"]]), P("x"), P("HTML"), P(True)]
    tool.updateMessages(params)
    assert params[0].error is None
    assert "tracks_RA_A_x: drawn on the map" in params[0].warning
    assert "Kommune: Testkommune shapefile: not used" in params[0].warning
    params = [P([two_regions["tracks_RA_A_x"]]), P("x"), P("HTML"), P(True)]
    tool.updateMessages(params)
    assert params[0].error == "Choose at least one Risk Assessment layer."


# ------------------------------------------------------- loading by municipality --

from arcpy_helpers import MODE_KOMMUNER, MODE_REGIONS   # noqa: E402


@pytest.fixture(scope="module")
def two_region_run(tmp_path_factory):
    """<tmp>/run_k with regions R1 and R2 (single-scenario runs, scenario A) on the same squares.

    Buildings 2 and 3 are in both regions (overlapping regions); building 2 is worse in R2.
    """
    base = tmp_path_factory.mktemp("kdata") / "run_k"
    risk_fields = [("bld_id", "LONG", None), ("saf_class", "TEXT", 4), ("max_ppr", "DOUBLE", None),
                   ("mean_ppr", "DOUBLE", None), ("pra_elev", "DOUBLE", None), ("pra_aspct", "TEXT", 4)]
    for region, risk_rows in (
            ("R1", [(1, "S2", 10.0, 5.0, 100.0, "N"), (2, "S3", 20.0, 9.0, 200.0, "E"), (3, "S1", 1.0, 1.0, 300.0, "S")]),
            ("R2", [(2, "S3", 60.0, 9.0, 200.0, "E"), (3, "S1", 1.0, 1.0, 300.0, "S"), (4, "S2", 5.0, 2.0, 400.0, "W")])):
        make_flat_run(base, region, "A", risk_fields=risk_fields, risk_rows=risk_rows)
    return base


def test_load_dialog_switches_between_regions_and_municipalities(env):
    tool = env.mod.LoadALARMData()
    params = load_params(None, None, ["Tracks"], kommuner=None)
    p = {x.name: x for x in params}
    tool.updateParameters(params)
    assert p["region"].enabled is True and p["municipalities"].enabled is False
    p["load_by"].value = MODE_KOMMUNER
    p["load_by"].altered, p["load_by"].hasBeenValidated = True, False
    tool.updateParameters(params)
    assert p["region"].enabled is False and p["municipalities"].enabled is True
    tool.updateMessages(params)
    assert p["municipalities"].error == "Select at least one municipality."
    assert p["region"].error is None                                 # not needed in this mode
    p["load_by"].value = MODE_REGIONS
    p["municipalities"].error = None
    tool.updateMessages(params)
    assert p["region"].error == "Select at least one region."


def test_loading_by_municipality_cuts_and_merges_the_regions(kommune_env, two_region_run, capfd):
    env = kommune_env
    capfd.readouterr()
    env.mod.LoadALARMData().execute(
        load_params(None, ["A - x"], ["Tracks", "PRAs", "Risk Assessment"], True, source=OTHER,
                    folder=str(two_region_run), kommuner=TEST_KOMMUNE), None)
    out = "".join(capfd.readouterr())
    assert "Forecast regions that may overlap them: R1, R2" in out
    assert "risk: 1 buildings were in more than one region" in out   # building 2 (3 of R1 lies outside)
    groups = [l.name for l in env.map.listLayers() if l.isGroupLayer]
    assert "Testkommune - Scenario A [run_k]" in groups
    layers = {l.name: l for l in env.map.listLayers() if l.isFeatureLayer}
    assert "Kommune: Testkommune" in layers                         # the boundary, above the groups
    tracks = layers["tracks - Testkommune - A - run_k"]
    pras = layers["pra - Testkommune - A - run_k"]
    risk = layers["risk - Testkommune - A - run_k"]
    assert int(arcpy.management.GetCount(tracks)[0]) == 4            # squares 0 and 1 of both regions
    assert int(arcpy.management.GetCount(pras)[0]) == 4
    assert {r[0] for r in arcpy.da.SearchCursor(tracks, ["alarm_region"])} == {"R1", "R2"}
    buildings = sorted(arcpy.da.SearchCursor(risk, ["bld_id", "max_ppr", "alarm_region"]))
    assert buildings == [(1, 10.0, "R1"), (2, 60.0, "R2"), (3, 1.0, "R2")]   # inside, each once, worst result
    types = {f.name: f.type for f in arcpy.ListFields(pras.dataSource)}
    assert types["elev_med"] == "Double" and types["aspect_deg"] == "Double"   # numbers, not text
    assert "Successfully loaded 3 layers for Testkommune" in out


def test_loading_the_same_municipality_again_uses_the_cut_out(kommune_env, two_region_run, capfd):
    env = kommune_env
    before = sorted(l.longName for l in env.map.listLayers())
    capfd.readouterr()
    env.mod.LoadALARMData().execute(
        load_params(None, ["A - x"], ["Tracks", "PRAs", "Risk Assessment"], True, source=OTHER,
                    folder=str(two_region_run), kommuner=TEST_KOMMUNE), None)
    out = "".join(capfd.readouterr())
    assert out.count("using the cut-out made earlier") == 3
    assert sorted(l.longName for l in env.map.listLayers()) == before


def test_report_on_a_municipality_load_has_its_background(kommune_env, two_region_run, tmp_path):
    env = kommune_env
    layers = {l.name: l for l in env.map.listLayers() if l.isFeatureLayer}
    risk = layers["risk - Testkommune - A - run_k"]
    env.mod.GenerateReport().execute([P([risk]), P(str(tmp_path)), P("HTML"), P(True)], None)
    data = _map_data(next(tmp_path.glob("risk_report_*.html")).read_text(encoding="utf-8"))
    assert len(data['context']['tracks']['features']) == 4
    assert len(data['context']['pras']['features']) == 4
    assert any(f['properties'].get('name') == "Testkommune" for f in data['context']['boundaries']['features'])
    assert data['areas'][0]['max_ppr'] == 60.0


@needs_alarm22
def test_real_municipality_load_across_two_regions(env, tmp_path, monkeypatch, capfd):
    """Tromsø municipality from the ALARM2.2 runs: found in both regions, cut and merged."""
    monkeypatch.setattr(env.mod, "_KOMMUNE_CACHE", tmp_path / "kommune_cache")
    capfd.readouterr()
    env.mod.LoadALARMData().execute(
        load_params(None, [f"{data.FLAT_NO_ID} - x"], ["Tracks", "Risk Assessment"], True, source=alarm22_label(),
                    kommuner=["Tromsø (5501)"]), None)
    out = "".join(capfd.readouterr())
    assert "1_Lyngen" in out and "2_Tromso" in out
    layers = {l.name: l for l in env.map.listLayers() if l.isFeatureLayer}
    risk = layers["risk - Tromsø - single - ALARM2_2"]
    tracks = layers["tracks - Tromsø - single - ALARM2_2"]
    ids = [r[0] for r in arcpy.da.SearchCursor(risk, ["bld_id"])]
    assert ids and len(ids) == len(set(ids))                         # each building once
    regions = {r[0] for r in arcpy.da.SearchCursor(tracks, ["alarm_region"])}
    assert regions <= {"1_Lyngen", "2_Tromso"} and "2_Tromso" in regions
    assert "Kommune: Tromsø" in layers

