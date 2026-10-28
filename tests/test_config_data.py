import json
from pathlib import Path

import pytest

from alarm_core import config, data


# ------------------------------------------------------------------------- config --

def test_defaults(tmp_path):
    cfg = config.load_config(path=tmp_path / "missing.json", environ={})
    assert cfg['results_base'] == Path(config.DEFAULT_RESULTS_BASE)
    assert list(cfg['scenarios']) == ["A", "B", "C", "D", "E"]


def test_json_overrides_defaults(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"results_base": str(tmp_path / "res"), "scenarios": {"X": "my scenario"}}))
    cfg = config.load_config(path=f, environ={})
    assert cfg['results_base'] == tmp_path / "res"
    assert cfg['scenarios'] == {"X": "my scenario"}


def test_partial_json_keeps_the_other_defaults(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"results_base": "D:/x"}))
    cfg = config.load_config(path=f, environ={})
    assert cfg['scenarios'] == config.DEFAULT_SCENARIOS


def test_environment_wins_over_json(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"results_base": "D:/from_json"}))
    cfg = config.load_config(path=f, environ={"ALARM_RESULTS_BASE": "E:/from_env"})
    assert cfg['results_base'] == Path("E:/from_env")


def test_broken_json_is_reported_with_the_file_name(tmp_path):
    f = tmp_path / "c.json"
    f.write_text("{ not json")
    with pytest.raises(ValueError, match="c.json"):
        config.load_config(path=f, environ={})


def test_scenarios_do_not_leak_between_calls(tmp_path):
    cfg = config.load_config(path=tmp_path / "none.json", environ={})
    cfg['scenarios']['Z'] = "changed"
    assert "Z" not in config.load_config(path=tmp_path / "none.json", environ={})['scenarios']


def test_example_config_matches_defaults():
    example = json.loads((Path(__file__).resolve().parent.parent / "alarm_tools_config.example.json").read_text())
    assert example['scenarios'] == config.DEFAULT_SCENARIOS
    assert example['results_base'] == config.DEFAULT_RESULTS_BASE
    assert example['optimized_base'] == config.DEFAULT_RESULTS_BASE + "_optimized"


def test_optimized_base_follows_results_base(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"results_base": "D:/x/Results"}))
    assert config.load_config(path=f, environ={})['optimized_base'] == Path("D:/x/Results_optimized")
    assert config.load_config(path=tmp_path / "none.json", environ={})['optimized_base'] == \
        Path(config.DEFAULT_RESULTS_BASE + "_optimized")


@pytest.mark.parametrize("json_value, env, expected", [
    ("D:/fast", {}, Path("D:/fast")),
    ("", {}, None),                                                   # switched off
    ("D:/fast", {"ALARM_OPTIMIZED_BASE": "E:/env"}, Path("E:/env")),
    ("D:/fast", {"ALARM_OPTIMIZED_BASE": ""}, None),
])
def test_optimized_base_overrides(tmp_path, json_value, env, expected):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"optimized_base": json_value}))
    assert config.load_config(path=f, environ=env)['optimized_base'] == expected


# --------------------------------------------------------------------------- data --

def make_results(base):
    for region, scenarios in {"01_A": ["A_x", "B_y"], "02_B": ["A_z"], "03_empty": [], "04_nomerged": None}.items():
        (base / region).mkdir(parents=True)
        if scenarios is None:
            continue
        (base / region / "merged").mkdir()
        for s in scenarios:
            (base / region / "merged" / s).mkdir()
    (base / "notes.txt").write_text("x")


def test_completed_regions(tmp_path):
    make_results(tmp_path)
    assert data.completed_regions(tmp_path) == ["01_A", "02_B"]      # empty / missing merged are left out


def test_completed_regions_for_missing_base(tmp_path):
    assert data.completed_regions(tmp_path / "nope") == []


def test_find_scenario_dir(tmp_path):
    make_results(tmp_path)
    assert data.find_scenario_dir(tmp_path, "01_A", "B").name == "B_y"
    assert data.find_scenario_dir(tmp_path, "01_A", "C") is None
    assert data.find_scenario_dir(tmp_path, "nope", "A") is None


def test_find_scenario_dir_does_not_match_a_longer_id(tmp_path):
    (tmp_path / "R" / "merged" / "AB_1").mkdir(parents=True)
    assert data.find_scenario_dir(tmp_path, "R", "A") is None


def test_find_file(tmp_path):
    (tmp_path / "tracks_b.shp").touch()
    (tmp_path / "tracks_a.shp").touch()
    warnings = []
    assert data.find_file(tmp_path, "tracks_*.shp", warn=warnings.append).name == "tracks_a.shp"   # deterministic
    assert len(warnings) == 1 and "tracks_b.shp" in warnings[0]                                   # and reported
    assert data.find_file(tmp_path, "pra_*.shp") is None


@pytest.mark.parametrize("backup", [
    "risk_R_D_rel1.2m.backup.shp",          # reprocess_cell.py (found on L: for 01_Finnmarkskysten A-C)
    "risk_R_D_rel1_2m.backup.shp",
    "risk_R_D_rel1_2m_ALT.shp",             # incremental_remerge.py
    "risk_R_D_rel1_2m_NEU.shp",
    "risk_R_D_rel1_2m_backup.shp",
])
def test_backups_are_never_chosen(tmp_path, backup):
    real = "risk_R_D_rel1.2m.shp" if "1.2m" in backup else "risk_R_D_rel1_2m.shp"
    (tmp_path / backup).touch()
    (tmp_path / real).touch()
    warnings = []
    assert data.find_file(tmp_path, "risk_*.shp", warn=warnings.append).name == real
    assert warnings == []


