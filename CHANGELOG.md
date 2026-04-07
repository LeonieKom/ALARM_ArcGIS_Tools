# Changelog

All notable changes to the ALARM ArcGIS Tools will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
