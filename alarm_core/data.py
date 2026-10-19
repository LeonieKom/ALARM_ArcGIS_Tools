"""Finding ALARM result files on disk (no arcpy)."""

from pathlib import Path

# Copies the pipeline tools leave next to the results (reprocess_cell.py writes
# '<name>.backup.<ext>', incremental_remerge.py '<name>_ALT/_NEU.<ext>'). They match the
# same wildcards as the real files and sort before them, so they are skipped.
IGNORED_MARKERS = (".backup.", "_backup.", "_alt.", "_neu.")

# Other result files that start like the wanted one: 'pra_*' also matches the binary PRA
# raster export 'pra_binary_*', 'risk_*' also matches 'risk_assessment_*'.
EXCLUDED_PREFIXES = {
    "pra_": ("pra_binary_",),
    "risk_": ("risk_assessment_",),
}


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


def is_ignored(name):
    """True for backup / comparison copies that must never be loaded as results."""
    lower = name.lower()
    return any(marker in lower for marker in IGNORED_MARKERS)


def find_file(directory, pattern, warn=None):
    """The result file in directory matching a glob pattern, or None.

    Backup copies and other result types with the same prefix are skipped (see above).
    If several files remain, the first one (by name) is used and warn() is told about it.
    """
    lower_pattern = pattern.lower()
    excluded = next((v for k, v in EXCLUDED_PREFIXES.items() if lower_pattern.startswith(k)), ())
    files = [p for p in sorted(Path(directory).glob(pattern))
             if not is_ignored(p.name) and not p.name.lower().startswith(excluded)]
    if len(files) > 1 and warn:
        warn(f"  Several files match {pattern} in {Path(directory).name}: using {files[0].name} "
             f"(also: {', '.join(p.name for p in files[1:])})")
    return files[0] if files else None
