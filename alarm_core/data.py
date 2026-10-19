"""Finding ALARM result files on disk (no arcpy)."""

from pathlib import Path


def completed_regions(results_base):
    """Regions that have a non-empty 'merged' folder (completed or partial), sorted by name."""
    results_base = Path(results_base)
    regions = []
    if not results_base.exists():
        return regions
    for region_dir in results_base.iterdir():
        if region_dir.is_dir():
            merged_dir = region_dir / "merged"
            if merged_dir.exists() and any(merged_dir.iterdir()):
                regions.append(region_dir.name)
    return sorted(regions)


def find_scenario_dir(results_base, region, scenario_id):
    """Scenario folder <results_base>/<region>/merged/<scenario_id>_*, or None."""
    merged = Path(results_base) / region / "merged"
    if not merged.exists():
        return None
    matches = sorted(merged.glob(f"{scenario_id}_*"))
    return matches[0] if matches else None


def find_file(directory, pattern):
    """First file in directory matching a glob pattern, or None."""
    files = sorted(Path(directory).glob(pattern))
    return files[0] if files else None
