"""
ALARM Tools - ArcGIS Pro Python Toolbox
========================================
Tools for loading and managing ALARM regional avalanche data.

Tools:
1. Load ALARM Data - Load specific region and scenario into current map
2. Update Overview - Regenerate HTML overview page
3. Apply Symbology - Apply standard ALARM symbology to selected layers

Author: ALARM Pipeline
Date: 2026-04-07
"""

import arcpy
import os
from pathlib import Path
import subprocess
import sys


class Toolbox(object):
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the .pyt file)."""
        self.label = "ALARM Tools"
        self.alias = "ALARM"
        self.description = "Tools for loading and managing ALARM regional avalanche data"
        
        # List of tool classes associated with this toolbox
        self.tools = [LoadALARMData, FilterLayers, UpdateOverview]


class LoadALARMData(object):
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Load ALARM Data"
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
        param2.filter.list = ["PPR Raster", "Tracks", "PRAs", "Risk Assessment"]
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
        
        # Create group layer if requested
        group_layer = None
        if use_group:
            group_name = f"{region} - Scenario {scenario_id}"
            arcpy.AddMessage(f"Creating group layer: {group_name}")
            # Note: Group layers are created by adding layers to them
        
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
        
        # Load Tracks
        if "Tracks" in data_types:
            tracks_file = self._find_file(scenario_dir, "tracks_*.shp")
            if tracks_file:
                arcpy.AddMessage(f"Loading tracks: {tracks_file.name}")
                layer = map_obj.addDataFromPath(str(tracks_file))
                self._apply_tracks_symbology(layer)
                # Add spatial index for performance
                arcpy.AddSpatialIndex_management(layer)
                layers_added.append(layer)
            else:
                arcpy.AddWarning("Tracks shapefile not found")
        
        # Load PRAs
        if "PRAs" in data_types:
            pra_file = self._find_file(scenario_dir, "pra_*.shp")
            if pra_file:
                arcpy.AddMessage(f"Loading PRAs: {pra_file.name}")
                layer = map_obj.addDataFromPath(str(pra_file))
                self._apply_pra_symbology(layer)
                # Add spatial index for performance
                arcpy.AddSpatialIndex_management(layer)
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
                    # Add spatial index for performance
                    arcpy.AddSpatialIndex_management(layer)
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
                # Create group layer
                group_layer = map_obj.createGroupLayer(group_name)
                
                # Add layers to group (this creates copies in the group)
                for lyr in layers_added:
                    map_obj.addLayerToGroup(group_layer, lyr)
                
                # Remove original layers (they're now in the group)
                for lyr in layers_added:
                    map_obj.removeLayer(lyr)
                    
                arcpy.AddMessage(f"Created group layer: {group_name}")
            except Exception as e:
                arcpy.AddWarning(f"Could not create group layer: {e}")
        
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
                
                # Step 3: Define custom breaks, colors and labels
                breaks = [1, 10, 25, 50, 99999]
                colors = [
                    {'HSV': [186, 30, 98, 100]},   # light blue (0.1-1)
                    {'HSV': [107, 49, 76, 100]},   # green (1-10)
                    {'HSV': [28, 100, 66, 100]},    # orange (10-25)
                    {'HSV': [310, 100, 55, 100]},   # purple (25-50)
                    {'HSV': [320, 100, 39, 100]}    # darker purple (>50)
                ]
                labels = [
                    "0.1 - 1 kPa",
                    "1 - 10 kPa",
                    "10 - 25 kPa",
                    "25 - 50 kPa",
                    "> 50 kPa"
                ]
                
                arcpy.AddMessage(f"  PPR classBreaks available: {len(sym.colorizer.classBreaks)}")
                
                # Step 4: Iterate through classBreaks (official Esri pattern)
                for i, brk in enumerate(sym.colorizer.classBreaks):
                    if i < len(breaks):
                        brk.upperBound = breaks[i]
                        brk.color = colors[i]
                        brk.label = labels[i]
                        arcpy.AddMessage(f"  Set break {i}: upper={breaks[i]}, label={labels[i]}")
                
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
        self.label = "Update Overview"
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
        self.label = "Filter Layers"
        self.description = "Apply filters to ALARM layers (Tracks, PRAs, Risk Assessment)"
        self.canRunInBackground = False

    def getParameterInfo(self):
        """Define parameter definitions"""
        
        # Parameter 0: Layers to filter (multi-select)
        param0 = arcpy.Parameter(
            displayName="Layers to Filter",
            name="layers_to_filter",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True)
        
        param0.filter.type = "ValueList"
        param0.filter.list = ["Tracks", "PRAs", "Risk Assessment"]
        
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
        
        return [param0, param1, param2, param3, param4, param5, param6, param7, param8]

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
        layers_to_filter = [l.strip().strip("'\"") for l in parameters[0].valueAsText.split(';')]
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
        
        arcpy.AddMessage(f"Filtering layers: {', '.join(layers_to_filter)}")
        
        # Get current map
        aprx = arcpy.mp.ArcGISProject("CURRENT")
        map_obj = aprx.activeMap
        
        if not map_obj:
            arcpy.AddError("No active map found. Please open a map in ArcGIS Pro.")
            return
        
        # Apply filters to selected layers
        layers_filtered = 0
        for layer in map_obj.listLayers():
            if not layer.isFeatureLayer:
                continue
                
            layer_name = layer.name.lower()
            
            # Determine layer type and build appropriate filter
            filter_query = None
            
            if "Tracks" in layers_to_filter and "track" in layer_name:
                # Tracks: pra_elev, pra_aspdeg
                filter_query = self._build_filter_query(elev_min, elev_max, aspect_type, cardinal_dirs, aspect_min, aspect_max, "pra_elev", "pra_aspdeg")
                
            elif "PRAs" in layers_to_filter and "pra_" in layer_name and "track" not in layer_name:
                # PRAs: elev_med, aspect_deg
                filter_query = self._build_filter_query(elev_min, elev_max, aspect_type, cardinal_dirs, aspect_min, aspect_max, "elev_med", "aspect_deg")
                
            elif "Risk Assessment" in layers_to_filter and "risk" in layer_name:
                # Risk Assessment: pra_elev, pra_aspct (but aspect is string, skip aspect filter)
                # Add building-specific filters
                filter_query = self._build_risk_filter_query(elev_min, elev_max, saf_classes, min_max_ppr)
            
            if filter_query:
                try:
                    layer.definitionQuery = filter_query
                    arcpy.AddMessage(f"  Applied filter to: {layer.name}")
                    arcpy.AddMessage(f"    Query: {filter_query}")
                    layers_filtered += 1
                except Exception as e:
                    arcpy.AddWarning(f"  Could not filter {layer.name}: {e}")
        
        if layers_filtered == 0:
            arcpy.AddWarning("No matching layers found in current map.")
        else:
            arcpy.AddMessage(f"Successfully filtered {layers_filtered} layer(s)")
        
        return

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
