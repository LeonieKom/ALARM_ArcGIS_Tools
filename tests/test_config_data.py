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
