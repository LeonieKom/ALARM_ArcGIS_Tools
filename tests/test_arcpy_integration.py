"""Integration tests: run the toolbox with real arcpy against real ALARM results.

They need
  * ArcGIS Pro's Python (run with propy:  propy.bat -m pytest tests),
  * the results (default L:\\ALARM\\Results, see alarm_core/config.py),
  * a project file with a map to work in:  set ALARM_TEST_APRX=C:\\path\\to\\any.aprx
    (it is copied to a temporary folder; the original is not touched).
Optional: ALARM_TEST_REGION (default 02_Vest_Finnmark), ALARM_TEST_SCENARIO (default D).
Without these the tests are skipped. The first load of a large region takes about a minute.
"""

import importlib.machinery
import importlib.util
import os
import shutil
from pathlib import Path

import pytest

arcpy = pytest.importorskip("arcpy")

from alarm_core import compare, config, data, filters as f   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REGION = os.environ.get("ALARM_TEST_REGION", "02_Vest_Finnmark")
SCEN = os.environ.get("ALARM_TEST_SCENARIO", "D")
APRX = os.environ.get("ALARM_TEST_APRX")

_cfg = config.load_config()
_sdir = data.find_scenario_dir(_cfg['results_base'], REGION, SCEN)

pytestmark = [
    pytest.mark.skipif(not APRX or not Path(APRX).exists(), reason="set ALARM_TEST_APRX to a .aprx file"),
    pytest.mark.skipif(_sdir is None, reason=f"no results for {REGION} / {SCEN}"),
]


class P:
    """Stand-in for an arcpy tool parameter."""

    def __init__(self, value=None):
        self.value = value
        self.enabled = True

    @property
    def valueAsText(self):
        if self.value is None:
            return None
        if isinstance(self.value, (list, tuple)):
            return ";".join(str(x) for x in self.value)
        return str(self.value)


