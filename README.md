# ALARM ArcGIS Tools

ArcGIS Pro Python Toolbox for working with ALARM (Avalanche Risk Assessment) pipeline results.

## Overview

This toolbox provides easy access to ALARM pipeline outputs directly within ArcGIS Pro, with automatic symbology application, advanced filtering, data export, reporting, and scenario comparison tools.

**Features:**
- **Load ALARM Data**: Load region/scenario data with automatic symbology
- **Filter Layers**: Apply advanced filters to Tracks, PRAs, and Risk Assessment layers
- **Generate Report**: Create detailed statistics reports for Risk Assessment data
- **Export Filtered Data**: Export filtered layers as new shapefiles
- **Compare Scenarios**: Side-by-side table of all scenarios of a region with one shared filter

## Installation

### Method 1: Direct Download (Recommended)

1. Download this repository as ZIP or clone it:
   ```bash
   git clone https://github.com/LeonieKom/ALARM_ArcGIS_Tools.git
   ```

2. Open ArcGIS Pro

3. Add the toolbox:
   - **Catalog Pane** → **Toolboxes** → Right-click → **Add Toolbox**
   - Navigate to `ALARM_Tools.pyt` (keep the `alarm_core` folder next to it)
   - Click **OK**

4. The toolbox will appear under "Toolboxes" in the Catalog pane

### Method 2: Add to Favorites

For permanent access:
1. Right-click on the added toolbox
2. Select **Add To Favorites**

## Quick Start

### 1. Load ALARM Data

**Tool:** `Load ALARM Data`

Loads data for forecast regions or for municipalities, with automatic symbology.