def test_only_a_backup_means_no_file(tmp_path):
    (tmp_path / "ppr_R_D_max.backup.tif").touch()
    assert data.find_file(tmp_path, "ppr_*.tif") is None


def test_other_result_types_with_the_same_prefix_are_skipped(tmp_path):
    for name in ("pra_binary_R_D.shp", "pra_R_D.shp", "risk_assessment_R_D.shp", "risk_R_D.shp"):
        (tmp_path / name).touch()
    assert data.find_file(tmp_path, "pra_*.shp").name == "pra_R_D.shp"
    assert data.find_file(tmp_path, "risk_*.shp").name == "risk_R_D.shp"
    # lower-case region names would sort after 'binary'/'assessment' - still correct
    (tmp_path / "pra_R_D.shp").unlink()
    (tmp_path / "pra_zz.shp").touch()
    assert data.find_file(tmp_path, "pra_*.shp").name == "pra_zz.shp"


# ----------------------------------------------------------------- optimized copies --

def make_optimized(tmp_path):
    """A result folder with a raster and a shapefile, and their optimized copies."""
    results, fast = tmp_path / "Results", tmp_path / "Results_optimized"
    scen = results / "01_R" / "merged" / "D_75-55_prox0_rel2.3m"
    (scen / "risk_assessment").mkdir(parents=True)
    out = fast / "01_R" / scen.name
    (out / "risk_assessment").mkdir(parents=True)
    for name in ("ppr_R_D_max.tif", "risk_assessment/risk_R_D.shp", "risk_assessment/risk_R_D.dbf"):
        (scen / name).write_bytes(b"x" * 10)
    (out / "ppr_R_D_max.tif").write_bytes(b"cog")
    (out / "risk_assessment" / "risk_R_D.gpkg").write_bytes(b"gpkg")

    def stamp(name):
        st = (scen / name).stat()
        return [st.st_size, int(st.st_mtime)]

    manifest = {"format": 1, "files": {
        "ppr_R_D_max.tif": {"output": "ppr_R_D_max.tif", "sources": {"ppr_R_D_max.tif": stamp("ppr_R_D_max.tif")}},
        "risk_assessment/risk_R_D.shp": {
            "output": "risk_assessment/risk_R_D.gpkg", "layer": "risk_R_D",
            "sources": {"risk_R_D.shp": stamp("risk_assessment/risk_R_D.shp"),
                        "risk_R_D.dbf": stamp("risk_assessment/risk_R_D.dbf")}},
    }}
    (out / data.OPTIMIZED_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    return results, fast, scen, out


def test_optimized_copy_of_raster_and_shapefile(tmp_path):
    results, fast, scen, out = make_optimized(tmp_path)
    assert data.optimized_copy(results, fast, scen / "ppr_R_D_max.tif") == out / "ppr_R_D_max.tif"
    assert data.optimized_copy(results, fast, scen / "risk_assessment" / "risk_R_D.shp") == \
        out / "risk_assessment" / "risk_R_D.gpkg" / "main.risk_R_D"     # the table, as arcpy wants it


def test_changed_source_means_no_copy(tmp_path):
    results, fast, scen, _ = make_optimized(tmp_path)
    (scen / "risk_assessment" / "risk_R_D.dbf").write_bytes(b"patched attributes")   # .shp unchanged
    assert data.optimized_copy(results, fast, scen / "risk_assessment" / "risk_R_D.shp") is None
    assert data.optimized_copy(results, fast, scen / "ppr_R_D_max.tif") is not None


def test_no_copy_without_manifest_entry_or_copy_file(tmp_path):
    results, fast, scen, out = make_optimized(tmp_path)
    (scen / "pft_R_D_max.tif").write_bytes(b"x")
    assert data.optimized_copy(results, fast, scen / "pft_R_D_max.tif") is None      # not in the manifest
    (out / "ppr_R_D_max.tif").unlink()
    assert data.optimized_copy(results, fast, scen / "ppr_R_D_max.tif") is None      # copy deleted
    assert data.optimized_copy(results, None, scen / "ppr_R_D_max.tif") is None      # switched off


def test_broken_manifest_or_foreign_path_means_no_copy(tmp_path):
    results, fast, scen, out = make_optimized(tmp_path)
    assert data.optimized_copy(results, fast, tmp_path / "elsewhere" / "ppr.tif") is None
    (out / data.OPTIMIZED_MANIFEST).write_text("{ half written", encoding="utf-8")
    assert data.optimized_copy(results, fast, scen / "ppr_R_D_max.tif") is None


def test_gpkg_data_source_matches_the_path_it_was_added_from():
    added = r"L:\fast\R\D\risk_assessment\risk_R_D.gpkg\main.risk_R_D"
    reported = r"Instance=L:\fast\R\D\risk_assessment\risk_R_D.gpkg,Dataset=main.%risk_R_D"
    assert data.comparable_source(reported) == data.comparable_source(added)
    assert data.comparable_source(r"l:/fast/R/D/ppr.tif") == data.comparable_source(r"L:\fast\R\D\ppr.tif")
    assert data.comparable_source(reported) != data.comparable_source(added.replace("risk_R_D", "risk_R_E"))