class ProjectProxy:
    """What ArcGISProject('CURRENT') returns inside a tool: our map, our scratch geodatabase."""

    def __init__(self, raw, map_obj, gdb):
        self._raw, self.activeMap, self.activeView, self.defaultGeodatabase = raw, map_obj, None, gdb

    def __getattr__(self, name):
        return getattr(self._raw, name)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    work = tmp_path_factory.mktemp("arcpy_it")
    aprx_copy = work / "test.aprx"
    shutil.copy(APRX, aprx_copy)
    arcpy.management.CreateFileGDB(str(work), "scratch.gdb")
    gdb = str(work / "scratch.gdb")

    loader = importlib.machinery.SourceFileLoader("alarm_tools_under_test", str(ROOT / "ALARM_Tools.pyt"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)

    real = arcpy.mp.ArcGISProject
    raw = real(str(aprx_copy))
    m = raw.listMaps()[0]
    proxy = ProjectProxy(raw, m, gdb)
    arcpy.mp.ArcGISProject = lambda p: proxy if p == "CURRENT" else real(p)
    try:
        yield type("Env", (), {"mod": mod, "map": m, "gdb": gdb, "work": work})
    finally:
        arcpy.mp.ArcGISProject = real


@pytest.fixture(scope="module")
def loaded(env):
    """Load tracks, PRAs and risk assessment once (the PRA conversion is slow)."""
    before_sbn = {p.name for p in _sdir.glob("*.sb[nx]")}
    t0 = __import__("time").time()
    env.mod.LoadALARMData().execute([P(REGION), P(f"{SCEN} - x"), P(["Tracks", "PRAs", "Risk Assessment"]), P(True)], None)
    env.first_load_seconds = __import__("time").time() - t0
    env.sbn_before = before_sbn
    layers = {l.name: l for l in env.map.listLayers() if l.isFeatureLayer}
    env.tracks = next(n for n in layers if n.startswith("tracks_"))
    env.pras = next(n for n in layers if n.startswith("pra_"))
    env.risk = next(n for n in layers if n.startswith("risk_"))
    return env


def feature_layers(env):
    return {l.name: l for l in env.map.listLayers() if l.isFeatureLayer}


def long_names(env, *names):
    by = {l.name: l.longName for l in env.map.listLayers() if l.isFeatureLayer}
    return [by[n] for n in names]


def run_filter(env, layer_names, criteria=None, mode=None, counts=False):
    """Call FilterLayers.execute with layer long names (as ArcGIS Pro passes them)."""
    tool = env.mod.FilterLayers()
    c = criteria or f.make_criteria()
    mode = mode or tool.MODE_REPLACE
    tool.execute([P(long_names(env, *layer_names)), P(c['elev_min']), P(c['elev_max']), P(c['aspect_type']),
                  P(c['cardinal'] or None), P(c['aspect_min']), P(c['aspect_max']),
                  P(c['saf_classes'] or None), P(c['min_max_ppr']), P(mode), P(counts)], None)


def reset_all(env):
    run_filter(env, [env.tracks, env.pras, env.risk], mode=env.mod.FilterLayers.MODE_RESET)


def count(layer):
    return int(arcpy.management.GetCount(layer)[0])


# ------------------------------------------------------------------------ toolbox --

def test_toolbox_lists_five_tools_and_all_parameter_infos_build(env):
    tb = env.mod.Toolbox()
    assert [t.__name__ for t in tb.tools] == ["LoadALARMData", "FilterLayers", "GenerateReport",
                                              "ExportFilteredData", "CompareScenarios"]
    for tool in tb.tools:
        assert tool().getParameterInfo()


# --------------------------------------------------------------------------- load --

def test_load_puts_the_layers_into_one_group(loaded):
    group = [l for l in loaded.map.listLayers() if l.isGroupLayer and l.name == f"{REGION} - Scenario {SCEN}"]
    assert len(group) == 1
    assert all(l.longName.startswith(group[0].name + "\\") for l in feature_layers(loaded).values())


def test_pra_copy_has_numeric_fields_and_a_name_without_dots(loaded):
    arcpy.env.workspace = loaded.gdb
    fcs = arcpy.ListFeatureClasses("pra_*")
    assert len(fcs) == 1 and "." not in fcs[0] and "-" not in fcs[0]
    types = {fld.name: fld.type for fld in arcpy.ListFields(os.path.join(loaded.gdb, fcs[0]))}
    for name in ("elev_med", "aspect_deg", "area_m2", "T_HIGH", "T_LOW"):
        assert types[name] == "Double", name


def test_second_load_uses_the_cache(loaded):
    import time
    arcpy.env.workspace = loaded.gdb
    t0 = time.time()
    loaded.mod.LoadALARMData().execute([P(REGION), P(f"{SCEN} - x"), P(["PRAs"]), P(False)], None)
    cached_seconds = time.time() - t0
    assert len(arcpy.ListFeatureClasses("pra_*")) == 1            # no second conversion
    assert cached_seconds < max(10, loaded.first_load_seconds / 3)


def test_no_spatial_index_files_are_written_into_the_results_folder(loaded):
    assert {p.name for p in _sdir.glob("*.sb[nx]")} == loaded.sbn_before


def test_layer_types_are_detected_by_fields(loaded):
    tool = loaded.mod.FilterLayers()
    layers = feature_layers(loaded)
    assert tool._detect_layer_type(layers[loaded.tracks]) == "tracks"
    assert tool._detect_layer_type(layers[loaded.pras]) == "pras"
    assert tool._detect_layer_type(layers[loaded.risk]) == "risk"


def test_pfv_and_pft_rasters_use_the_pipeline_lyrx(loaded):
    loaded.mod.LoadALARMData().execute([P(REGION), P(f"{SCEN} - x"), P(["PFV Raster", "PFT Raster"]), P(False)], None)
    rasters = {l.name: l for l in loaded.map.listLayers() if l.isRasterLayer}
    pfv = next(l for n, l in rasters.items() if n.startswith("pfv_"))
    assert [b.label for b in pfv.symbology.colorizer.classBreaks][0] == "< 1 m/s"


# -------------------------------------------------------------------------- filter --

CRITERIA = [
    f.make_criteria(elev_min=100, elev_max=900),
    f.make_criteria(aspect_type=f.ASPECT_CARDINAL, cardinal=["N", "NE", "E", "SE", "NW"]),
    f.make_criteria(elev_min=100, aspect_type=f.ASPECT_CARDINAL, cardinal=["S", "SW"], saf_classes=["S2", "S3", "S4"],
                    min_max_ppr=10),
    f.make_criteria(aspect_type=f.ASPECT_DEGREES, aspect_min=300, aspect_max=60),
]


@pytest.mark.parametrize("criteria", CRITERIA, ids=lambda c: ", ".join(f.criteria_notes(c))[:60])
def test_filter_counts_equal_the_python_counts_of_compare(loaded, criteria):
    """The numbers in a map layer (SQL) and in Compare Scenarios (Python) must be identical."""
    reset_all(loaded)
    run_filter(loaded, [loaded.tracks, loaded.pras, loaded.risk], criteria)
    layers = feature_layers(loaded)
    expected = compare.compute_scenario(SCEN, _sdir, criteria)
    assert count(layers[loaded.tracks]) == expected['tracks']['matched']
    assert count(layers[loaded.pras]) == expected['pras']['matched']
    assert count(layers[loaded.risk]) == expected['risk']['matched']


def test_reset_removes_the_filters_and_totals_match(loaded):
    run_filter(loaded, [loaded.tracks, loaded.pras, loaded.risk], f.make_criteria(elev_min=100))
    reset_all(loaded)
    layers = feature_layers(loaded)
    assert all(not l.definitionQuery for l in layers.values())
    totals = compare.compute_scenario(SCEN, _sdir, f.make_criteria())
    assert (count(layers[loaded.tracks]), count(layers[loaded.pras]), count(layers[loaded.risk])) == (
        totals['tracks']['total'], totals['pras']['total'], totals['risk']['total'])


def test_refine_adds_to_the_existing_filter_and_narrows(loaded):
    tool_cls = loaded.mod.FilterLayers
    reset_all(loaded)
    run_filter(loaded, [loaded.tracks], f.make_criteria(elev_min=100, elev_max=900), mode=tool_cls.MODE_REFINE)
    step1 = count(feature_layers(loaded)[loaded.tracks])
    run_filter(loaded, [loaded.tracks], f.make_criteria(aspect_type=f.ASPECT_CARDINAL, cardinal=["N", "NE"]),
               mode=tool_cls.MODE_REFINE)
    layer = feature_layers(loaded)[loaded.tracks]
    assert ") AND (" in layer.definitionQuery and "pra_elev" in layer.definitionQuery and "pra_aspdeg" in layer.definitionQuery
    assert 0 < count(layer) < step1


def test_replace_discards_the_previous_filter(loaded):
    reset_all(loaded)
    run_filter(loaded, [loaded.risk], f.make_criteria(saf_classes=["S3"]))
    run_filter(loaded, [loaded.risk], f.make_criteria(saf_classes=["S2"]), mode=loaded.mod.FilterLayers.MODE_REPLACE)
    assert feature_layers(loaded)[loaded.risk].definitionQuery == "saf_class IN ('S2')"


def test_filter_works_without_counting(loaded):
    reset_all(loaded)
    run_filter(loaded, [loaded.tracks], f.make_criteria(elev_min=100), counts=False)
    assert feature_layers(loaded)[loaded.tracks].definitionQuery == "pra_elev >= 100"


@pytest.mark.parametrize("fail_on_call", [1, 2, 3])
def test_a_failing_filter_keeps_the_previous_filter(loaded, monkeypatch, fail_on_call):
    """Counting changes the query temporarily; an error at any count must restore the old filter."""
    tool_cls = loaded.mod.FilterLayers
    reset_all(loaded)
    run_filter(loaded, [loaded.tracks], f.make_criteria(elev_min=100))
    calls = {"n": 0}
    real_count = tool_cls._count

    def failing_count(self, layer):
        calls["n"] += 1
        if calls["n"] == fail_on_call:
            raise RuntimeError("simulated failure")
        return real_count(self, layer)

    monkeypatch.setattr(tool_cls, "_count", failing_count)
    run_filter(loaded, [loaded.tracks], f.make_criteria(elev_max=900), mode=tool_cls.MODE_REFINE, counts=True)
    assert calls["n"] == fail_on_call
    assert feature_layers(loaded)[loaded.tracks].definitionQuery == "pra_elev >= 100"


def test_unknown_layer_name_only_warns(loaded):
    tool = loaded.mod.FilterLayers()
    tool.execute([P(["no such layer"]), P(100), P(None), P("None"), P(None), P(None), P(None), P(None), P(None),
                  P(tool.MODE_REPLACE), P(False)], None)


# ----------------------------------------------------------------- report / export --

def test_report_writes_html_and_csv(loaded, tmp_path):
    reset_all(loaded)
    risk_layer = feature_layers(loaded)[loaded.risk]
    loaded.mod.GenerateReport().execute([P(risk_layer), P(str(tmp_path)), P("Both")], None)
    names = [p.suffix for p in tmp_path.iterdir()]
    assert ".html" in names and ".csv" in names


def test_export_respects_the_filter_and_sanitizes_the_name(loaded, tmp_path):
    reset_all(loaded)
    risk_layer = feature_layers(loaded)[loaded.risk]
    risk_layer.definitionQuery = "max_ppr >= 10"
    export = loaded.mod.ExportFilteredData()
    export.execute([P(risk_layer), P(str(tmp_path)), P("my.export.v1")], None)
    out = tmp_path / "my_export_v1.shp"
    assert out.exists()
    risk_layer.definitionQuery = ""
    total = count(risk_layer)
    assert 0 < int(arcpy.management.GetCount(str(out))[0]) < total
    export.execute([P(risk_layer), P(str(tmp_path)), P("my.export.v1")], None)      # existing file: error, no crash
    risk_layer.definitionQuery = ""


# ------------------------------------------------------------------------ compare --

def test_compare_tool_writes_the_tables(loaded, tmp_path):
    tool = loaded.mod.CompareScenarios()
    assert len(tool.getParameterInfo()) == 12
    scenarios = [f"{SCEN} - x"]
    tool.execute([P(REGION), P(scenarios), P(100), P(900), P(f.ASPECT_CARDINAL), P(["N", "NE"]), P(None), P(None),
                  P(["S2", "S3"]), P(None), P(str(tmp_path)), P("Both")], None)
    assert len(list(tmp_path.glob("compare_*.html"))) == 1 and len(list(tmp_path.glob("compare_*.csv"))) == 1
