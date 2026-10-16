"""
ALARM Tools - ArcGIS Pro Python Toolbox
========================================
Tools for loading and managing ALARM regional avalanche data.

Tools:
1. Load ALARM Data - Load specific region and scenario into current map
2. Filter Layers - Filter Tracks / PRAs / Risk Assessment by elevation, aspect, safety class, PPR
3. Generate Report - Statistics report (HTML/CSV) for a Risk Assessment layer
4. Export Filtered Data - Export a (filtered) layer
5. Compare Scenarios - Prepare two layers for comparison
6. Update Overview - Regenerate HTML overview page

Author: ALARM Pipeline
Date: 2026-04-07
"""

import arcpy
import os
import re
from datetime import datetime
from pathlib import Path
import subprocess
import sys


class Toolbox(object):
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the .pyt file)."""
        self.label = "ALARM Tools v2"
        self.alias = "ALARM"
        self.description = "Tools for loading and managing ALARM regional avalanche data"

        # List of tool classes associated with this toolbox
        self.tools = [LoadALARMData, FilterLayers, GenerateReport, ExportFilteredData, CompareScenarios, UpdateOverview]


class LoadALARMData(object):
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "1. Load ALARM Data"
        self.description = "Load ALARM data for a specific region and scenario into the current map"
        self.canRunInBackground = False

        # Configuration
        self.results_base = Path(r"L:\ALARM\Results")

        self.scenarios = {
            'A': 'A (80-60, prox0, rel1.2m)',
            'B': 'B (80-60, prox0, rel1.8m)',
            'C': 'C (80-60, prox100, rel2.3m)',
            'D': 'D (75-55, prox0, rel2.3m)',
            'E': 'E (75-55, prox150, rel2.3m)'
        }

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
        return

    def execute(self, parameters, messages):
        """The source code of the tool."""

        # Get parameters
        region = parameters[0].valueAsText
        scenario_full = parameters[1].valueAsText
        scenario_id = scenario_full.split(' - ')[0]  # Extract 'A' from 'A - (80-60, prox0, rel1.2m)'
        # Strip quotes and whitespace from data types
        data_types = [dt.strip().strip("'\"") for dt in parameters[2].valueAsText.split(';')]
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
            if ppr_file:
                arcpy.AddMessage(f"Loading PPR raster: {ppr_file.name}")
                layer = map_obj.addDataFromPath(str(ppr_file))
                self._apply_ppr_symbology(layer)
                layers_added.append(layer)
            else:
                arcpy.AddWarning("PPR raster not found")

        # Load PFV (flow velocity) and PFT (flow thickness) rasters.
        # The pipeline writes a matching .lyrx next to each raster; use it for the styling.
        for label, prefix in (("PFV Raster", "pfv"), ("PFT Raster", "pft")):
            if label in data_types:
                raster_file = self._find_file(scenario_dir, f"{prefix}_*.tif")
                if raster_file:
                    arcpy.AddMessage(f"Loading {label}: {raster_file.name}")
                    layer = map_obj.addDataFromPath(str(raster_file))
                    self._apply_lyrx(layer, raster_file.with_suffix(".lyrx"))
                    layers_added.append(layer)
                else:
                    arcpy.AddWarning(f"{label} not found")

        # Load Tracks
        if "Tracks" in data_types:
            tracks_file = self._find_file(scenario_dir, "tracks_*.shp")
            if tracks_file:
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
                arcpy.AddMessage("  Converting to File Geodatabase (fixes String field types for filtering)...")

                gdb_path = aprx.defaultGeodatabase

                # Generate feature class name (GDB names must not contain - or .)
                fc_name = re.sub(r"[^0-9A-Za-z_]", "_", f"pra_{region}_{scenario_id}")
                fc_path = os.path.join(gdb_path, fc_name)

                if arcpy.Exists(fc_path):
                    arcpy.management.Delete(fc_path)

                # ArcPy cannot resolve shapefile *paths* whose name contains a dot
                # (e.g. '..._rel2.3m.shp'), but it can use them as map layers. So the
                # shapefile is added as a temporary layer and converted from there.
                src_layer = map_obj.addDataFromPath(str(pra_file))

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

                try:
                    arcpy.conversion.ExportFeatures(src_layer, fc_path, field_mapping=field_mappings)
                finally:
                    map_obj.removeLayer(src_layer)

                arcpy.AddMessage(f"  Converted to: {fc_path}")

                # Load from geodatabase instead of shapefile
                layer = map_obj.addDataFromPath(fc_path)
                self._apply_pra_symbology(layer)
                layers_added.append(layer)
            else:
                arcpy.AddWarning("PRA shapefile not found")

        # Load Risk Assessment
        if "Risk Assessment" in data_types:
            risk_dir = scenario_dir / "risk_assessment"
            if risk_dir.exists():
                risk_file = self._find_file(risk_dir, "risk_*.shp")
                if risk_file:
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

    def _get_completed_regions(self):
        """Get list of regions with merged data (completed or partial)."""
        regions = []
        if not self.results_base.exists():
            return regions

        for region_dir in self.results_base.iterdir():
            if region_dir.is_dir():
                # Check if merged folder exists (indicates data is available)
                merged_dir = region_dir / "merged"
                if merged_dir.exists() and any(merged_dir.iterdir()):
                    regions.append(region_dir.name)

        return sorted(regions)

    def _find_scenario_dir(self, region, scenario_id):
        """Find scenario directory for given region and scenario."""
        region_dir = self.results_base / region / "merged"
        if not region_dir.exists():
            return None

        # Find directory starting with scenario ID
        scenario_dirs = list(region_dir.glob(f"{scenario_id}_*"))
        return scenario_dirs[0] if scenario_dirs else None

    def _find_file(self, directory, pattern):
        """Find first file matching pattern in directory."""
        files = list(directory.glob(pattern))
        return files[0] if files else None

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


class UpdateOverview(object):
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "6. Update Overview"
        self.description = "Regenerate HTML overview page with latest data"
        self.canRunInBackground = False

    def getParameterInfo(self):
        """Define parameter definitions"""

        # Parameter 0: Output directory
        param0 = arcpy.Parameter(
            displayName="Output Directory",
            name="output_dir",
            datatype="DEFolder",
            parameterType="Optional",
            direction="Input")

        param0.value = r"L:\ALARM\ALARM_Overview"

        return [param0]

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
        return

    def execute(self, parameters, messages):
        """The source code of the tool."""

        output_dir = parameters[0].valueAsText

        arcpy.AddMessage("Updating ALARM overview...")
        arcpy.AddMessage(f"Output directory: {output_dir}")

        # Find Python script
        script_dir = Path(__file__).parent
        script_path = script_dir / "generate_data_overview.py"

        if not script_path.exists():
            arcpy.AddError(f"Script not found: {script_path}")
            return

        # Get Python executable from conda environment
        python_exe = sys.executable

        arcpy.AddMessage(f"Running script: {script_path}")
        arcpy.AddMessage(f"Python: {python_exe}")

        try:
            # Run script
            result = subprocess.run(
                [python_exe, str(script_path)],
                capture_output=True,
                text=True,
                timeout=600  # 10 minutes timeout
            )

            # Show output
            if result.stdout:
                for line in result.stdout.split('\n'):
                    if line.strip():
                        arcpy.AddMessage(line)

            if result.stderr:
                for line in result.stderr.split('\n'):
                    if line.strip():
                        arcpy.AddWarning(line)

            if result.returncode == 0:
                arcpy.AddMessage("Overview updated successfully!")
                arcpy.AddMessage(f"Open: {output_dir}\\index.html")
            else:
                arcpy.AddError(f"Script failed with return code {result.returncode}")

        except subprocess.TimeoutExpired:
            arcpy.AddError("Script timed out after 10 minutes")
        except Exception as e:
            arcpy.AddError(f"Error running script: {e}")

        return


class FilterLayers(object):
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "2. Filter Layers"
        self.description = "Apply filters to selected ALARM layers (Tracks, PRAs, Risk Assessment). A new filter replaces the existing one; PRAs must be loaded via Load ALARM Data."
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

        # Parameter 9: Reset filters
        param9 = arcpy.Parameter(
            displayName="Reset filters (remove existing definition queries instead of filtering)",
            name="reset_filters",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input")

        param9.value = False

        return [param0, param1, param2, param3, param4, param5, param6, param7, param8, param9]

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
        """Modify the messages created by internal validation for each tool parameter."""
        return

    def execute(self, parameters, messages):
        """The source code of the tool."""

        # Get parameters
        layer_names = [l.strip().strip("'\"") for l in parameters[0].valueAsText.split(';')]
        elev_min = parameters[1].value
        elev_max = parameters[2].value
        aspect_type = parameters[3].valueAsText if parameters[3].value else "None"
        cardinal_dirs = parameters[4].valueAsText.split(';') if parameters[4].value else []
        cardinal_dirs = [d.strip().strip("'\"") for d in cardinal_dirs] if cardinal_dirs else []
        aspect_min = parameters[5].value
        aspect_max = parameters[6].value
        saf_classes = parameters[7].valueAsText.split(';') if parameters[7].value else []
        saf_classes = [s.strip().strip("'\"") for s in saf_classes] if saf_classes else []
        min_max_ppr = parameters[8].value
        reset = bool(parameters[9].value)

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
                    filter_query = self._build_filter_query(elev_min, elev_max, aspect_type, cardinal_dirs, aspect_min, aspect_max, "pra_elev", "pra_aspdeg")
                elif layer_type == "pras":
                    filter_query = self._build_filter_query(elev_min, elev_max, aspect_type, cardinal_dirs, aspect_min, aspect_max, "elev_med", "aspect_deg")
                elif layer_type == "risk":
                    if aspect_type != "None":
                        arcpy.AddWarning(f"  {layer.name}: aspect filter is not supported for Risk Assessment (text field) - ignored")
                    filter_query = self._build_risk_filter_query(elev_min, elev_max, saf_classes, min_max_ppr)
                else:
                    arcpy.AddWarning(f"  {layer.name}: not recognised as Tracks, PRAs or Risk Assessment - skipped")
                    continue

                if layer_type == "pras" and not self._is_numeric_field(layer, "elev_med"):
                    arcpy.AddWarning(f"  {layer.name}: 'elev_med' is a text field. Load PRAs via 'Load ALARM Data' to get numeric fields - skipped")
                    continue

                if not filter_query:
                    arcpy.AddWarning(f"  {layer.name}: no filter criteria apply to this layer type - skipped")
                    continue

                try:
                    # Count unfiltered features first. The layer is used instead of its
                    # dataSource path, because paths with dots are not resolvable.
                    layer.definitionQuery = ""
                    total = int(arcpy.management.GetCount(layer)[0])
                    layer.definitionQuery = filter_query
                    arcpy.AddMessage(f"  Applied filter to: {layer.name} ({layer_type})")
                    arcpy.AddMessage(f"    Query: {filter_query}")

                    tmp = arcpy.management.MakeFeatureLayer(layer, "alarm_filter_tmp", filter_query)
                    matched = int(arcpy.management.GetCount(tmp)[0])
                    arcpy.management.Delete(tmp)
                    arcpy.AddMessage(f"    Features: {total} -> {matched}")

                    if matched == 0:
                        arcpy.AddWarning(f"    Filter matches 0 features for {layer.name} - too restrictive?")
                    layers_filtered += 1
                except Exception as e:
                    arcpy.AddWarning(f"  Failed to apply filter to {layer.name}: {e}")
                    arcpy.AddWarning(f"  Query was: {filter_query}")

        if layers_filtered == 0:
            arcpy.AddWarning("No layers were changed.")
        else:
            action = "Reset" if reset else "Filtered"
            arcpy.AddMessage(f"{action} {layers_filtered} layer(s). A new filter replaces any existing one on the same layer.")

        return

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

    def _build_filter_query(self, elev_min, elev_max, aspect_type, cardinal_dirs, aspect_min, aspect_max, elev_field, aspect_field):
        """Build SQL WHERE clause for filtering based on elevation and aspect.

        Args:
            elev_min, elev_max: Elevation range
            aspect_type: "None", "Cardinal Directions", or "Degree Range"
            cardinal_dirs: List of cardinal directions
            aspect_min, aspect_max: Aspect degree range
            elev_field: Name of elevation field (e.g., "pra_elev", "elev_med")
            aspect_field: Name of aspect field (e.g., "pra_aspdeg", "aspect_deg") or None
        """
        conditions = []

        # Elevation filter
        if elev_field and elev_min is not None:
            conditions.append(f"{elev_field} >= {elev_min}")
        if elev_field and elev_max is not None:
            conditions.append(f"{elev_field} <= {elev_max}")

        # Aspect filter (only if aspect_field is provided and numeric)
        if aspect_field:
            if aspect_type == "Cardinal Directions" and cardinal_dirs:
                # Convert cardinal directions to degree ranges
                aspect_conditions = []
                cardinal_ranges = {
                    'N': [(337.5, 360), (0, 22.5)],
                    'NE': [(22.5, 67.5)],
                    'E': [(67.5, 112.5)],
                    'SE': [(112.5, 157.5)],
                    'S': [(157.5, 202.5)],
                    'SW': [(202.5, 247.5)],
                    'W': [(247.5, 292.5)],
                    'NW': [(292.5, 337.5)]
                }

                for direction in cardinal_dirs:
                    if direction in cardinal_ranges:
                        for range_tuple in cardinal_ranges[direction]:
                            if len(range_tuple) == 2:
                                aspect_conditions.append(f"({aspect_field} >= {range_tuple[0]} AND {aspect_field} < {range_tuple[1]})")

                if aspect_conditions:
                    conditions.append(f"({' OR '.join(aspect_conditions)})")

            elif aspect_type == "Degree Range" and aspect_min is not None and aspect_max is not None:
                # Handle wrapping around 0/360 degrees
                if aspect_min <= aspect_max:
                    conditions.append(f"({aspect_field} >= {aspect_min} AND {aspect_field} <= {aspect_max})")
                else:
                    # Wraps around (e.g., 350 to 10 degrees)
                    conditions.append(f"({aspect_field} >= {aspect_min} OR {aspect_field} <= {aspect_max})")

        # Combine all conditions
        if conditions:
            return " AND ".join(conditions)
        return None

    def _build_risk_filter_query(self, elev_min, elev_max, saf_classes, min_max_ppr):
        """Build SQL WHERE clause for Risk Assessment layer filtering.

        Args:
            elev_min, elev_max: Elevation range (uses pra_elev field)
            saf_classes: List of safety classes (e.g., ["S1", "S2"])
            min_max_ppr: Minimum max_ppr threshold
        """
        conditions = []

        # Elevation filter
        if elev_min is not None:
            conditions.append(f"pra_elev >= {elev_min}")
        if elev_max is not None:
            conditions.append(f"pra_elev <= {elev_max}")

        # Safety class filter
        if saf_classes:
            # SQL IN clause for multiple safety classes
            classes_str = "', '".join(saf_classes)
            conditions.append(f"saf_class IN ('{classes_str}')")

        # Max PPR filter
        if min_max_ppr is not None:
            conditions.append(f"max_ppr >= {min_max_ppr}")

        # Combine all conditions
        if conditions:
            return " AND ".join(conditions)
        return None


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
        from collections import defaultdict

        # Get parameters
        layer = parameters[0].value
        output_dir = parameters[1].valueAsText
        report_format = parameters[2].valueAsText

        arcpy.AddMessage(f"Analyzing layer: {layer.name}")

        # Check if layer has definition query (filter)
        if hasattr(layer, 'definitionQuery') and layer.definitionQuery:
            arcpy.AddMessage(f"Active filter: {layer.definitionQuery}")

        # Collect statistics
        stats = {
            'total_count': 0,
            'safety_class': defaultdict(int),
            'ppr_categories': defaultdict(int),
            'elevation_ranges': defaultdict(int),
            'aspect_categories': defaultdict(int),
            'max_ppr_values': [],
            'mean_ppr_values': [],
            'pra_elev_values': []
        }

        try:
            # Read all features
            fields = ['saf_class', 'max_ppr', 'mean_ppr', 'pra_elev', 'pra_aspct']

            with arcpy.da.SearchCursor(layer, fields) as cursor:
                for row in cursor:
                    stats['total_count'] += 1

                    # Safety class
                    saf_class = row[0] if row[0] else 'Unknown'
                    stats['safety_class'][saf_class] += 1

                    # PPR categories
                    max_ppr = row[1] if row[1] is not None else 0
                    stats['max_ppr_values'].append(max_ppr)
                    if max_ppr < 25:
                        stats['ppr_categories']['0-25 kPa'] += 1
                    elif max_ppr < 50:
                        stats['ppr_categories']['25-50 kPa'] += 1
                    elif max_ppr < 100:
                        stats['ppr_categories']['50-100 kPa'] += 1
                    elif max_ppr < 200:
                        stats['ppr_categories']['100-200 kPa'] += 1
                    else:
                        stats['ppr_categories']['>200 kPa'] += 1

                    # Mean PPR
                    if row[2] is not None:
                        stats['mean_ppr_values'].append(row[2])

                    # Elevation ranges
                    pra_elev = row[3] if row[3] is not None else 0
                    stats['pra_elev_values'].append(pra_elev)
                    if pra_elev < 500:
                        stats['elevation_ranges']['<500m'] += 1
                    elif pra_elev < 1000:
                        stats['elevation_ranges']['500-1000m'] += 1
                    elif pra_elev < 1500:
                        stats['elevation_ranges']['1000-1500m'] += 1
                    elif pra_elev < 2000:
                        stats['elevation_ranges']['1500-2000m'] += 1
                    else:
                        stats['elevation_ranges']['>2000m'] += 1

                    # Aspect categories (pra_aspct is String field with cardinal directions)
                    aspect_str = row[4] if row[4] else 'Unknown'
                    # Map string aspect to cardinal direction
                    if aspect_str and aspect_str != 'Unknown':
                        try:
                            # If it's a numeric string, convert to cardinal direction
                            aspect_deg = float(aspect_str)
                            if aspect_deg >= 337.5 or aspect_deg < 22.5:
                                cardinal = 'N'
                            elif aspect_deg < 67.5:
                                cardinal = 'NE'
                            elif aspect_deg < 112.5:
                                cardinal = 'E'
                            elif aspect_deg < 157.5:
                                cardinal = 'SE'
                            elif aspect_deg < 202.5:
                                cardinal = 'S'
                            elif aspect_deg < 247.5:
                                cardinal = 'SW'
                            elif aspect_deg < 292.5:
                                cardinal = 'W'
                            else:
                                cardinal = 'NW'
                            stats['aspect_categories'][cardinal] += 1
                        except (ValueError, TypeError):
                            # If it's already a cardinal direction string, use it
                            stats['aspect_categories'][aspect_str] += 1
                    else:
                        stats['aspect_categories']['Unknown'] += 1

            arcpy.AddMessage(f"Analyzed {stats['total_count']} buildings")

            # Generate reports
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            if report_format in ["HTML", "Both"]:
                html_path = os.path.join(output_dir, f"risk_report_{timestamp}.html")
                self._generate_html_report(stats, html_path, layer.name)
                arcpy.AddMessage(f"HTML report: {html_path}")

            if report_format in ["CSV", "Both"]:
                csv_path = os.path.join(output_dir, f"risk_report_{timestamp}.csv")
                self._generate_csv_report(stats, csv_path)
                arcpy.AddMessage(f"CSV report: {csv_path}")

        except Exception as e:
            arcpy.AddError(f"Report generation failed: {e}")
            import traceback
            arcpy.AddError(traceback.format_exc())

        return

    def _generate_html_report(self, stats, output_path, layer_name):
        """Generate HTML report."""
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Risk Assessment Report - {layer_name}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        h2 {{ color: #666; margin-top: 30px; }}
        table {{ border-collapse: collapse; width: 100%; max-width: 600px; margin: 10px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #4CAF50; color: white; }}
        tr:nth-child(even) {{ background-color: #f2f2f2; }}
        .summary {{ background-color: #e7f3fe; padding: 15px; border-left: 6px solid #2196F3; margin: 20px 0; }}
    </style>
</head>
<body>
    <h1>Risk Assessment Report</h1>
    <p><strong>Layer:</strong> {layer_name}</p>
    <p><strong>Generated:</strong> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>

    <div class="summary">
        <h2>Summary</h2>
        <p><strong>Total Buildings Analyzed:</strong> {stats['total_count']}</p>
        <p><strong>Max PPR Range:</strong> {min(stats['max_ppr_values']) if stats['max_ppr_values'] else 0:.2f} - {max(stats['max_ppr_values']) if stats['max_ppr_values'] else 0:.2f} kPa</p>
        <p><strong>Mean PPR Average:</strong> {sum(stats['mean_ppr_values'])/len(stats['mean_ppr_values']) if stats['mean_ppr_values'] else 0:.2f} kPa</p>
        <p><strong>Elevation Range:</strong> {min(stats['pra_elev_values']) if stats['pra_elev_values'] else 0:.0f} - {max(stats['pra_elev_values']) if stats['pra_elev_values'] else 0:.0f} m</p>
    </div>

    <h2>Buildings by Safety Class</h2>
    <table>
        <tr><th>Safety Class</th><th>Count</th><th>Percentage</th></tr>
"""
        for saf_class, count in sorted(stats['safety_class'].items()):
            pct = (count / stats['total_count'] * 100) if stats['total_count'] > 0 else 0
            html += f"        <tr><td>{saf_class}</td><td>{count}</td><td>{pct:.1f}%</td></tr>\n"

        html += """    </table>

    <h2>Buildings by PPR Category</h2>
    <table>
        <tr><th>PPR Range</th><th>Count</th><th>Percentage</th></tr>
"""
        ppr_order = ['0-25 kPa', '25-50 kPa', '50-100 kPa', '100-200 kPa', '>200 kPa']
        for category in ppr_order:
            count = stats['ppr_categories'].get(category, 0)
            pct = (count / stats['total_count'] * 100) if stats['total_count'] > 0 else 0
            html += f"        <tr><td>{category}</td><td>{count}</td><td>{pct:.1f}%</td></tr>\n"

        html += """    </table>

    <h2>Buildings by Elevation Range</h2>
    <table>
        <tr><th>Elevation Range</th><th>Count</th><th>Percentage</th></tr>
"""
        elev_order = ['<500m', '500-1000m', '1000-1500m', '1500-2000m', '>2000m']
        for category in elev_order:
            count = stats['elevation_ranges'].get(category, 0)
            pct = (count / stats['total_count'] * 100) if stats['total_count'] > 0 else 0
            html += f"        <tr><td>{category}</td><td>{count}</td><td>{pct:.1f}%</td></tr>\n"

        html += """    </table>

    <h2>Buildings by Aspect</h2>
    <table>
        <tr><th>Aspect</th><th>Count</th><th>Percentage</th></tr>
"""
        for aspect, count in sorted(stats['aspect_categories'].items()):
            pct = (count / stats['total_count'] * 100) if stats['total_count'] > 0 else 0
            html += f"        <tr><td>{aspect}</td><td>{count}</td><td>{pct:.1f}%</td></tr>\n"

        html += """    </table>
</body>
</html>
"""

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)

    def _generate_csv_report(self, stats, output_path):
        """Generate CSV report."""
        import csv

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # Summary
            writer.writerow(['SUMMARY'])
            writer.writerow(['Total Buildings', stats['total_count']])
            writer.writerow(['Max PPR Min', min(stats['max_ppr_values']) if stats['max_ppr_values'] else 0])
            writer.writerow(['Max PPR Max', max(stats['max_ppr_values']) if stats['max_ppr_values'] else 0])
            writer.writerow(['Mean PPR Avg', sum(stats['mean_ppr_values'])/len(stats['mean_ppr_values']) if stats['mean_ppr_values'] else 0])
            writer.writerow([])

            # Safety Class
            writer.writerow(['SAFETY CLASS', 'Count', 'Percentage'])
            for saf_class, count in sorted(stats['safety_class'].items()):
                pct = (count / stats['total_count'] * 100) if stats['total_count'] > 0 else 0
                writer.writerow([saf_class, count, f"{pct:.1f}%"])
            writer.writerow([])

            # PPR Categories
            writer.writerow(['PPR CATEGORY', 'Count', 'Percentage'])
            ppr_order = ['0-25 kPa', '25-50 kPa', '50-100 kPa', '100-200 kPa', '>200 kPa']
            for category in ppr_order:
                count = stats['ppr_categories'].get(category, 0)
                pct = (count / stats['total_count'] * 100) if stats['total_count'] > 0 else 0
                writer.writerow([category, count, f"{pct:.1f}%"])
            writer.writerow([])

            # Elevation
            writer.writerow(['ELEVATION RANGE', 'Count', 'Percentage'])
            elev_order = ['<500m', '500-1000m', '1000-1500m', '1500-2000m', '>2000m']
            for category in elev_order:
                count = stats['elevation_ranges'].get(category, 0)
                pct = (count / stats['total_count'] * 100) if stats['total_count'] > 0 else 0
                writer.writerow([category, count, f"{pct:.1f}%"])
            writer.writerow([])

            # Aspect
            writer.writerow(['ASPECT', 'Count', 'Percentage'])
            for aspect, count in sorted(stats['aspect_categories'].items()):
                pct = (count / stats['total_count'] * 100) if stats['total_count'] > 0 else 0
                writer.writerow([aspect, count, f"{pct:.1f}%"])


