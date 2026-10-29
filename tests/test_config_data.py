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
    assert example['kommune_gdb'] == config.DEFAULT_KOMMUNE_GDB
    assert {k: Path(v) for k, v in example['sources'].items()} == {
        k: Path(v) for k, v in config.DEFAULT_EXTRA_SOURCES.items()}
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


# ------------------------------------------------------------------------ sources --

def test_sources_default_to_standard_plus_alarm22(tmp_path):
    cfg = config.load_config(path=tmp_path / "none.json", environ={})
    assert list(cfg['sources']) == [config.STANDARD_SOURCE, "ALARM2.2"]
    assert cfg['sources'][config.STANDARD_SOURCE] == cfg['results_base']
    assert cfg['sources']["ALARM2.2"] == Path(r"L:\ALARM\ALARM2.2")


def test_standard_source_follows_results_base(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"results_base": str(tmp_path / "res")}))
    assert config.load_config(path=f, environ={})['sources'][config.STANDARD_SOURCE] == tmp_path / "res"


def test_sources_can_be_added_changed_and_removed(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"sources": {"My run": str(tmp_path / "run1"), "ALARM2.2": "", config.STANDARD_SOURCE: "X:/ignored"}}))
    sources = config.load_config(path=f, environ={})['sources']
    assert list(sources) == [config.STANDARD_SOURCE, "My run"]            # ALARM2.2 removed
    assert sources["My run"] == tmp_path / "run1"
    assert sources[config.STANDARD_SOURCE] == Path(config.DEFAULT_RESULTS_BASE)   # cannot be replaced


# ------------------------------------------------- single-scenario run (flat layout) --

def make_flat(base, region="1_Lyngen", scenario_id="A", params="80-60_prox0_rel1_2m", extra=()):
    """<base>/<region>/merged/ with the files of a single-scenario run, as the pipeline writes them."""
    merged = base / region / "merged"
    (merged / "risk_assessment").mkdir(parents=True)
    stem = f"{scenario_id}_{params}" if scenario_id else params
    for name in (f"tracks_{region}_{stem}.shp", f"pra_{region}_{stem}.shp", f"ppr_{region}_{stem}_max.tif",
                 f"ppr_{region}_{stem}_max_clipped.tif", f"pra_binary_{region}.shp", *extra):
        (merged / name).touch()
    # a single-scenario run names the risk shapefile like its .csv/.xlsx (found on L:\ALARM\ALARM2.2)
    (merged / "risk_assessment" / f"risk_assessment_{region}_{stem}.shp").touch()
    (merged / "risk_assessment" / f"risk_assessment_{region}_{stem}.csv").touch()
    return merged


def test_flat_run_with_scenario_id_is_found_by_its_id(tmp_path):
    merged = make_flat(tmp_path, scenario_id="A")
    assert data.flat_scenario(merged, "1_Lyngen") == ("A", "80-60_prox0_rel1_2m")
    assert data.find_scenario_dir(tmp_path, "1_Lyngen", "A") == merged
    assert data.find_scenario_dir(tmp_path, "1_Lyngen", "B") is None
    assert data.is_flat_scenario(merged)
    assert data.scenario_dir_label(merged) == "1_Lyngen/merged"


def test_flat_run_without_scenario_id(tmp_path):
    merged = make_flat(tmp_path, scenario_id=None)
    assert data.flat_scenario(merged, "1_Lyngen") == (None, "80-60_prox0_rel1_2m")
    assert data.find_scenario_dir(tmp_path, "1_Lyngen", data.FLAT_NO_ID) == merged
    assert data.find_scenario_dir(tmp_path, "1_Lyngen", "A") is None


def test_the_region_name_is_not_taken_for_a_scenario_id(tmp_path):
    """'tracks_1_Lyngen_80-60_...' has no id; 'Lyngen' must not be read as one."""
    merged = make_flat(tmp_path, region="1_Lyngen", scenario_id=None)
    assert data.flat_scenario(merged, "1_Lyngen")[0] is None


def test_files_of_another_region_do_not_count(tmp_path):
    merged = make_flat(tmp_path, region="1_Lyngen")
    assert data.flat_scenario(merged, "2_Tromso") is None


def test_flat_detection_ignores_backups_and_the_binary_pra(tmp_path):
    merged = tmp_path / "R" / "merged"
    merged.mkdir(parents=True)
    (merged / "pra_binary_R.shp").touch()
    (merged / "tracks_R_B_80-60_prox0_rel1_2m.backup.shp").touch()
    assert data.flat_scenario(merged, "R") is None


