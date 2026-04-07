# ALARM ArcGIS Tools

ArcGIS Pro Python Toolbox for working with ALARM (Avalanche Risk Assessment) pipeline results.

## Overview

This toolbox provides easy access to ALARM pipeline outputs directly within ArcGIS Pro, with automatic symbology application and data management tools.

**Features:**
- **Load ALARM Data**: Load region/scenario data with automatic symbology
- **Update Overview**: Regenerate HTML overview page
- **Apply Symbology**: Apply standard ALARM symbology to selected layers

## Installation

### Method 1: Direct Download (Recommended)

1. Download this repository as ZIP or clone it:
   ```bash
   git clone https://github.com/LeonieKom/ALARM_ArcGIS_Tools.git
   ```

2. Open ArcGIS Pro

3. Add the toolbox:
   - **Catalog Pane** → **Toolboxes** → Right-click → **Add Toolbox**
   - Navigate to `ALARM_Tools.pyt`
   - Click **OK**

4. The toolbox will appear under "Toolboxes" in the Catalog pane

### Method 2: Add to Favorites

For permanent access:
1. Right-click on the added toolbox
2. Select **Add To Favorites**

## Quick Start

### 1. Load ALARM Data

**Tool:** `Load ALARM Data`

Loads data for a specific region and scenario with automatic symbology.

**Parameters:**
- **Region**: Select from available regions (e.g., Finnmarkskysten, Oslo)
- **Scenario**: Select scenario (A, B, C, D, E, or All)
- **Layers to Load**: Choose which layers to add (PPR, Tracks, PRAs, Risk Assessment)

**What it does:**
- Finds data in `L:\ALARM\Results\{region}\merged\{scenario}\`
- Loads selected layers into current map
- Applies standard ALARM symbology automatically

**Example:**
```
Region: Finnmarkskysten
Scenario: A
Layers: PPR Raster, Tracks, Risk Assessment
→ Loads 3 layers with correct symbology
```

### 2. Update Overview

**Tool:** `Update Overview`

Regenerates the HTML overview page with thumbnails and statistics.

**What it does:**
- Scans `L:\ALARM\Results\` for completed regions
- Generates preview images for each scenario
- Creates interactive HTML page at `L:\ALARM\ALARM_Overview\index.html`

**When to use:**
- After new regions are processed
- To update statistics
- To regenerate thumbnails

### 3. Apply Symbology

**Tool:** `Apply Symbology`

Applies standard ALARM symbology to selected layers in the current map.

**Parameters:**
- **Layer**: Select layer from current map
- **Layer Type**: PPR Raster, Tracks, PRAs, or Risk Assessment

**What it does:**
- Detects layer type automatically (if possible)
- Applies predefined symbology
- Updates layer in current map

## Symbology Reference

### PPR Raster (Peak Pressure)
- **≤ 1 kPa**: Transparent
- **1-10 kPa**: Light blue (#b0f4fa)
- **10-25 kPa**: Green (#75c165)
- **25-50 kPa**: Orange (#a96c00)
- **> 50 kPa**: Dark purple (#8b0069)
- **Opacity**: 70%

### Tracks (Avalanche Paths)
- **Field**: `med_pres` (median pressure)
- **Scale**: Logarithmic blue gradient
  - **25-50 kPa**: #e0f3ff
  - **50-100 kPa**: #99d6ff
  - **100-200 kPa**: #4da6ff
  - **200-400 kPa**: #0066cc
  - **> 400 kPa**: #003d7a
- **Opacity**: 90%

### PRAs (Potential Release Areas)
- **Outline**: Black (1.5 pt)
- **Fill**: None
- **Opacity**: 100%

### Risk Assessment (Buildings)
- **Field**: `max_ppr` (maximum pressure on building)
- **Scale**: Magenta/pink gradient
  - **0-25 kPa**: #ffb3d9
  - **25-50 kPa**: #ff66b3
  - **50-100 kPa**: #ff0080
  - **100-200 kPa**: #cc0066
  - **> 200 kPa**: #990050
- **Opacity**: 100%

## Data Structure

Expected data location: `L:\ALARM\Results\`

```
L:\ALARM\Results\
├── Finnmarkskysten\
│   ├── merged\
│   │   ├── A_80-60_prox0_rel1.2m\
│   │   │   ├── ppr_Finnmarkskysten_A_80-60_prox0_rel1.2m_max.tif
│   │   │   ├── tracks_Finnmarkskysten_A_80-60_prox0_rel1.2m.shp
│   │   │   ├── pra_Finnmarkskysten_A_80-60_prox0_rel1.2m.shp
│   │   │   └── risk_assessment\
│   │   │       ├── risk_Finnmarkskysten_A_80-60_prox0_rel1.2m.shp
│   │   │       ├── risk_assessment_Finnmarkskysten_A_80-60_prox0_rel1.2m.csv
│   │   │       └── risk_assessment_Finnmarkskysten_A_80-60_prox0_rel1.2m.xlsx
│   │   ├── B_80-60_prox0_rel1.8m\
│   │   ├── C_80-60_prox100_rel2.3m\
│   │   ├── D_75-55_prox0_rel2.3m\
│   │   └── E_75-55_prox150_rel2.3m\
│   └── _REGION_COMPLETE.marker
├── Oslo\
└── ...
```

## Configuration

The toolbox uses these default paths:
- **Results Base**: `L:\ALARM\Results`
- **Overview Output**: `L:\ALARM\ALARM_Overview`

To change these, edit the configuration section in `ALARM_Tools.pyt`:

```python
# Configuration
self.results_base = Path(r"L:\ALARM\Results")
self.overview_output = Path(r"L:\ALARM\ALARM_Overview")
```

## Scenarios

The ALARM pipeline processes 5 scenarios per region:

| ID | Name | Description |
|----|------|-------------|
| A | 80-60_prox0_rel1.2m | High thresholds, no proximity, 1.2m release |
| B | 80-60_prox0_rel1.8m | High thresholds, no proximity, 1.8m release |
| C | 80-60_prox100_rel2.3m | High thresholds, 100m proximity, 2.3m release |
| D | 75-55_prox0_rel2.3m | Medium thresholds, no proximity, 2.3m release |
| E | 75-55_prox150_rel2.3m | Medium thresholds, 150m proximity, 2.3m release |

## Troubleshooting

### "No regions found"
- Check that `L:\ALARM\Results` exists and contains region folders
- Ensure regions have a `merged` folder with data
- Verify network drive `L:` is accessible

### "Failed to load layer"
- Check that all shapefile components exist (.shp, .shx, .dbf, .prj)
- Verify file paths don't contain special characters
- Ensure you have read permissions for the data directory

### "Symbology not applied"
- Check that layer type matches selected symbology
- Verify field names exist in the attribute table
- Try manually applying symbology from Layer Properties

## Requirements

- **ArcGIS Pro** 2.8 or later
- **Python** 3.7+ (included with ArcGIS Pro)
- **Network access** to `L:\ALARM\Results`

## Contributing

This is an open-source tool developed for the ALARM project. Contributions are welcome!

## License

MIT License - See LICENSE file for details

## Authors

- ALARM Project Team
- Norwegian Water Resources and Energy Directorate (NVE)

## Related Projects

- **ALARM Pipeline**: Main processing pipeline (private repository)
- **AvaFrame**: Avalanche simulation framework

## Support

For questions or issues:
- Open an issue on GitHub
- Contact: [Your contact information]

---

**Version**: 1.0.0  
**Last Updated**: April 2026
