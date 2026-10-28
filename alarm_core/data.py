"""Finding ALARM result files on disk (no arcpy)."""

import json
import ntpath
import os
import re
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


# Written by tools/optimize_results.py (pipeline repository) into every scenario folder
# of the optimized tree: result file -> its copy, plus size and modification time of the
# source file(s) at the time of copying.
OPTIMIZED_MANIFEST = "_sources.json"


def optimized_copy(results_base, optimized_base, source):
    """Path of the optimized copy of a result file, or None to use the file itself.

    The copies live in <optimized_base>/<region>/<scenario>/ (rasters as Cloud-Optimized
    GeoTIFF, shapefiles as GeoPackage). A copy is only returned while every source file
    it was made from (for a shapefile .shp and .dbf) still has the recorded size and
    modification time, so a re-merged or patched result is never shown from an old copy.
    For a GeoPackage the path names its table ('<file>.gpkg/main.<table>'), as arcpy
    expects it.
    """
    if optimized_base is None:
        return None
    try:
        parts = Path(source).relative_to(results_base).parts
    except ValueError:
        return None
    if len(parts) < 4 or parts[1] != "merged":
        return None
    region, scenario = parts[0], parts[2]
    out_dir = Path(optimized_base) / region / scenario
    try:
        manifest = json.loads((out_dir / OPTIMIZED_MANIFEST).read_text(encoding="utf-8"))
        entry = manifest["files"]["/".join(parts[3:])]
        for name, (size, mtime) in entry["sources"].items():
            stat = (Path(source).parent / name).stat()
            if stat.st_size != size or int(stat.st_mtime) != mtime:
                return None
        copy = out_dir / entry["output"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not copy.is_file():
        return None
    if entry.get("layer"):
        return Path(os.path.join(str(copy), f"main.{entry['layer']}"))
    return copy


# ArcGIS Pro reports a GeoPackage layer's dataSource as
# 'Instance=C:\x\file.gpkg,Dataset=main.%table', not as the path it was added from.
_GPKG_SOURCE = re.compile(r"^Instance=(?P<file>.+),Dataset=(?P<table>[^,]+)$", re.IGNORECASE)


def comparable_source(data_source):
    """Normalized form of a file path or layer dataSource, so the two can be compared.

    ArcGIS Pro only runs on Windows, so these are always Windows paths; ntpath keeps the
    result the same when the tests run on Linux.
    """
    text = str(data_source)
    match = _GPKG_SOURCE.match(text)
    if match:
        text = ntpath.join(match.group("file"), match.group("table").replace("%", ""))
    return ntpath.normcase(ntpath.normpath(text))
