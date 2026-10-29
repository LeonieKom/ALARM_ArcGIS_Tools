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
from arcpy_helpers import P, compare_params, env_context, load_params   # noqa: E402

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


def make_flat_run(base, region=REGION, scenario_id="A", params=PARAMS):
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
               [("saf_class", "TEXT", 4), ("max_ppr", "DOUBLE", None), ("mean_ppr", "DOUBLE", None),
                ("pra_elev", "DOUBLE", None), ("pra_aspct", "TEXT", 4)],
               [(s, p, p / 2, e, a) for s, p, e, a in RISK])
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
    assert [p.name for p in params] == ["source", "source_folder", "region", "scenario", "data_types", "use_group"]
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
    tool.execute([P([long[tracks], long[pras], long[risk]]), P(200), P(None), P("Cardinal Directions"),
                  P(["E", "S", "N"]), P(None), P(None), P(["S2", "S3"]), P(None), P(tool.MODE_REPLACE), P(True)], None)
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