**Parameters:**
- **Data Source**: where the data come from: the standard results (`L:\ALARM\Results`), the **ALARM2.2** test runs (`L:\ALARM\ALARM2.2`), or **Other folder...** (then choose the **Data Folder**, the one that contains the region folders). The region and scenario lists follow the choice. More sources can be added in the config (see [Configuration](#configuration)).
- **Load by**: *Forecast regions (Varslingsregioner)* as before, or *Municipalities (Kommuner)* (see below)
- **Regions**: one or several regions (e.g., Vest_Finnmark, Nord_Troms); in region mode
- **Municipalities (Kommuner)**: one or several municipalities; in municipality mode
- **Scenarios**: one or several scenarios (A, B, C, D, E). For other data sources the list shows what the selected regions contain; a single-scenario run without scenario id appears as `single`.
  - Every selected region is combined with every selected scenario; each combination gets its own group layer. A combination without data is skipped with a warning.
- **Data Types**: Choose which layers to load (PPR Raster, PFV Raster, PFT Raster, Tracks, PRAs, Risk Assessment). PFV/PFT use the `.lyrx` next to the raster.
- **Add to Group Layer**: Organize layers in a group (default: Yes)

**Municipality mode** - work with a municipality without caring about forecast regions:
- The tool finds the forecast regions whose results reach into the selected municipalities, keeps from each of them only what lies (at least partly) inside, and merges the regions: per scenario you get one layer each, e.g. `tracks - Tromsø - D`, `pra - Tromsø - D`, `risk - Tromsø - D`, in the group `Tromsø - Scenario D`. A field `alarm_region` says which region a feature came from
- A building that is in two regions (neighbouring regions overlap) is kept once, with its highest max PPR
- Rasters are not cut: each region's raster is loaded whole (one layer per region, e.g. `ppr - 2_Tromso - D`); the boundary layer shows the municipality. Cutting read the full raster over the network and took about a minute per raster
- The **boundaries** of the selected municipalities are drawn as their own layer (`Kommune: Tromsø`, dark red outline)
- The cut-outs are stored in the project geodatabase and reused as long as the result files are unchanged, so loading the same municipality again is fast. The first time, the spatial selection on the large region layers takes a while (faster with optimized copies)

**What it does (region mode):**
- Finds data in `<data folder>\{region}\merged\{scenario}\` (or directly in `merged\` for a single-scenario run, see [Data Structure](#data-structure))
- Layers and groups from a data source other than the standard results carry its name, e.g. `1_Lyngen - Scenario single [ALARM2_2]`, so two sources can be loaded side by side
- Loads selected layers into current map
- Applies standard ALARM symbology automatically
- Loads from the **optimized copies** in `L:\ALARM\Results_optimized\` when they are up to date (see [Optimized copies](#optimized-copies)); otherwise from the original files
- Without an optimized copy, converts PRAs to a geodatabase feature class with numeric fields; the copy is cached in the project geodatabase, so the first load of a large region takes about a minute and later loads are instant

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
- **Layers to Filter**: Pick one or more layers from the map (type is detected from the fields: Tracks, PRAs, Risk Assessment)
- **Municipalities (Kommuner)**: tick one or several municipalities, e.g. *Tromsø (5501)*. The list shows the municipalities that the chosen layers touch. A track, PRA or building counts as "in" a municipality when it lies at least partly inside. Combines with all other criteria and with refining; Export and Report take it over automatically
- **Elevation**: Min/Max range (meters)
- **Aspect Filter Type**: None, Cardinal Directions, or Degree Range
  - **Cardinal Directions**: Multi-select (N, NE, E, SE, S, SW, W, NW)
  - **Degree Range**: Min/Max (0-360°)
- **Building Safety Class** (Risk Assessment only): S1, S2, S3, S4
- **Minimum Max PPR** (Risk Assessment only): Threshold in kPa

**What it does:**
- Applies SQL definition queries to selected layers
- Uses correct field names per layer type (Tracks: `pra_elev`/`pra_aspdeg`, PRAs: `elev_med`/`aspect_deg`, Risk Assessment: `pra_elev`)
- Tracks of several PRAs released together (`n_pras` > 1, proximity scenarios) pass when **any** member PRA matches: its elevation range (`elev_lo`-`elev_hi`) overlaps the filter and one of its aspect classes (`asp_set`, e.g. `,S,SW,`) is selected. A degree range is applied to these tracks at the resolution of the eight aspect classes. Results without these fields are filtered on the track's own PRA as before
- Criteria within one run are combined with AND
- **Filter Mode** controls what happens to a filter that is already on the layer:
  - *Refine existing filter* (default): the new criteria are added with AND, so you can filter step by step (e.g. first elevation, then aspect, then safety class)
  - *Replace existing filter*: the old filter is discarded
  - *Reset filter*: removes the filter from the selected layers
- With refinement the messages show total / before / now feature counts
- Every filter gets a readable name (e.g. `ALARM: Kommune Tromsø; >= 300 m; N/NE`), shown in *Layer Properties > Definition Query* and in the report. A municipality filter is stored as a list of object IDs (ranges where possible), so the SQL itself is long
- The first time a municipality is used, its boundary is read from `L:\ALARM\BaseData\Basisdata_0000_Norge_25833_Kommuner_FGDB.gdb` and kept in `%LOCALAPPDATA%\ALARM_Tools\kommuner\` (until the dataset changes). Finding the features inside takes a few seconds per large layer
- **Show feature counts** can be switched off: counting reads each layer completely and takes seconds per large layer on `L:` (about 16 s for three Vest_Finnmark layers vs. 0.2 s without)
- Aspect on Risk Assessment works with Cardinal Directions (matched against `pra_aspct`); a degree range is not available there
- Shows applied query and feature counts (before -> after) in messages

**Example:**
```
Layers: Risk Assessment
Elevation: 500-1500m
Safety Class: S3, S4
Min Max PPR: 25 kPa
→ Shows only high-risk buildings (S3/S4) between 500-1500m with PPR ≥ 25 kPa
```

### 3. Generate Report

**Tool:** `Generate Report`

Generate a detailed statistics report for one or several Risk Assessment layers.

**Parameters:**
- **Risk Assessment Layers**: one or several from the current map, e.g. the risk layers of all forecast regions a municipality lies in. Tracks and PRA layers chosen here as well are drawn on the map (layers of the same group are drawn anyway); other layers are not used. The dialog says before the run how each chosen layer is used. They are combined; a building in more than one layer (same `bld_id`) is counted once, with its highest max PPR, and the report says how many there were
- **Output Directory**: Where to save the report
- **Report Format**: HTML, CSV, or Both
- **Include map**: an interactive map in the HTML report (default: yes)
- **Look up addresses and area names**: from Kartverket's open APIs (ws.geonorge.no, needs internet; default: yes). The answers are cached in `%LOCALAPPDATA%\ALARM_Tools\kartverket`, so a building or area is only looked up once. Without internet the report is written without addresses

**What it does:**
- **Scenario** at the top: the scenario parameters (PRA thresholds, proximity, release thickness; from the file names, or from the scenario list in the config) and the **avalanche problem as in Varsom**: the aspect rose and the elevation triangle, red where the release areas are. They follow the layer's filter (Filter Layers): no filter = all aspects red, all elevations
- **Exposed buildings by pressure**: a table of the buildings, highest max PPR first, with nearest address ("near" = more than 30 m away), area, max PPR, aspect of the release areas (with a small rose) and their elevation (from `pra_asplst` / `pra_elvls`: all PRAs reaching the building). S1 buildings are hidden until ticked. The CSV report has the same list with all buildings. Addresses are looked up for at most 2000 buildings (S3, S2 first)
- **Area names**: each affected area is named after the nearest settlement-like place name (Kartverket place names), else its postal place; equal names get the most common street, then II, III. The name is shown under each small map ("Area 1: Name"), in the priority table and in the building table
- Analyzes all features (or filtered subset)
- Generates statistics:
  - Total building count
  - Distribution by Safety Class (S1, S2, S3, S4)
  - Distribution by PPR categories (0-25, 25-50, 50-100, 100-200, >200 kPa)
  - Distribution by Elevation ranges (<500m, 500-1000m, 1000-1500m, 1500-2000m, >2000m)
  - Distribution by Aspect (N, NE, E, SE, S, SW, W, NW)
  - Min/Max/Average PPR values
- Creates formatted HTML report with tables and percentages; it names the layer, its filter (readable name and SQL) and a selection, if any
- **Map** (HTML): all buildings of the report on a Kartverket background map (OpenStreetMap as alternative), coloured by max PPR like the layer; click a building for its values. As background: the avalanche tracks (very light blue) and PRAs (thin black outline) of the same group(s) as the risk layers, within 1 km of the buildings, and municipality boundaries (`Kommune: ...` layers). Buildings closer than 500 m to each other form an *affected area*: a priority table lists the areas, highest max PPR first, with a *Zoom* button, and the first 12 get their own small map. All maps can be zoomed and moved. Opening the report needs internet access for the map (Leaflet and the background tiles); the tables work without it
- Optional CSV export for further analysis

**Example:**
```
Layer: risk_Vest_Finnmark_D
Format: HTML
→ Creates risk_report_20260409_123045.html with full statistics
```

### 4. Export Filtered Data

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
-> Exports 47 features to high_risk_buildings.shp
```

### 5. Compare Scenarios

**Tool:** `Compare Scenarios`

Compares the scenarios of one region side by side with **one shared filter**. It does not need loaded layers; the attribute tables are read directly from the result files.

**Parameters:**
- **Data Source** (and **Data Folder**), **Region** and **Scenarios to Compare** (default: all scenarios the source has for the region)
- **Municipalities (Kommuner)**: count only what lies (at least partly) in these municipalities; "total" then means the total in the municipalities. Needs a spatial selection per file, so it takes longer than the attribute criteria
- The same criteria as in *Filter Layers*: elevation, aspect (cardinal directions or degree range), building safety class, minimum max PPR
- **Output Directory** and **Report Format** (HTML, CSV or both)

**What you get** (one column per scenario):
- Avalanche tracks, PRAs and buildings in the risk assessment: filtered / total (the buildings listed in the scenario's risk assessment, not all buildings of the region)
- Buildings by safety class and by max PPR class (filtered)
- Highest and mean max PPR (`max_ppr`) of the filtered buildings
- The applied filter is written at the top of the HTML report

**Notes:**
- Safety class and PPR only apply to buildings; tracks and PRAs are filtered by elevation and aspect.
- A degree range is not available for buildings (their aspect is stored as N/NE/...); use cardinal directions there.
- The numbers are identical to what *Filter Layers* shows on the loaded layers (checked in the tests).
- Reading five scenarios of a large region takes about a minute (the PRA tables are big).

## Symbology Reference

### PPR / PFV / PFT Rasters
Styled from the `.lyrx` file the pipeline writes next to each raster (single source of truth), e.g.
`ppr_<region>_<scenario>_max.lyrx`. PPR classes: < 1, 1-3, 3-10, 10-20, 20-30, 30-60, > 60 kPa.
If the `.lyrx` is missing, PPR falls back to a built-in scale (breaks 0.1, 1, 10, 25, 50 kPa; below 0.1 kPa transparent).

### Tracks (Avalanche Paths)
- **Field**: `med_pres` (median pressure)
- **Scale**: five blue classes, light to dark: 0-50, 50-100, 100-200, 200-500, > 500 kPa
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

**Single-scenario runs** (pipeline quick settings, e.g. the `ALARM2.2` test runs) have no scenario folders: all files are written directly into `merged\`, and the risk assessment shapefile is named like its tables:

```
L:\ALARM\ALARM2.2\1_Lyngen\merged\
├── ppr_1_Lyngen_80-60_prox0_rel1_2m_max.tif            (also ..._max_clipped.tif: cut to the region polygon, not loaded)
├── tracks_1_Lyngen_80-60_prox0_rel1_2m.shp
├── pra_1_Lyngen_80-60_prox0_rel1_2m.shp
└── risk_assessment\risk_assessment_1_Lyngen_80-60_prox0_rel1_2m.shp
```

The file names carry the scenario id only if one was set (`..._1_Lyngen_A_80-60_...`); without it the toolbox calls the run `single`. Where a scenario folder and flat files both exist, the folder wins.

Note on file names: newer pipeline runs write result files without dots (`..._rel2_3m.shp`, folder names keep them), because ArcPy cannot resolve shapefile paths containing a dot. Older results still use `rel2.3m` in file names. The toolbox handles both (it loads files via map layers and finds them with wildcards).

## Configuration

By default the toolbox reads the results from `L:\ALARM\Results` and knows scenarios A-E. To change this **without editing code**:

- copy `alarm_tools_config.example.json` to `alarm_tools_config.json` (next to `ALARM_Tools.pyt`) and edit it, or
- set the environment variable `ALARM_RESULTS_BASE`.

The data sources offered in the tools ("Data Source") are the standard results plus `ALARM2.2`; add your own or remove one in the same file (an empty path removes a default source):

```json
"sources": {"My run": "D:\\ALARM\\run1", "ALARM2.2": ""}
```

The municipality boundaries come from `kommune_gdb` (default `L:\ALARM\BaseData\Basisdata_0000_Norge_25833_Kommuner_FGDB.gdb`, feature class `kommune`), or `ALARM_KOMMUNE_GDB`. The municipality list in the dialogs comes with the toolbox (`alarm_core/kommuner.json`: number, official names and bounding box of the 357 municipalities, made from the same Kartverket dataset, CC BY 4.0), so the dialogs never wait for `L:`. After a municipality reform it has to be regenerated.

The environment variable wins over the JSON file, which wins over the defaults. A broken JSON file is reported with its file name. `alarm_tools_config.json` is not tracked by git.

### Optimized copies

The shapefiles on `L:` have no spatial index and the rasters are not optimized for reading over the network, so panning and zooming are slow. `tools/optimize_results.py` in the pipeline repository writes fast copies into a separate folder (default `L:\ALARM\Results_optimized\`, same `region\scenario\` layout); the originals are never changed:

- rasters as Cloud-Optimized GeoTIFF (lossless, checked pixel by pixel, overviews and statistics inside the file; the `.lyrx` is copied along)
- shapefiles as GeoPackage with a spatial index, same field names; the PRA numbers stored as text in the shapefile are real numbers, so PRAs need no geodatabase conversion

Load ALARM Data uses a copy only while the original is unchanged (size and modification time of the `.tif`, or of `.shp` and `.dbf`, are recorded in `_sources.json`). After a re-merge or an attribute patch it loads the original again until the copy is rebuilt, and says so in the messages. Filter and Report work on the loaded layers as before; Compare Scenarios keeps reading the original `.dbf` files. ArcGIS Pro cannot export GeoPackage layers (64-bit object IDs) to shapefiles with its own tools, so Export Filtered Data copies such layers row by row; filter and selection apply as usual.

`optimized_base` in `alarm_tools_config.json` or the environment variable `ALARM_OPTIMIZED_BASE` points to another folder; an empty value switches the copies off.

## Project layout

```
ALARM_Tools.pyt        the toolbox: parameters, messages, map handling (needs arcpy)
alarm_core/            everything that does not need arcpy
    config.py          results folder and scenarios
    data.py            finding regions, scenario folders and files
    dbf.py             .dbf reader
    filters.py         filter criteria: SQL for the layers + the same logic in Python
    compare.py         scenario comparison and its HTML/CSV tables
    report.py          statistics report for a Risk Assessment layer
    kommune.py         municipalities: labels, the object-ID SQL, the bundled list kommuner.json
    webmap.py          the interactive map of the HTML report (Leaflet)
tests/                 pytest
alarm_tools_config.example.json
```

Keep the `alarm_core` folder next to `ALARM_Tools.pyt`. After editing code, use *Refresh* on the toolbox in the Catalog pane; the `alarm_core` modules are reloaded then (restart Pro if a change does not show up).

## Development

Run the tests with ArcGIS Pro's Python:

```
"C:\Program Files\ArcGIS\Pro\bin\Python\Scripts\propy.bat" -m pytest tests
```

- Without anything else, 167 tests run that do not need arcpy or the results (the SQL built for the layers is checked against the Python filter logic with sqlite).
- `tests/test_arcpy_sources.py` (data source switch, single-scenario runs) needs only arcpy and a project file (`ALARM_TEST_APRX`): it creates tiny shapefiles in the layout of a single-scenario run. Two of its tests also use the real `L:\ALARM\ALARM2.2` folder when it is reachable.
- The integration tests (loading, filtering, report, export, comparison) additionally need the results on `L:` and a project file with a map: set `ALARM_TEST_APRX` to any `.aprx`; it is copied to a temporary folder. Optional: `ALARM_TEST_REGION` (default `02_Vest_Finnmark`) and `ALARM_TEST_SCENARIO` (default `D`). They take about three minutes for a large region, mostly the first PRA conversion.
- If optimized copies of that scenario exist, the integration tests load from them. Run them a second time with `ALARM_OPTIMIZED_BASE` set to an empty value to cover loading from the originals.
- On GitHub, `.github/workflows/tests.yml` runs the tests without arcpy on every push (Windows and Linux, Python 3.9 and 3.11).
- A filter change must be made in `alarm_core/filters.py` once; the SQL builders and the Python predicates live side by side there, and `test_filters.py` fails if they disagree.

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

### "No module named 'alarm_core'"
- The `alarm_core` folder must be next to `ALARM_Tools.pyt` (copy both, not only the .pyt)

### Changes to the code do not show up
- Right-click the toolbox in the Catalog pane -> *Refresh*; if that is not enough, restart ArcGIS Pro

### The map in the HTML report stays empty
- The map loads Leaflet from unpkg.com and the background from cache.kartverket.no; without internet access only the tables are shown. Open the report in a current browser (Edge, Chrome, Firefox)

### "Symbology not applied"
- Check that layer type matches selected symbology
- Verify field names exist in the attribute table
- Try manually applying symbology from Layer Properties

## Requirements

- **ArcGIS Pro** 3.0 or later (uses `ExportFeatures`, available since 3.0; tested with 3.5)
- **Python** 3.9+ (included with ArcGIS Pro 3.x)
- **Network access** to `L:\ALARM\Results` (and to `L:\ALARM\BaseData` for municipality boundaries)
- **Internet access** to view the map in the HTML report

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

---

**Version**: 2.0.0  
**Last Updated**: October 2026
