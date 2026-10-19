"""
ALARM Tools - ArcGIS Pro Python Toolbox
========================================
Tools for loading and managing ALARM regional avalanche data.

Tools:
1. Load ALARM Data - Load specific region and scenario into current map
2. Filter Layers - Filter Tracks / PRAs / Risk Assessment by elevation, aspect, safety class, PPR
3. Generate Report - Statistics report (HTML/CSV) for a Risk Assessment layer
4. Export Filtered Data - Export a (filtered) layer
5. Compare Scenarios - Compare the scenarios of a region with one shared filter

Author: ALARM Pipeline
Date: 2026-04-07
"""

import arcpy
import importlib
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# The logic that does not need arcpy lives in the alarm_core package next to this file.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import alarm_core.config as _config
import alarm_core.data as _data
import alarm_core.dbf as _dbf
import alarm_core.filters as _filters
import alarm_core.compare as _compare
import alarm_core.report as _report

# ArcGIS Pro keeps imported modules for the whole session. Reloading them here makes
# "Refresh" of the toolbox pick up edits without restarting Pro.
for _module in (_config, _data, _dbf, _filters, _compare, _report):
    importlib.reload(_module)


def _selection_count(layer):
    """Number of selected features of a map layer (0 if none or not determinable).

    Counting, exporting and reading a layer only use the selected features while a
    selection exists, so the tools point this out.
    """
    try:
        selection = layer.getSelectionSet()
    except Exception:
        return 0
    return len(selection) if selection else 0


# Parameter index of each filter criterion in the two tools that use the criteria
_FILTER_PARAMS = dict(any=0, elev_min=1, elev_max=2, aspect_type=3, cardinal=4, aspect_min=5, aspect_max=6,
                      saf_classes=7, min_max_ppr=8)
_COMPARE_PARAMS = dict(elev_min=2, elev_max=3, aspect_type=4, cardinal=5, aspect_min=6, aspect_max=7,
                       saf_classes=8, min_max_ppr=9)


def _criteria_from(parameters, index):
    """Filter criteria from the tool parameters (index: criteria key -> parameter position)."""
    def p(key):
        return parameters[index[key]]
    return _filters.make_criteria(
        elev_min=p('elev_min').value,
        elev_max=p('elev_max').value,
        aspect_type=p('aspect_type').valueAsText if p('aspect_type').value else _filters.ASPECT_NONE,
        cardinal=_split_values(p('cardinal').valueAsText),
        aspect_min=p('aspect_min').value,
        aspect_max=p('aspect_max').value,
        saf_classes=_split_values(p('saf_classes').valueAsText),
        min_max_ppr=p('min_max_ppr').value)


def _show_validation(parameters, index, require_any=False):
    """Show problems with the criteria at the affected parameters (in updateMessages)."""
    for key, level, message in _filters.validate(_criteria_from(parameters, index), require_any):
        if key not in index:
            continue
        param = parameters[index[key]]
        if level == "error":
            param.setErrorMessage(message)
        else:
            param.setWarningMessage(message)


def _check_region(param):
    """The region list shows 'No regions found' when the results folder is not reachable."""
    if param.valueAsText == "No regions found":
        param.setErrorMessage("No regions found - is the results folder (L:) reachable? See alarm_core/config.py.")


def _split_values(text):
    """Values of a multi-value parameter (valueAsText is 'a;b;c', values may be quoted)."""
    if not text:
        return []
    return [v.strip().strip("'\"") for v in text.split(';') if v.strip()]




