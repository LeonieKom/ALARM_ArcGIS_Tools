# Changelog

All notable changes to the ALARM ArcGIS Tools will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-10-19

Larger rework: filtering step by step, a real scenario comparison, the `alarm_core` package with tests, and several fixes for wrong or misleading results. The "Update Overview" tool was removed (see below); scenario descriptions in the dialogs changed, so saved tool parameters may need to be set again.

### Fixed
- Filter Layers: if applying a filter failed, the layer lost its previous filter (or kept the broken one); the previous filter is restored now
- Load ALARM Data / Compare Scenarios: backup copies (`*.backup.*`, `_ALT`, `_NEU`) and other result types with the same prefix (`pra_binary_*`, `risk_assessment_*`) were matched by the wildcards and could be loaded instead of the results (found in `01_Finnmarkskysten` A-C)
- Generate Report: buildings without elevation were counted as 0 m; they are listed as "Unknown" now
- Filter Layers, Export, Generate Report: a warning when a selection limits counts, export or report
- Generate Report: HTML export crashed with `NameError` (`datetime` was not imported)
- Load ALARM Data: PRA text fields (`elev_med`, `aspect_deg`, ...) are now converted to DOUBLE so numeric filters work
- Load/Filter/Export: ArcPy cannot resolve shapefile paths with a dot in the name (e.g. `..._rel2.3m.shp`), so conversions and counts now work on map layers instead of paths
- Export Filtered Data: output names are sanitized (dots in layer names produced invalid shapefile names); uses `ExportFeatures`
- Load ALARM Data no longer writes spatial index files (`.sbn/.sbx`) into the results folders on `L:`

### Added
- Load ALARM Data: several regions and/or scenarios in one run (every region x scenario combination gets its own group layer; combinations without data are skipped with a warning)
- GitHub Actions workflow that runs the tests without arcpy on every push
- Dialog checks in Filter Layers and Compare Scenarios (min above max, missing directions or degree values, out-of-range values); Load ALARM Data skips files that are already in the map
- `alarm_core` package with the logic that does not need arcpy (config, data lookup, .dbf reader, filters, comparison); `ALARM_Tools.pyt` shrank from about 1760 to 1360 lines
- Central configuration: results folder and scenarios can be changed in `alarm_tools_config.json` or via `ALARM_RESULTS_BASE`, no code edit needed
- Test suite (`tests/`): 88 tests without arcpy and 27 integration tests; the SQL filters and the Python filters are checked against each other
- Compare Scenarios: now a real comparison. One shared filter is applied to all scenarios of a region; the result is an HTML/CSV table (tracks, PRAs, buildings by safety class and max PPR). Replaces the previous swipe/side-by-side instructions
- Load ALARM Data: the converted PRA copy is cached in the project geodatabase (keyed on the shapefile's modification time and size). First load ~1 min for a large region, later loads under a second; the cache is rebuilt when the source changes
- Filter Layers: aspect filter (cardinal directions) for Risk Assessment via `pra_aspct`; option to switch feature counting off
- Filter Layers: "Filter Mode" (refine / replace / reset) so filters can be applied step by step on already filtered layers; counts shown before and after each step
- Load ALARM Data: optional PFV (flow velocity) and PFT (flow thickness) rasters, styled from the `.lyrx` files written by the pipeline

### Changed
- Compare Scenarios: rows renamed to "Buildings in risk assessment", "Highest max PPR" and "Mean of max PPR"
- Generate Report: the report states layer, data source, filter and selection; the file name contains the layer name
- Scenario descriptions in the dialogs are shorter ("A - 80-60, prox0, rel1.2m")
- Stopped tracking the `*.pyt.xml` files that ArcGIS Pro regenerates
- Filter Layers: neighbouring aspect directions are merged into one range, which keeps queries short; feature counts use the layer directly (no temporary layer)
- Load ALARM Data: PPR raster symbology now comes from the pipeline's `.lyrx` (built-in scale only as fallback)
- Filter Layers: layers are now picked explicitly from the map (type detected by fields) instead of guessed from layer names; new "Reset filters" option; feature counts are computed from the source with the query; aspect filter for Risk Assessment is reported as unsupported instead of silently ignored

### Removed
- Update Overview tool (it could not run inside ArcGIS Pro: the script it started needs geopandas/rasterio and is not part of the toolbox); run `generate_data_overview.py` from the pipeline environment instead
- Obsolete helper scripts (`analyze_fields.py`, `check_fields_*.txt`) and stale per-tool `.pyt.xml` files

## [1.0.0] - 2026-04-07

### Added
- Initial release of ALARM ArcGIS Tools
- **Load ALARM Data** tool for loading region/scenario data with automatic symbology
- **Update Overview** tool for regenerating HTML overview page
- **Apply Symbology** tool for applying standard ALARM symbology to layers
- Automatic symbology for PPR rasters, tracks, PRAs, and risk assessment
- Support for all 5 ALARM scenarios (A, B, C, D, E)
- Dynamic region detection from `L:\ALARM\Results`
- Comprehensive README with installation and usage instructions

### Symbology
- PPR Raster: 5-class blue-green-orange-purple scale (70% opacity)
- Tracks: Logarithmic blue scale by median pressure (90% opacity)
- PRAs: Black outline, no fill
- Risk Assessment: Magenta/pink scale by max pressure (100% opacity)

### Known Issues
- None