def test_scenario_folders_win_over_flat_files(tmp_path):
    merged = make_flat(tmp_path, scenario_id="A")
    (merged / "A_80-60_prox0_rel1.2m").mkdir()
    assert data.find_scenario_dir(tmp_path, "1_Lyngen", "A") == merged / "A_80-60_prox0_rel1.2m"
    assert not data.is_flat_scenario(data.find_scenario_dir(tmp_path, "1_Lyngen", "A"))


def test_a_file_named_like_a_scenario_is_not_a_scenario_folder(tmp_path):
    (tmp_path / "R" / "merged").mkdir(parents=True)
    (tmp_path / "R" / "merged" / "A_notes.txt").touch()
    assert data.find_scenario_dir(tmp_path, "R", "A") is None


def test_discover_scenarios_from_folders_and_flat_runs(tmp_path):
    make_flat(tmp_path, region="1_Lyngen", scenario_id="A")
    make_flat(tmp_path, region="2_Tromso", scenario_id=None, params="75-55_prox150_rel2_3m")
    campaign = tmp_path / "3_Other" / "merged"
    for name in ("B_80-60_prox0_rel1.8m", "C_80-60_prox100_rel2.3m", "risk_assessment", "80-60_0__rel1.0m"):
        (campaign / name).mkdir(parents=True)
    found = data.discover_scenarios(tmp_path, ["1_Lyngen", "2_Tromso", "3_Other", "9_missing"])
    assert list(found) == ["A", "B", "C", data.FLAT_NO_ID]
    assert found["A"] == "80-60, prox0, rel1.2m"
    assert found["B"] == "80-60, prox0, rel1.8m"
    assert found[data.FLAT_NO_ID].startswith("single run without scenario id") and "75-55, prox150, rel2.3m" in found[data.FLAT_NO_ID]


def test_discover_scenarios_for_no_regions(tmp_path):
    assert data.discover_scenarios(tmp_path, []) == {}


def test_find_file_works_in_a_flat_folder(tmp_path):
    merged = make_flat(tmp_path, scenario_id="A")
    assert data.find_file(merged, "tracks_*.shp").name.startswith("tracks_1_Lyngen_A_")
    assert data.find_file(merged, "pra_*.shp").name.startswith("pra_1_Lyngen_A_")          # not pra_binary
    assert data.find_risk_file(merged / "risk_assessment").name == "risk_assessment_1_Lyngen_A_80-60_prox0_rel1_2m.shp"


def test_risk_file_of_a_campaign_run_wins_over_the_single_run_name(tmp_path):
    for name in ("risk_R_A_x.shp", "risk_assessment_R_A_x.shp"):
        (tmp_path / name).touch()
    assert data.find_risk_file(tmp_path).name == "risk_R_A_x.shp"


def test_risk_file_missing(tmp_path):
    (tmp_path / "risk_assessment_R_A_x.csv").touch()            # only the table, no shapefile
    (tmp_path / "risk_R_A_x.backup.shp").touch()
    assert data.find_risk_file(tmp_path) is None


def test_the_clipped_variant_of_a_raster_is_not_chosen_and_not_reported(tmp_path):
    for name in ("ppr_R_x_max.tif", "ppr_R_x_max_clipped.tif"):
        (tmp_path / name).touch()
    warnings = []
    assert data.find_file(tmp_path, "ppr_*.tif", warn=warnings.append).name == "ppr_R_x_max.tif"
    assert warnings == []


def test_a_clipped_raster_alone_is_still_found(tmp_path):
    (tmp_path / "ppr_R_x_max_clipped.tif").touch()
    assert data.find_file(tmp_path, "ppr_*.tif").name == "ppr_R_x_max_clipped.tif"


def test_kommune_gdb_setting(tmp_path):
    assert config.load_config(path=tmp_path / "none.json", environ={})['kommune_gdb'] == Path(config.DEFAULT_KOMMUNE_GDB)
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"kommune_gdb": "D:/k.gdb"}))
    assert config.load_config(path=f, environ={})['kommune_gdb'] == Path("D:/k.gdb")
    assert config.load_config(path=f, environ={"ALARM_KOMMUNE_GDB": "E:/x.gdb"})['kommune_gdb'] == Path("E:/x.gdb")


def test_shp_extent_from_the_header(tmp_path):
    import struct
    shp = tmp_path / "t.shp"
    shp.write_bytes(struct.pack(">i", 9994) + bytes(32) + struct.pack("<4d", 1.0, 2.0, 3.0, 4.0) + bytes(32))
    assert data.shp_extent(shp) == (1.0, 2.0, 3.0, 4.0)
    (tmp_path / "bad.shp").write_bytes(b"nope")
    assert data.shp_extent(tmp_path / "bad.shp") is None
    assert data.shp_extent(tmp_path / "missing.shp") is None
    assert data.union_extent([(0, 0, 1, 1), None, (2, -1, 3, 0.5)]) == (0, -1, 3, 1)
    assert data.union_extent([None]) is None