class CompareScenarios(object):
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "5. Compare Scenarios"
        self.description = "Compare two scenarios visually with Swipe or Side-by-Side view"
        self.canRunInBackground = False

    def getParameterInfo(self):
        """Define parameter definitions"""

        # Parameter 0: Comparison Mode
        param0 = arcpy.Parameter(
            displayName="Comparison Mode",
            name="comparison_mode",
            datatype="GPString",
            parameterType="Required",
            direction="Input")

        param0.filter.type = "ValueList"
        param0.filter.list = ["Swipe Tool", "Side-by-Side Maps"]
        param0.value = "Swipe Tool"

        # Parameter 1: Layer 1
        param1 = arcpy.Parameter(
            displayName="Layer 1 (Left/Top)",
            name="layer1",
            datatype="GPLayer",
            parameterType="Required",
            direction="Input")

        # Parameter 2: Layer 2
        param2 = arcpy.Parameter(
            displayName="Layer 2 (Right/Bottom)",
            name="layer2",
            datatype="GPLayer",
            parameterType="Required",
            direction="Input")

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
        comparison_mode = parameters[0].valueAsText
        layer1 = parameters[1].value
        layer2 = parameters[2].value

        arcpy.AddMessage(f"Comparison mode: {comparison_mode}")
        arcpy.AddMessage(f"Layer 1: {layer1.name}")
        arcpy.AddMessage(f"Layer 2: {layer2.name}")

        try:
            if comparison_mode == "Swipe Tool":
                self._setup_swipe(layer1, layer2)
            else:
                self._setup_side_by_side(layer1, layer2)

        except Exception as e:
            arcpy.AddError(f"Comparison setup failed: {e}")
            import traceback
            arcpy.AddError(traceback.format_exc())

        return

    def _setup_swipe(self, layer1, layer2):
        """Setup swipe tool for two layers."""
        arcpy.AddMessage("\nSetting up Swipe Tool:")
        arcpy.AddMessage("1. Both layers are now visible in your map")
        arcpy.AddMessage("2. To enable Swipe:")
        arcpy.AddMessage("   - Go to 'Map' tab → 'Exploratory Analysis' → 'Swipe'")
        arcpy.AddMessage(f"   - Select '{layer2.name}' as the swipe layer")
        arcpy.AddMessage(f"   - '{layer1.name}' will be visible on the other side")
        arcpy.AddMessage("3. Drag the swipe line to compare the layers")

        # Ensure both layers are visible
        layer1.visible = True
        layer2.visible = True

        # Get current map and zoom to combined extent
        aprx = arcpy.mp.ArcGISProject("CURRENT")
        map_obj = aprx.activeMap

        # Get map view
        map_view = aprx.activeView
        if map_view:
            # Zoom to layer1 extent
            map_view.camera.setExtent(map_view.getLayerExtent(layer1))

        arcpy.AddMessage("\n✓ Layers prepared for swipe comparison")

    def _setup_side_by_side(self, layer1, layer2):
        """Setup side-by-side comparison (requires manual map frame setup)."""
        arcpy.AddMessage("\nSide-by-Side comparison setup:")
        arcpy.AddMessage("This mode requires manual setup in ArcGIS Pro Layout view:")
        arcpy.AddMessage("\n1. Create a new Layout:")
        arcpy.AddMessage("   - Insert → New Layout → Choose size")
        arcpy.AddMessage("\n2. Add two Map Frames:")
        arcpy.AddMessage("   - Insert → Map Frame → Select your map (twice)")
        arcpy.AddMessage("   - Position them side-by-side")
        arcpy.AddMessage("\n3. In each Map Frame:")
        arcpy.AddMessage(f"   - Left frame: Show only '{layer1.name}'")
        arcpy.AddMessage(f"   - Right frame: Show only '{layer2.name}'")
        arcpy.AddMessage("   - Right-click frame → Properties → Extent → Link to same extent")
        arcpy.AddMessage("\n4. Synchronize extents:")
        arcpy.AddMessage("   - Right-click one frame → Activate")
        arcpy.AddMessage("   - Navigate to desired extent")
        arcpy.AddMessage("   - Both frames will update if linked")

        # Ensure both layers are visible
        layer1.visible = True
        layer2.visible = True

        arcpy.AddMessage("\n✓ Layers are visible and ready for side-by-side comparison")
