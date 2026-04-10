# ALARM ArcGIS Tools

ArcGIS Pro Python Toolbox for working with ALARM (Avalanche Risk Assessment) pipeline results.

## Overview

This toolbox provides easy access to ALARM pipeline outputs directly within ArcGIS Pro, with automatic symbology application, advanced filtering, data export, reporting, and scenario comparison tools.

**Features:**
- **Load ALARM Data**: Load region/scenario data with automatic symbology
- **Filter Layers**: Apply advanced filters to Tracks, PRAs, and Risk Assessment layers
- **Export Filtered Data**: Export filtered layers as new shapefiles
- **Generate Report**: Create detailed statistics reports for Risk Assessment data
- **Compare Scenarios**: Visual comparison of two scenarios using Swipe or Side-by-Side views
- **Update Overview**: Regenerate HTML overview page

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
- **Region**: Select from available regions (e.g., Vest_Finnmark, Nord_Troms)
- **Scenario**: Select scenario (A, B, C, D, E)
- **Data Types**: Choose which layers to load (PPR Raster, Tracks, PRAs, Risk Assessment)
- **Add to Group Layer**: Organize layers in a group (default: Yes)

**What it does:**
- Finds data in `L:\ALARM\Results\{region}\merged\{scenario}\`
- Loads selected layers into current map
- Applies standard ALARM symbology automatically
- Adds spatial index for performance optimization

**Example:**
```
Region: Vest_Finnmark
Scenario: D
Data Types: Tracks, Risk Assessment
→ Loads 2 layers with correct symbology in a group
```

### 2. Filter Layers

**Tool:** `Filter Layers`

Apply advanced filters to loaded layers based on elevation, aspect, safety class, and pressure.

**Note:** PRAs must be loaded via the **Load ALARM Data** tool (which automatically converts them to File Geodatabase format with proper numeric field types). PRAs loaded directly as shapefiles cannot be filtered.

**Parameters:**
- **Layers to Filter**: Multi-select (Tracks, PRAs, Risk Assessment)
- **Elevation**: Min/Max range (meters)
- **Aspect Filter Type**: None, Cardinal Directions, or Degree Range
  - **Cardinal Directions**: Multi-select (N, NE, E, SE, S, SW, W, NW)
  - **Degree Range**: Min/Max (0-360°)
- **Building Safety Class** (Risk Assessment only): S1, S2, S3, S4
- **Minimum Max PPR** (Risk Assessment only): Threshold in kPa

**What it does:**
- Applies SQL definition queries to selected layers
- Uses correct field names per layer type (Tracks: `pra_elev`/`pra_aspdeg`, PRAs: `elev_med`/`aspect_deg`, Risk Assessment: `pra_elev`)
- Filters are cumulative (AND logic)
- Shows applied query and feature counts in messages

**Example:**
```
Layers: Risk Assessment
Elevation: 500-1500m
Safety Class: S3, S4
Min Max PPR: 25 kPa
→ Shows only high-risk buildings (S3/S4) between 500-1500m with PPR ≥ 25 kPa
```

### 3. Export Filtered Data

**Tool:** `Export Filtered Data`

Export filtered layers to new shapefiles for further analysis.

**Parameters:**
- **Layer to Export**: Select from current map
- **Output Directory**: Where to save the shapefile
- **Output Filename** (optional): Custom name (auto-generated if empty)

**What it does:**
- Exports only visible/filtered features (respects `definitionQuery`)
- Auto-generates filename with timestamp if not specified
- Reports number of exported features

**Example:**
```
Layer: risk_Vest_Finnmark_D (filtered to S3/S4)
Output: C:\Users\...\exports\
Filename: high_risk_buildings.shp
→ Exports 47 features to high_risk_buildings.shp
```

### 4. Generate Report

**Tool:** `Generate Report`

Generate detailed statistics report for Risk Assessment layer.

**Parameters:**
- **Risk Assessment Layer**: Select from current map
- **Output Directory**: Where to save the report
- **Report Format**: HTML, CSV, or Both

**What it does:**
- Analyzes all features (or filtered subset)
- Generates statistics:
  - Total building count
  - Distribution by Safety Class (S1, S2, S3, S4)
  - Distribution by PPR categories (0-25, 25-50, 50-100, 100-200, >200 kPa)
  - Distribution by Elevation ranges (<500m, 500-1000m, 1000-1500m, 1500-2000m, >2000m)
  - Distribution by Aspect (N, NE, E, SE, S, SW, W, NW)
  - Min/Max/Average PPR values
- Creates formatted HTML report with tables and percentages
- Optional CSV export for further analysis

**Example:**
```
Layer: risk_Vest_Finnmark_D
Format: HTML
→ Creates risk_report_20260409_123045.html with full statistics
```

### 5. Compare Scenarios

**Tool:** `Compare Scenarios`

Visually compare two scenarios using Swipe or Side-by-Side views.

**Parameters:**
- **Comparison Mode**: Swipe Tool or Side-by-Side Maps
- **Layer 1** (Left/Top): First scenario layer
- **Layer 2** (Right/Bottom): Second scenario layer

**What it does:**

**Swipe Tool Mode:**
- Makes both layers visible
- Provides instructions for activating ArcGIS Pro Swipe tool
- Synchronizes extent to Layer 1
- Allows interactive comparison with draggable swipe line

**Side-by-Side Mode:**
- Makes both layers visible
- Provides detailed instructions for Layout setup
- Guides user through creating two synchronized map frames

**Example:**
```
Mode: Swipe Tool
Layer 1: tracks_Vest_Finnmark_D
Layer 2: tracks_Vest_Finnmark_E
→ Prepares layers for swipe comparison
→ Follow on-screen instructions to activate Swipe tool
```

### 6. Update Overview

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