class Toolbox(object):
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the .pyt file)."""
        self.label = "ALARM Tools v2"
        self.alias = "ALARM"
        self.description = "Tools for loading and managing ALARM regional avalanche data"

        # List of tool classes associated with this toolbox
        self.tools = [LoadALARMData, FilterLayers, GenerateReport, ExportFilteredData, CompareScenarios]


class LoadALARMData(object):
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "1. Load ALARM Data"
        self.description = "Load ALARM data for a specific region and scenario into the current map"
        self.canRunInBackground = False

        # Configuration (see alarm_core/config.py; can be overridden in alarm_tools_config.json)
        cfg = _config.load_config()
        self.results_base = cfg['results_base']
        self.scenarios = cfg['scenarios']

    def getParameterInfo(self):
        """Define parameter definitions"""

        # Parameter 0: Region
        param0 = arcpy.Parameter(
            displayName="Region",
            name="region",
            datatype="GPString",
            parameterType="Required",
            direction="Input")

        # Get list of completed regions
        regions = self._get_completed_regions()
        param0.filter.type = "ValueList"
        param0.filter.list = regions if regions else ["No regions found"]

        # Parameter 1: Scenario
        param1 = arcpy.Parameter(
            displayName="Scenario",
            name="scenario",
            datatype="GPString",
            parameterType="Required",
            direction="Input")

        param1.filter.type = "ValueList"
        param1.filter.list = [f"{k} - {v}" for k, v in self.scenarios.items()]

        # Parameter 2: Data types to load
        param2 = arcpy.Parameter(
            displayName="Data to Load",
            name="data_types",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True)

        param2.filter.type = "ValueList"
        param2.filter.list = ["PPR Raster", "PFV Raster", "PFT Raster", "Tracks", "PRAs", "Risk Assessment"]
        param2.value = ["PPR Raster", "Tracks", "PRAs", "Risk Assessment"]

        # Parameter 3: Add to group layer
        param3 = arcpy.Parameter(
            displayName="Add to Group Layer",
            name="use_group",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input")

        param3.value = True

        return [param0, param1, param2, param3]

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal
        validation is performed."""
        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter."""
        _check_region(parameters[0])
        return

    def execute(self, parameters, messages):
        """The source code of the tool."""

        # Get parameters
        region = parameters[0].valueAsText
        scenario_full = parameters[1].valueAsText
        scenario_id = scenario_full.split(' - ')[0]  # Extract 'A' from 'A - (80-60, prox0, rel1.2m)'
        # Strip quotes and whitespace from data types
        data_types = _split_values(parameters[2].valueAsText)
        use_group = parameters[3].value

        arcpy.AddMessage(f"Loading data for {region}, Scenario {scenario_id}")
        arcpy.AddMessage(f"Data types to load: {data_types}")

        # Find scenario directory
        scenario_dir = self._find_scenario_dir(region, scenario_id)
        if not scenario_dir:
            arcpy.AddError(f"Could not find data for {region}, Scenario {scenario_id}")
            return

        arcpy.AddMessage(f"Found data directory: {scenario_dir}")

        # Get current map
        aprx = arcpy.mp.ArcGISProject("CURRENT")
        map_obj = aprx.activeMap

        if not map_obj:
            arcpy.AddError("No active map found. Please open a map in ArcGIS Pro.")
            return

        layers_added = []

        # Load PPR Raster
        if "PPR Raster" in data_types:
            ppr_file = self._find_file(scenario_dir, "ppr_*.tif")
            if ppr_file and self._already_loaded(map_obj, ppr_file):
                pass
            elif ppr_file:
                arcpy.AddMessage(f"Loading PPR raster: {ppr_file.name}")
                layer = map_obj.addDataFromPath(str(ppr_file))
                # The pipeline's .lyrx is the single source of truth for PPR colors;
                # the built-in symbology is only the fallback if it is missing.
                ppr_lyrx = ppr_file.with_suffix(".lyrx")
                if ppr_lyrx.exists():
                    self._apply_lyrx(layer, ppr_lyrx)
                else:
                    arcpy.AddWarning(f"  No layer file ({ppr_lyrx.name}) - using built-in PPR symbology")
                    self._apply_ppr_symbology(layer)
                layers_added.append(layer)
            else:
                arcpy.AddWarning("PPR raster not found")

        # Load PFV (flow velocity) and PFT (flow thickness) rasters.
        # The pipeline writes a matching .lyrx next to each raster; use it for the styling.
        for label, prefix in (("PFV Raster", "pfv"), ("PFT Raster", "pft")):
            if label in data_types:
                raster_file = self._find_file(scenario_dir, f"{prefix}_*.tif")
                if raster_file and self._already_loaded(map_obj, raster_file):
                    pass
                elif raster_file:
                    arcpy.AddMessage(f"Loading {label}: {raster_file.name}")
                    layer = map_obj.addDataFromPath(str(raster_file))
                    self._apply_lyrx(layer, raster_file.with_suffix(".lyrx"))
                    layers_added.append(layer)
                else:
                    arcpy.AddWarning(f"{label} not found")

        # Load Tracks
        if "Tracks" in data_types:
            tracks_file = self._find_file(scenario_dir, "tracks_*.shp")
            if tracks_file and self._already_loaded(map_obj, tracks_file):
                pass
            elif tracks_file:
                arcpy.AddMessage(f"Loading tracks: {tracks_file.name}")
                layer = map_obj.addDataFromPath(str(tracks_file))
                self._apply_tracks_symbology(layer)
                layers_added.append(layer)
            else:
                arcpy.AddWarning("Tracks shapefile not found")

        # Load PRAs - Convert to File Geodatabase to fix String field types
        if "PRAs" in data_types:
            pra_file = self._find_file(scenario_dir, "pra_*.shp")
            if pra_file:
                arcpy.AddMessage(f"Loading PRAs: {pra_file.name}")
                gdb_path = aprx.defaultGeodatabase

                # The converted copy is cached in the project geodatabase. The name carries
                # the modification time and size of the shapefile, so the cache is reused
                # as long as the source is unchanged and rebuilt automatically when it changes.
                # (GDB names must not contain - or .)
                base_name = re.sub(r"[^0-9A-Za-z_]", "_", f"pra_{region}_{scenario_id}")
                stat = pra_file.stat()
                fc_name = f"{base_name}_{int(stat.st_mtime)}_{stat.st_size}"
                fc_path = os.path.join(gdb_path, fc_name)

                if arcpy.Exists(fc_path):
                    arcpy.AddMessage("  Using cached geodatabase copy (source unchanged)")
                else:
                    self._delete_old_pra_caches(gdb_path, base_name)
                    arcpy.AddMessage("  Converting to File Geodatabase (numeric fields; takes a while, done once)...")
                    self._convert_pra(map_obj, pra_file, fc_path)
                    arcpy.AddMessage(f"  Converted to: {fc_path}")

                # Load from geodatabase instead of shapefile
                if not self._already_loaded(map_obj, fc_path):
                    layer = map_obj.addDataFromPath(fc_path)
                    layer.name = base_name
                    self._apply_pra_symbology(layer)
                    layers_added.append(layer)
            else:
                arcpy.AddWarning("PRA shapefile not found")

        # Load Risk Assessment
        if "Risk Assessment" in data_types:
            risk_dir = scenario_dir / "risk_assessment"
            if risk_dir.exists():
                risk_file = self._find_file(risk_dir, "risk_*.shp")
                if risk_file and self._already_loaded(map_obj, risk_file):
                    pass
                elif risk_file:
                    arcpy.AddMessage(f"Loading risk assessment: {risk_file.name}")
                    layer = map_obj.addDataFromPath(str(risk_file))
                    self._apply_risk_symbology(layer)
                    layers_added.append(layer)
                else:
                    arcpy.AddWarning("Risk assessment shapefile not found")
            else:
                arcpy.AddWarning("Risk assessment directory not found")

        # Move layers to group if requested
        if use_group and layers_added:
            group_name = f"{region} - Scenario {scenario_id}"
            arcpy.AddMessage(f"Organizing layers in group: {group_name}")
            try:
                # Check if group already exists
                existing_group = None
                for lyr in map_obj.listLayers():
                    if lyr.isGroupLayer and lyr.name == group_name:
                        existing_group = lyr
                        arcpy.AddMessage(f"Found existing group: {group_name}")
                        break

                # Create group if it doesn't exist
                if existing_group is None:
                    group_layer = map_obj.createGroupLayer(group_name)
                    arcpy.AddMessage(f"Created new group layer: {group_name}")
                else:
                    group_layer = existing_group
                    arcpy.AddMessage(f"Adding to existing group: {group_name}")

                # Add layers to group (this creates copies in the group)
                for lyr in layers_added:
                    map_obj.addLayerToGroup(group_layer, lyr)

                # Remove original layers (they're now in the group)
                for lyr in layers_added:
                    map_obj.removeLayer(lyr)

                arcpy.AddMessage(f"Layers organized in group: {group_name}")
            except Exception as e:
                arcpy.AddWarning(f"Could not organize group layer: {e}")

        arcpy.AddMessage(f"Successfully loaded {len(layers_added)} layers")

        return

    def _already_loaded(self, map_obj, path):
        """True (with a message) if a layer of the active map already shows this file.

        Loading the same scenario twice used to add every layer a second time.
        """
        target = os.path.normcase(os.path.normpath(str(path)))
        for lyr in map_obj.listLayers():
            try:
                if lyr.isGroupLayer or not lyr.supports("DATASOURCE"):
                    continue
                if os.path.normcase(os.path.normpath(lyr.dataSource)) == target:
                    arcpy.AddMessage(f"  Already in the map as '{lyr.longName}' - skipped "
                                     f"(remove that layer to load it again)")
                    return True
            except Exception:
                continue
        return False

    def _get_completed_regions(self):
        """Regions with merged data (completed or partial)."""
        return _data.completed_regions(self.results_base)

    def _find_scenario_dir(self, region, scenario_id):
        """Scenario directory for the given region and scenario, or None."""
        return _data.find_scenario_dir(self.results_base, region, scenario_id)

    def _find_file(self, directory, pattern):
        """The result file in the directory matching the pattern (backups skipped), or None."""
        return _data.find_file(directory, pattern, warn=arcpy.AddWarning)

    def _delete_old_pra_caches(self, gdb_path, base_name):
        """Remove cached PRA copies of this region/scenario that belong to an older source file."""
        pattern = re.compile(rf"^{re.escape(base_name)}_\d+_\d+$")
        previous_workspace = arcpy.env.workspace
        try:
            arcpy.env.workspace = gdb_path
            for fc in arcpy.ListFeatureClasses(f"{base_name}_*") or []:
                if pattern.match(fc):
                    try:
                        arcpy.management.Delete(os.path.join(gdb_path, fc))
                    except Exception:
                        # e.g. still used as a layer in the map; harmless, just keep it
                        arcpy.AddWarning(f"  Could not remove outdated cache '{fc}' (in use?) - remove the layer and delete it manually")
        finally:
            arcpy.env.workspace = previous_workspace

    def _convert_pra(self, map_obj, pra_file, fc_path):
        """Convert the PRA shapefile to a feature class with numeric fields."""
        # ArcPy cannot resolve shapefile *paths* whose name contains a dot
        # (e.g. '..._rel2.3m.shp'), but it can use them as map layers. So the
        # shapefile is added as a temporary layer and converted from there.
        src_layer = map_obj.addDataFromPath(str(pra_file))
        try:
            # The PRA shapefile stores numbers as text. Map them to DOUBLE
            # explicitly, otherwise numeric filters (elevation, aspect) fail.
            field_mappings = arcpy.FieldMappings()
            field_mappings.addTable(src_layer)
            numeric_fields = {"elev_med", "aspect_deg", "area_m2", "t_high", "t_low"}
            for i in range(field_mappings.fieldCount):
                fmap = field_mappings.getFieldMap(i)
                if fmap.outputField.name.lower() in numeric_fields:
                    out_field = fmap.outputField
                    out_field.type = "Double"
                    fmap.outputField = out_field
                    field_mappings.replaceFieldMap(i, fmap)
            arcpy.conversion.ExportFeatures(src_layer, fc_path, field_mapping=field_mappings)
        finally:
            map_obj.removeLayer(src_layer)

    def _apply_lyrx(self, layer, lyrx_path):
        """Apply the symbology of a .lyrx file written by the pipeline (if present)."""
        if not lyrx_path.exists():
            arcpy.AddWarning(f"  No layer file next to raster ({lyrx_path.name}) - default symbology used")
            return
        try:
            arcpy.management.ApplySymbologyFromLayer(layer, str(lyrx_path))
            arcpy.AddMessage(f"  Applied symbology from {lyrx_path.name}")
        except Exception as e:
            arcpy.AddWarning(f"  Could not apply {lyrx_path.name}: {e}")

    def _apply_ppr_symbology(self, layer):
        """Apply PPR symbology to raster layer."""
        try:
            sym = layer.symbology
            if hasattr(sym, 'colorizer'):
                # Step 1: Switch to RasterClassifyColorizer if needed
                if sym.colorizer.type != 'RasterClassifyColorizer':
                    sym.updateColorizer('RasterClassifyColorizer')

                # Step 2: Set classification field and break count
                sym.colorizer.classificationField = "Value"
                sym.colorizer.breakCount = 5
                sym.colorizer.noDataColor = {'RGB': [0, 0, 0, 0]}

                # Step 3: Define custom breaks starting at 0.1, colors and labels
                # First break starts at 0.1 to exclude background
                breaks = [0.1, 1, 10, 25, 50, 99999]
                colors = [
                    {'RGB': [0, 0, 0, 0]},          # transparent (0-0.1) - HIDE BACKGROUND
                    {'HSV': [186, 30, 98, 100]},   # light blue (0.1-1)
                    {'HSV': [107, 49, 76, 100]},   # green (1-10)
                    {'HSV': [28, 100, 66, 100]},    # orange (10-25)
                    {'HSV': [310, 100, 55, 100]},   # purple (25-50)
                    {'HSV': [320, 100, 39, 100]}    # darker purple (>50)
                ]
                labels = [
                    "< 0.1 kPa (hidden)",
                    "0.1 - 1 kPa",
                    "1 - 10 kPa",
                    "10 - 25 kPa",
                    "25 - 50 kPa",
                    "> 50 kPa"
                ]

                # Update break count to match
                sym.colorizer.breakCount = len(breaks)

                arcpy.AddMessage(f"  PPR classBreaks available: {len(sym.colorizer.classBreaks)}")

                # Step 4: Iterate through classBreaks (official Esri pattern)
                for i, brk in enumerate(sym.colorizer.classBreaks):
                    if i < len(breaks):
                        brk.upperBound = breaks[i]
                        brk.color = colors[i]
                        brk.label = labels[i]
                        arcpy.AddMessage(f"  Set break {i}: upper={breaks[i]}, label={labels[i]}, transparent={i==0}")

                # Step 5: Apply symbology
                layer.symbology = sym
                layer.transparency = 30

            arcpy.AddMessage("Applied PPR symbology successfully")
        except Exception as e:
            arcpy.AddWarning(f"Could not apply PPR symbology: {e}")

    def _apply_tracks_symbology(self, layer):
        """Apply tracks symbology to polygon layer."""
        try:
            sym = layer.symbology
            if hasattr(sym, 'renderer'):
                # Step 1: Switch to graduated colors renderer
                sym.updateRenderer('GraduatedColorsRenderer')
                sym.renderer.classificationField = "med_pres"
                sym.renderer.breakCount = 5

                # Step 2: Define custom breaks, colors, and labels
                breaks = [50, 100, 200, 500, 99999]
                colors = [
                    {'HSV': [207, 12, 100, 100]},   # very light blue (0-50)
                    {'HSV': [207, 40, 100, 100]},   # light blue (50-100)
                    {'HSV': [213, 70, 100, 100]},   # medium blue (100-200)
                    {'HSV': [213, 100, 80, 100]},   # dark blue (200-500)
                    {'HSV': [213, 100, 48, 100]}    # very dark blue (>500)
                ]
                labels = [
                    "0 - 50 kPa",
                    "50 - 100 kPa",
                    "100 - 200 kPa",
                    "200 - 500 kPa",
                    "> 500 kPa"
                ]

                arcpy.AddMessage(f"  Tracks classBreaks available: {len(sym.renderer.classBreaks)}")

                # Step 3: Iterate through classBreaks (official Esri pattern)
                for i, brk in enumerate(sym.renderer.classBreaks):
                    if i < len(breaks):
                        brk.upperBound = breaks[i]
                        brk.label = labels[i]
                        brk.symbol.color = colors[i]
                        brk.symbol.outlineColor = {'RGB': [0, 0, 0, 100]}
                        brk.symbol.size = 1
                        arcpy.AddMessage(f"  Set break {i}: upper={breaks[i]}, label={labels[i]}")

                # Step 4: Apply symbology
                layer.symbology = sym
                layer.transparency = 10

            arcpy.AddMessage("Applied tracks symbology successfully")
        except Exception as e:
            arcpy.AddWarning(f"Could not apply tracks symbology: {e}")

    def _apply_pra_symbology(self, layer):
        """Apply PRA symbology to polygon layer."""
        try:
            sym = layer.symbology
            if hasattr(sym, 'renderer'):
                # Set to single symbol
                sym.updateRenderer('SimpleRenderer')

                # Set outline only, no fill
                symbol = sym.renderer.symbol
                symbol.color = {'RGB': [0, 0, 0, 0]}  # Transparent fill
                symbol.outlineColor = {'RGB': [0, 0, 0, 100]}  # Black outline
                symbol.outlineWidth = 1.5

                layer.symbology = sym

            arcpy.AddMessage("Applied PRA symbology")
        except Exception as e:
            arcpy.AddWarning(f"Could not apply PRA symbology: {e}")

    def _apply_risk_symbology(self, layer):
        """Apply risk assessment symbology to polygon layer."""
        try:
            sym = layer.symbology
            if hasattr(sym, 'renderer'):
                # Set to graduated colors
                sym.updateRenderer('GraduatedColorsRenderer')
                sym.renderer.classificationField = "max_ppr"
                sym.renderer.breakCount = 5

                # First compute with EqualInterval to initialize breaks
                sym.renderer.classificationMethod = "EqualInterval"

                # Now switch to Manual and set our custom breaks
                sym.renderer.classificationMethod = "Manual"

                # Define breaks (upper bounds) and colors (magenta/pink gradient)
                breaks = [25, 50, 100, 200, 10000]
                colors = [
                    {'RGB': [255, 179, 217, 100]},  # #ffb3d9 - light pink (0-25)
                    {'RGB': [255, 102, 179, 100]},  # #ff66b3 - pink (25-50)
                    {'RGB': [255, 0, 128, 100]},    # #ff0080 - magenta (50-100)
                    {'RGB': [204, 0, 102, 100]},    # #cc0066 - dark magenta (100-200)
                    {'RGB': [153, 0, 80, 100]}      # #990050 - very dark magenta (>200)
                ]

                # Apply breaks and colors to each class
                for i in range(min(len(breaks), len(sym.renderer.classBreaks))):
                    sym.renderer.classBreaks[i].upperBound = breaks[i]
                    if i < len(colors):
                        sym.renderer.classBreaks[i].symbol.color = colors[i]
                        sym.renderer.classBreaks[i].label = f"{0 if i == 0 else breaks[i-1]} - {breaks[i]}"

                layer.symbology = sym
                layer.transparency = 0

            arcpy.AddMessage("Applied risk assessment symbology")
        except Exception as e:
            arcpy.AddWarning(f"Could not apply risk assessment symbology: {e}")


class FilterLayers(object):
    MODE_REFINE = "Refine existing filter (add to it)"
    MODE_REPLACE = "Replace existing filter"
    MODE_RESET = "Reset filter (remove it)"

    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "2. Filter Layers"
        self.description = "Apply filters to selected ALARM layers (Tracks, PRAs, Risk Assessment). Run it again to refine an existing filter, replace it or reset it; PRAs must be loaded via Load ALARM Data."
        self.canRunInBackground = False

    def getParameterInfo(self):
        """Define parameter definitions"""

        # Parameter 0: Layers to filter (picked explicitly from the map)
        param0 = arcpy.Parameter(
            displayName="Layers to Filter",
            name="layers_to_filter",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
            multiValue=True)

        # Parameter 1: Minimum Elevation (optional)
        param1 = arcpy.Parameter(
            displayName="Minimum Elevation (m)",
            name="elev_min",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input")

        # Parameter 2: Maximum Elevation (optional)
        param2 = arcpy.Parameter(
            displayName="Maximum Elevation (m)",
            name="elev_max",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input")

        # Parameter 3: Aspect Filter Type
        param3 = arcpy.Parameter(
            displayName="Aspect Filter Type",
            name="aspect_type",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")

        param3.filter.type = "ValueList"
        param3.filter.list = ["None", "Cardinal Directions", "Degree Range"]
        param3.value = "None"

        # Parameter 4: Cardinal Directions (multi-select)
        param4 = arcpy.Parameter(
            displayName="Cardinal Directions",
            name="cardinal_dirs",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True)

        param4.filter.type = "ValueList"
        param4.filter.list = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        param4.enabled = False

        # Parameter 5: Aspect Min (degrees)
        param5 = arcpy.Parameter(
            displayName="Aspect Min (degrees)",
            name="aspect_min",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input")

        param5.filter.type = "Range"
        param5.filter.list = [0, 360]
        param5.enabled = False

        # Parameter 6: Aspect Max (degrees)
        param6 = arcpy.Parameter(
            displayName="Aspect Max (degrees)",
            name="aspect_max",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input")

        param6.filter.type = "Range"
        param6.filter.list = [0, 360]
        param6.enabled = False

        # Parameter 7: Safety Class (Risk Assessment only)
        param7 = arcpy.Parameter(
            displayName="Building Safety Class (Risk Assessment)",
            name="saf_class",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True)

        param7.filter.type = "ValueList"
        param7.filter.list = ["S1", "S2", "S3", "S4"]  # Common safety classes

        # Parameter 8: Minimum Max PPR (Risk Assessment only)
        param8 = arcpy.Parameter(
            displayName="Minimum Max PPR (kPa, Risk Assessment)",
            name="min_max_ppr",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input")

        # Parameter 9: How to combine with a filter that is already on the layer
        param9 = arcpy.Parameter(
            displayName="Filter Mode",
            name="filter_mode",
            datatype="GPString",
            parameterType="Required",
            direction="Input")

        param9.filter.type = "ValueList"
        param9.filter.list = [self.MODE_REFINE, self.MODE_REPLACE, self.MODE_RESET]
        param9.value = self.MODE_REFINE

        # Parameter 10: count features (informational, slower on big layers)
        param10 = arcpy.Parameter(
            displayName="Show feature counts (slower for large layers)",
            name="count_features",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input")

        param10.value = True

        return [param0, param1, param2, param3, param4, param5, param6, param7, param8, param9, param10]

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal validation is performed."""
        # Enable/disable aspect parameters based on filter type
        if parameters[3].value:  # aspect_type
            aspect_type = parameters[3].valueAsText

            if aspect_type == "Cardinal Directions":
                parameters[4].enabled = True  # cardinal_dirs
                parameters[5].enabled = False  # aspect_min
                parameters[6].enabled = False  # aspect_max
            elif aspect_type == "Degree Range":
                parameters[4].enabled = False  # cardinal_dirs
                parameters[5].enabled = True   # aspect_min
                parameters[6].enabled = True   # aspect_max
            else:  # "None"
                parameters[4].enabled = False
                parameters[5].enabled = False
                parameters[6].enabled = False

        return

    def updateMessages(self, parameters):
        """Check the criteria before the tool runs (not needed for a reset)."""
        if parameters[9].valueAsText != self.MODE_RESET:
            _show_validation(parameters, _FILTER_PARAMS, require_any=True)
        return

    def execute(self, parameters, messages):
        """The source code of the tool."""

        # Get parameters
        layer_names = _split_values(parameters[0].valueAsText)
        criteria = _criteria_from(parameters, _FILTER_PARAMS)
        mode = parameters[9].valueAsText or self.MODE_REFINE
        count_features = bool(parameters[10].value) if parameters[10].value is not None else True
        reset = mode == self.MODE_RESET
        refine = mode == self.MODE_REFINE

        # Get current map
        aprx = arcpy.mp.ArcGISProject("CURRENT")
        map_obj = aprx.activeMap

        if not map_obj:
            arcpy.AddError("No active map found. Please open a map in ArcGIS Pro.")
            return

        # Resolve the selected layers in the active map. For layers inside a group
        # ArcGIS passes the long name ("Group\\Layer"), so match on that first and
        # fall back to the short name.
        by_long_name = {}
        by_short_name = {}
        for lyr in map_obj.listLayers():
            if lyr.isFeatureLayer:
                by_long_name.setdefault(lyr.longName, []).append(lyr)
                by_short_name.setdefault(lyr.name, []).append(lyr)
        map_layers = by_long_name
        for key, lyrs in by_short_name.items():
            map_layers.setdefault(key, lyrs)

        layers_filtered = 0
        for name in layer_names:
            candidates = map_layers.get(name, [])
            if not candidates:
                arcpy.AddWarning(f"Layer '{name}' not found in the active map - skipped")
                continue
            if len(candidates) > 1:
                arcpy.AddWarning(f"Several layers are named '{name}' - filtering all of them")

            for layer in candidates:
                if reset:
                    layer.definitionQuery = ""
                    arcpy.AddMessage(f"  Reset filter: {layer.name}")
                    layers_filtered += 1
                    continue

                layer_type = self._detect_layer_type(layer)
                if layer_type == "tracks":
                    filter_query = _filters.numeric_query(criteria, "pra_elev", "pra_aspdeg")
                elif layer_type == "pras":
                    filter_query = _filters.numeric_query(criteria, "elev_med", "aspect_deg")
                elif layer_type == "risk":
                    if criteria['aspect_type'] == _filters.ASPECT_DEGREES:
                        arcpy.AddWarning(f"  {layer.name}: a degree range is not supported for Risk Assessment (aspect is stored as N/NE/...) - use Cardinal Directions")
                    filter_query = _filters.risk_query(criteria)
                else:
                    arcpy.AddWarning(f"  {layer.name}: not recognised as Tracks, PRAs or Risk Assessment - skipped")
                    continue

                if layer_type == "pras" and not self._is_numeric_field(layer, "elev_med"):
                    arcpy.AddWarning(f"  {layer.name}: 'elev_med' is a text field. Load PRAs via 'Load ALARM Data' to get numeric fields - skipped")
                    continue

                if not filter_query:
                    arcpy.AddWarning(f"  {layer.name}: no filter criteria apply to this layer type - skipped")
                    continue

                previous_query = layer.definitionQuery or ""
                try:
                    # Refine: keep the filter that is already on the layer and add the new one
                    if refine:
                        filter_query = _filters.combine_refine(previous_query, filter_query)

                    # Counting reads the whole layer, which is slow for big shapefiles on L:,
                    # so it is optional. The layer is used (not its dataSource path):
                    # paths with dots in the file name are not resolvable.
                    total = before = None
                    if count_features:
                        selected = _selection_count(layer)
                        if selected:
                            arcpy.AddWarning(f"  {layer.name}: {selected} features are selected - the counts below only "
                                             f"include the selection (the filter itself applies to all features)")
                        layer.definitionQuery = ""
                        total = before = self._count(layer)
                        if previous_query:
                            layer.definitionQuery = previous_query
                            before = self._count(layer)

                    layer.definitionQuery = filter_query
                    action = "Refined" if (refine and previous_query) else "Applied"
                    arcpy.AddMessage(f"  {action} filter on: {layer.name} ({layer_type})")
                    arcpy.AddMessage(f"    Query: {filter_query}")

                    if count_features:
                        matched = self._count(layer)
                        if previous_query and refine:
                            arcpy.AddMessage(f"    Features: {total} total | {before} before | {matched} now")
                        else:
                            arcpy.AddMessage(f"    Features: {total} -> {matched}")
                        if matched == 0:
                            arcpy.AddWarning(f"    Filter matches 0 features for {layer.name} - too restrictive?")
                    layers_filtered += 1
                except Exception as e:
                    # Counting changes the definition query temporarily; never leave the
                    # layer without its previous filter or with a broken one.
                    try:
                        layer.definitionQuery = previous_query
                    except Exception:
                        pass
                    arcpy.AddWarning(f"  Failed to apply filter to {layer.name}: {e}")
                    arcpy.AddWarning(f"  Query was: {filter_query}")
                    arcpy.AddWarning(f"  The previous filter was kept: {previous_query or '(none)'}")

        if layers_filtered == 0:
            arcpy.AddWarning("No layers were changed.")
        else:
            action = "Reset" if reset else "Filtered"
            arcpy.AddMessage(f"{action} {layers_filtered} layer(s).")

        return

    def _count(self, layer):
        """Number of features the layer currently shows (respects its definition query)."""
        return int(arcpy.management.GetCount(layer)[0])

    def _detect_layer_type(self, layer):
        """Identify an ALARM layer by its fields: 'tracks', 'pras', 'risk' or None."""
        try:
            fields = {f.name.lower() for f in arcpy.ListFields(layer)}
        except Exception:
            return None
        if "saf_class" in fields and "max_ppr" in fields:
            return "risk"
        if "med_pres" in fields and "pra_aspdeg" in fields:
            return "tracks"
        if "elev_med" in fields and "aspect_deg" in fields:
            return "pras"
        return None

    def _is_numeric_field(self, layer, field_name):
        for f in arcpy.ListFields(layer, field_name):
            return f.type in ("Double", "Single", "Integer", "SmallInteger", "OID")
        return False

