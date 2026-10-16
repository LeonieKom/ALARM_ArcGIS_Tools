# Changelog

All notable changes to the ALARM ArcGIS Tools will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Generate Report: HTML export crashed with `NameError` (`datetime` was not imported)
- Load ALARM Data: PRA text fields (`elev_med`, `aspect_deg`, ...) are now converted to DOUBLE so numeric filters work
- Load/Filter/Export: ArcPy cannot resolve shapefile paths with a dot in the name (e.g. `..._rel2.3m.shp`), so conversions and counts now work on map layers instead of paths
- Export Filtered Data: output names are sanitized (dots in layer names produced invalid shapefile names); uses `ExportFeatures`
- Load ALARM Data no longer writes spatial index files (`.sbn/.sbx`) into the results folders on `L:`

### Added
- Filter Layers: "Filter Mode" (refine / replace / reset) so filters can be applied step by step on already filtered layers; counts shown before and after each step
- Load ALARM Data: optional PFV (flow velocity) and PFT (flow thickness) rasters, styled from the `.lyrx` files written by the pipeline

### Changed
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

---

## Future Releases

### [1.1.0] - Planned
- Add batch processing for multiple regions
- Export symbology to layer files (.lyrx)
- Custom symbology editor
- Integration with QGIS (optional)

### [1.2.0] - Planned
- Automated report generation
- Statistics dashboard
- Comparison tools for scenarios