class ExportFilteredData(object):
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "4. Export Filtered Data"
        self.description = "Export filtered layers to new shapefiles"
        self.canRunInBackground = False

    def getParameterInfo(self):
        """Define parameter definitions"""

        # Parameter 0: Layer to export
        param0 = arcpy.Parameter(
            displayName="Layer to Export",
            name="layer",
            datatype="GPLayer",
            parameterType="Required",
            direction="Input")

        # Parameter 1: Output directory
        param1 = arcpy.Parameter(
            displayName="Output Directory",
            name="output_dir",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input")

        # Parameter 2: Output filename (optional)
        param2 = arcpy.Parameter(
            displayName="Output Filename (optional)",
            name="output_name",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")

        param2.value = ""

        return [param0, param1, param2]

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal validation is performed."""
        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool parameter."""
        return

    def execute(self, parameters, messages):
        """The source code of the tool."""
        # Get parameters
        layer = parameters[0].value
        output_dir = parameters[1].valueAsText
        output_name = parameters[2].valueAsText

        # Generate output filename (dots in layer names such as 'rel2.3m' are invalid in shapefile names)
        if not output_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_name = f"{layer.name}_filtered_{timestamp}"
        if output_name.lower().endswith('.shp'):
            output_name = output_name[:-4]
        output_name = re.sub(r"[^0-9A-Za-z_]", "_", output_name) + ".shp"

        output_path = os.path.join(output_dir, output_name)

        if os.path.exists(output_path):
            arcpy.AddError(f"{output_path} already exists. Choose another filename or delete the existing file.")
            return

        arcpy.AddMessage(f"Exporting layer: {layer.name}")
        arcpy.AddMessage(f"Output: {output_path}")

        # Check if layer has definition query (filter)
        if hasattr(layer, 'definitionQuery') and layer.definitionQuery:
            arcpy.AddMessage(f"Active filter: {layer.definitionQuery}")
        else:
            arcpy.AddMessage("No filter active - exporting all features")

        selected = _selection_count(layer)
        if selected:
            arcpy.AddWarning(f"{selected} features are selected in '{layer.name}' - only the selected features "
                             f"are exported. Clear the selection to export everything the filter shows.")

        try:
            # Export the layer (respects definitionQuery automatically)
            arcpy.conversion.ExportFeatures(layer, output_path)

            # Count features
            result = arcpy.management.GetCount(output_path)
            count = int(result.getOutput(0))

            arcpy.AddMessage(f"Successfully exported {count} features to:")
            arcpy.AddMessage(f"  {output_path}")

        except Exception as e:
            arcpy.AddError(f"Export failed: {e}")

        return


class GenerateReport(object):
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "3. Generate Report"
        self.description = "Generate statistics report for Risk Assessment layer"
        self.canRunInBackground = False

    def getParameterInfo(self):
        """Define parameter definitions"""

        # Parameter 0: Risk Assessment Layer
        param0 = arcpy.Parameter(
            displayName="Risk Assessment Layer",
            name="risk_layer",
            datatype="GPLayer",
            parameterType="Required",
            direction="Input")

        # Parameter 1: Output directory
        param1 = arcpy.Parameter(
            displayName="Output Directory",
            name="output_dir",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input")

        # Parameter 2: Report format
        param2 = arcpy.Parameter(
            displayName="Report Format",
            name="report_format",
            datatype="GPString",
            parameterType="Required",
            direction="Input")

        param2.filter.type = "ValueList"
        param2.filter.list = ["HTML", "CSV", "Both"]
        param2.value = "HTML"

        return [param0, param1, param2]

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal validation is performed."""
        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool parameter."""
        return

    def execute(self, parameters, messages):
        """The source code of the tool."""
        layer = parameters[0].value
        output_dir = parameters[1].valueAsText
        report_format = parameters[2].valueAsText

        arcpy.AddMessage(f"Analyzing layer: {layer.name}")
        definition_query = getattr(layer, 'definitionQuery', "") or ""
        if definition_query:
            arcpy.AddMessage(f"Active filter: {definition_query}")
        selected = _selection_count(layer)
        if selected:
            arcpy.AddWarning(f"{selected} features are selected in '{layer.name}' - the report only covers the "
                             f"selection. Clear the selection to report everything the filter shows.")

        try:
            # The cursor respects the layer's filter and selection
            with arcpy.da.SearchCursor(layer, _report.FIELDS) as cursor:
                stats = _report.collect(cursor)
        except Exception as e:
            arcpy.AddError(f"Could not read {', '.join(_report.FIELDS)} from '{layer.name}' - "
                           f"is it a Risk Assessment layer? ({e})")
            return

        arcpy.AddMessage(f"Analyzed {stats['total']} buildings")
        if stats['elevation'][_report.UNKNOWN]:
            arcpy.AddWarning(f"{stats['elevation'][_report.UNKNOWN]} buildings have no elevation (listed as Unknown)")

        source = getattr(layer, 'dataSource', None)
        context = _report.context_lines(layer.name, definition_query, selected, source)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = re.sub(r"[^0-9A-Za-z_]", "_", f"risk_report_{layer.name}_{timestamp}")

        if report_format in ["HTML", "Both"]:
            html_path = os.path.join(output_dir, base + ".html")
            _report.write_html(html_path, stats, context)
            arcpy.AddMessage(f"HTML report: {html_path}")
        if report_format in ["CSV", "Both"]:
            csv_path = os.path.join(output_dir, base + ".csv")
            _report.write_csv(csv_path, stats, context)
            arcpy.AddMessage(f"CSV report: {csv_path}")
        return


class CompareScenarios(object):
    """Compare the scenarios of one region side by side, with one shared filter.

    The counting and the tables live in alarm_core.compare; this class only handles the
    tool dialog and the messages.
    """

    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "5. Compare Scenarios"
        self.description = ("Compare the scenarios of a region side by side (tracks, PRAs, buildings by safety "
                            "class and pressure) with one shared filter. Writes an HTML and/or CSV table.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        """Define parameter definitions"""
        cfg = _config.load_config()

        param0 = arcpy.Parameter(displayName="Region", name="region", datatype="GPString",
                                 parameterType="Required", direction="Input")
        regions = _data.completed_regions(cfg['results_base'])
        param0.filter.type = "ValueList"
        param0.filter.list = regions if regions else ["No regions found"]

        scenario_list = [f"{k} - {v}" for k, v in cfg['scenarios'].items()]
        param1 = arcpy.Parameter(displayName="Scenarios to Compare", name="scenarios", datatype="GPString",
                                 parameterType="Required", direction="Input", multiValue=True)
        param1.filter.type = "ValueList"
        param1.filter.list = scenario_list
        param1.value = scenario_list

        param2 = arcpy.Parameter(displayName="Minimum Elevation (m)", name="elev_min", datatype="GPDouble",
                                 parameterType="Optional", direction="Input")
        param3 = arcpy.Parameter(displayName="Maximum Elevation (m)", name="elev_max", datatype="GPDouble",
                                 parameterType="Optional", direction="Input")

        param4 = arcpy.Parameter(displayName="Aspect Filter Type", name="aspect_type", datatype="GPString",
                                 parameterType="Optional", direction="Input")
        param4.filter.type = "ValueList"
        param4.filter.list = [_filters.ASPECT_NONE, _filters.ASPECT_CARDINAL, _filters.ASPECT_DEGREES]
        param4.value = _filters.ASPECT_NONE

        param5 = arcpy.Parameter(displayName="Cardinal Directions", name="cardinal_dirs", datatype="GPString",
                                 parameterType="Optional", direction="Input", multiValue=True)
        param5.filter.type = "ValueList"
        param5.filter.list = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        param5.enabled = False

        param6 = arcpy.Parameter(displayName="Aspect Min (degrees)", name="aspect_min", datatype="GPDouble",
                                 parameterType="Optional", direction="Input")
        param6.filter.type = "Range"
        param6.filter.list = [0, 360]
        param6.enabled = False
        param7 = arcpy.Parameter(displayName="Aspect Max (degrees)", name="aspect_max", datatype="GPDouble",
                                 parameterType="Optional", direction="Input")
        param7.filter.type = "Range"
        param7.filter.list = [0, 360]
        param7.enabled = False

        param8 = arcpy.Parameter(displayName="Building Safety Class (Risk Assessment)", name="saf_class",
                                 datatype="GPString", parameterType="Optional", direction="Input", multiValue=True)
        param8.filter.type = "ValueList"
        param8.filter.list = ["S1", "S2", "S3", "S4"]

        param9 = arcpy.Parameter(displayName="Minimum Max PPR (kPa, Risk Assessment)", name="min_max_ppr",
                                 datatype="GPDouble", parameterType="Optional", direction="Input")

        param10 = arcpy.Parameter(displayName="Output Directory", name="output_dir", datatype="DEFolder",
                                  parameterType="Required", direction="Input")

        param11 = arcpy.Parameter(displayName="Report Format", name="report_format", datatype="GPString",
                                  parameterType="Required", direction="Input")
        param11.filter.type = "ValueList"
        param11.filter.list = ["HTML", "CSV", "Both"]
        param11.value = "HTML"

        return [param0, param1, param2, param3, param4, param5, param6, param7, param8, param9, param10, param11]

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Enable/disable the aspect parameters depending on the aspect filter type."""
        if parameters[4].value:
            aspect_type = parameters[4].valueAsText
            parameters[5].enabled = aspect_type == _filters.ASPECT_CARDINAL
            parameters[6].enabled = aspect_type == _filters.ASPECT_DEGREES
            parameters[7].enabled = aspect_type == _filters.ASPECT_DEGREES
        return

    def updateMessages(self, parameters):
        """Check region and criteria before the tool runs."""
        _check_region(parameters[0])
        _show_validation(parameters, _COMPARE_PARAMS)
        return

    def execute(self, parameters, messages):
        """The source code of the tool."""
        region = parameters[0].valueAsText
        scenario_ids = [v.split(' - ')[0] for v in _split_values(parameters[1].valueAsText)]
        criteria = _criteria_from(parameters, _COMPARE_PARAMS)
        output_dir = parameters[10].valueAsText
        report_format = parameters[11].valueAsText

        cfg = _config.load_config()
        results = []
        for sid in scenario_ids:
            scenario_dir = _data.find_scenario_dir(cfg['results_base'], region, sid)
            if not scenario_dir:
                arcpy.AddWarning(f"Scenario {sid}: no data found for {region} - skipped")
                continue
            arcpy.AddMessage(f"Scenario {sid}: reading {scenario_dir.name}")
            results.append(_compare.compute_scenario(
                sid, scenario_dir, criteria, label=cfg['scenarios'].get(sid, sid), warn=arcpy.AddWarning))

        if not results:
            arcpy.AddError("No scenarios could be read.")
            return

        rows = _compare.build_rows(results)
        arcpy.AddMessage("")
        for line in _compare.table_lines(rows, results):
            arcpy.AddMessage(line)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = re.sub(r"[^0-9A-Za-z_]", "_", f"compare_{region}_{timestamp}")
        if report_format in ("HTML", "Both"):
            html_path = os.path.join(output_dir, base + ".html")
            _compare.write_html(html_path, region, results, rows, criteria)
            arcpy.AddMessage(f"HTML report: {html_path}")
        if report_format in ("CSV", "Both"):
            csv_path = os.path.join(output_dir, base + ".csv")
            _compare.write_csv(csv_path, results, rows)
            arcpy.AddMessage(f"CSV report: {csv_path}")
        return
