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
        self.tools = [LoadALARMData, UpdateOverview, ApplySymbology]


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
        
        # Parameter 4: Minimum Elevation (optional filter)
        param4 = arcpy.Parameter(
            displayName="Minimum Elevation (m)",
            name="elev_min",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input")
        
        # Parameter 5: Maximum Elevation (optional filter)
        param5 = arcpy.Parameter(
            displayName="Maximum Elevation (m)",
            name="elev_max",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input")
        
        # Parameter 6: Aspect Filter Type
        param6 = arcpy.Parameter(
            displayName="Aspect Filter Type",
            name="aspect_type",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        
        param6.filter.type = "ValueList"
        param6.filter.list = ["None", "Cardinal Directions", "Degree Range"]
        param6.value = "None"
        
        # Parameter 7: Cardinal Directions (multi-select)
        param7 = arcpy.Parameter(
            displayName="Cardinal Directions",
            name="cardinal_dirs",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True)
        
        param7.filter.type = "ValueList"
        param7.filter.list = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        param7.enabled = False
        
        # Parameter 8: Aspect Min (degrees)
        param8 = arcpy.Parameter(
            displayName="Aspect Min (degrees)",
            name="aspect_min",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input")
        
        param8.filter.type = "Range"
        param8.filter.list = [0, 360]
        param8.enabled = False
        
        # Parameter 9: Aspect Max (degrees)
        param9 = arcpy.Parameter(
            displayName="Aspect Max (degrees)",
            name="aspect_max",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input")
        
        param9.filter.type = "Range"
        param9.filter.list = [0, 360]
        param9.enabled = False
        
        return [param0, param1, param2, param3, param4, param5, param6, param7, param8, param9]

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal
        validation is performed."""
        # Enable/disable aspect parameters based on filter type
        if parameters[6].value:  # aspect_type
            aspect_type = parameters[6].valueAsText
            
            if aspect_type == "Cardinal Directions":
                parameters[7].enabled = True  # cardinal_dirs
                parameters[8].enabled = False  # aspect_min
                parameters[9].enabled = False  # aspect_max
            elif aspect_type == "Degree Range":
                parameters[7].enabled = False  # cardinal_dirs
                parameters[8].enabled = True   # aspect_min
                parameters[9].enabled = True   # aspect_max
            else:  # "None"
                parameters[7].enabled = False
                parameters[8].enabled = False
                parameters[9].enabled = False
        
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
        
        # Get filter parameters
        elev_min = parameters[4].value
        elev_max = parameters[5].value
        aspect_type = parameters[6].valueAsText if parameters[6].value else "None"
        cardinal_dirs = parameters[7].valueAsText.split(';') if parameters[7].value else []
        cardinal_dirs = [d.strip().strip("'\"") for d in cardinal_dirs] if cardinal_dirs else []
        aspect_min = parameters[8].value
        aspect_max = parameters[9].value
        
        arcpy.AddMessage(f"Loading data for {region}, Scenario {scenario_id}")
        arcpy.AddMessage(f"Data types to load: {data_types}")
        
        # Build filter query if filters are specified
        filter_query = self._build_filter_query(elev_min, elev_max, aspect_type, cardinal_dirs, aspect_min, aspect_max)
        if filter_query:
            arcpy.AddMessage(f"Applying filters: {filter_query}")
        
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
                if filter_query:
                    layer.definitionQuery = filter_query
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
                if filter_query:
                    layer.definitionQuery = filter_query
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
                    if filter_query:
                        layer.definitionQuery = filter_query
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

    def _build_filter_query(self, elev_min, elev_max, aspect_type, cardinal_dirs, aspect_min, aspect_max):
        """Build SQL WHERE clause for filtering based on elevation and aspect."""
        conditions = []
        
        # Elevation filter
        if elev_min is not None:
            conditions.append(f"elev_mean >= {elev_min}")
        if elev_max is not None:
            conditions.append(f"elev_mean <= {elev_max}")
        
        # Aspect filter
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
                            aspect_conditions.append(f"(aspect_mea >= {range_tuple[0]} AND aspect_mea < {range_tuple[1]})")
            
            if aspect_conditions:
                conditions.append(f"({' OR '.join(aspect_conditions)})")
        
        elif aspect_type == "Degree Range" and aspect_min is not None and aspect_max is not None:
            # Handle wrapping around 0/360 degrees
            if aspect_min <= aspect_max:
                conditions.append(f"(aspect_mea >= {aspect_min} AND aspect_mea <= {aspect_max})")
            else:
                # Wraps around (e.g., 350 to 10 degrees)
                conditions.append(f"(aspect_mea >= {aspect_min} OR aspect_mea <= {aspect_max})")
        
        # Combine all conditions
        if conditions:
            return " AND ".join(conditions)
        return None

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
                # Update to classified colorizer
                if sym.colorizer.type != 'RasterClassifyColorizer':
                    sym.updateColorizer('RasterClassifyColorizer')
                
                # Set classification field and break count
                sym.colorizer.classificationField = "Value"
                sym.colorizer.breakCount = 5
                
                # First use EqualInterval to initialize breaks
                sym.colorizer.classificationMethod = 'EqualInterval'
                
                # Now switch to ManualInterval
                sym.colorizer.classificationMethod = 'ManualInterval'
                
                # Define breaks (upper bounds) and colors
                breaks = [1, 10, 25, 50, 200]
                colors = [
                    {'RGB': [176, 244, 250, 100]},  # #b0f4fa - light blue (0.1-1)
                    {'RGB': [117, 193, 101, 100]},  # #75c165 - green (1-10)
                    {'RGB': [169, 108, 0, 100]},    # #a96c00 - orange (10-25)
                    {'RGB': [139, 0, 105, 100]},    # #8b0069 - purple (25-50)
                    {'RGB': [100, 0, 75, 100]}      # darker purple (50-200)
                ]
                
                # Set breaks and colors for each class
                for i in range(min(len(breaks), len(sym.colorizer.classBreaks))):
                    sym.colorizer.classBreaks[i].upperBound = breaks[i]
                    if i < len(colors):
                        sym.colorizer.classBreaks[i].color = colors[i]
                        if i == 0:
                            sym.colorizer.classBreaks[i].label = f"0.1 - {breaks[i]} kPa"
                        else:
                            sym.colorizer.classBreaks[i].label = f"{breaks[i-1]} - {breaks[i]} kPa"
                
                # Set lower bound to exclude values below 0.1 (AFTER setting breaks)
                sym.colorizer.classBreaks[0].lowerBound = 0.1
                
                # Apply symbology
                layer.symbology = sym
                layer.transparency = 30
            
            arcpy.AddMessage("Applied PPR symbology")
        except Exception as e:
            arcpy.AddWarning(f"Could not apply PPR symbology: {e}")

    def _apply_tracks_symbology(self, layer):
        """Apply tracks symbology to polygon layer."""
        try:
            sym = layer.symbology
            if hasattr(sym, 'renderer'):
                # Set to graduated colors
                sym.updateRenderer('GraduatedColorsRenderer')
                sym.renderer.classificationField = "med_pres"
                sym.renderer.breakCount = 5
                
                # First compute with EqualInterval to initialize breaks
                sym.renderer.classificationMethod = "EqualInterval"
                
                # Now switch to Manual and set our custom breaks
                sym.renderer.classificationMethod = "Manual"
                
                # Define breaks (0 to >500 kPa) - these are upper bounds
                breaks = [50, 100, 200, 500, 99999]
                
                # Define colors
                colors = [
                    {'RGB': [224, 243, 255, 100]},  # #e0f3ff - very light blue (0-50)
                    {'RGB': [153, 214, 255, 100]},  # #99d6ff - light blue (50-100)
                    {'RGB': [77, 166, 255, 100]},   # #4da6ff - medium blue (100-200)
                    {'RGB': [0, 102, 204, 100]},    # #0066cc - dark blue (200-500)
                    {'RGB': [0, 61, 122, 100]}      # #003d7a - very dark blue (>500)
                ]
                
                # Apply breaks and colors to each class
                for i in range(min(len(breaks), len(sym.renderer.classBreaks))):
                    sym.renderer.classBreaks[i].upperBound = breaks[i]
                    if i < len(colors):
                        sym.renderer.classBreaks[i].symbol.color = colors[i]
                        if i == len(breaks) - 1:
                            sym.renderer.classBreaks[i].label = f"> {breaks[i-1]}"
                        else:
                            sym.renderer.classBreaks[i].label = f"{0 if i == 0 else breaks[i-1]} - {breaks[i]}"
                
                layer.symbology = sym
                layer.transparency = 10
            
            arcpy.AddMessage("Applied tracks symbology")
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


class ApplySymbology(object):
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Apply Symbology"
        self.description = "Apply standard ALARM symbology to selected layers"
        self.canRunInBackground = False

    def getParameterInfo(self):
        """Define parameter definitions"""
        
        # Parameter 0: Layer
        param0 = arcpy.Parameter(
            displayName="Layer",
            name="layer",
            datatype="GPLayer",
            parameterType="Required",
            direction="Input")
        
        # Parameter 1: Symbology type
        param1 = arcpy.Parameter(
            displayName="Symbology Type",
            name="symbology_type",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        
        param1.filter.type = "ValueList"
        param1.filter.list = ["PPR Raster", "Tracks", "PRAs", "Risk Assessment"]
        
        return [param0, param1]

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
        
        layer = parameters[0].value
        symbology_type = parameters[1].valueAsText
        
        arcpy.AddMessage(f"Applying {symbology_type} symbology to {layer.name}")
        
        # Apply appropriate symbology
        if symbology_type == "PPR Raster":
            self._apply_ppr_symbology(layer)
        elif symbology_type == "Tracks":
            self._apply_tracks_symbology(layer)
        elif symbology_type == "PRAs":
            self._apply_pra_symbology(layer)
        elif symbology_type == "Risk Assessment":
            self._apply_risk_symbology(layer)
        
        arcpy.AddMessage("Symbology applied successfully!")
        
        return

    def _apply_ppr_symbology(self, layer):
        """Apply PPR symbology."""
        try:
            sym = layer.symbology
            if hasattr(sym, 'colorizer'):
                # Update to classified colorizer
                if sym.colorizer.type != 'RasterClassifyColorizer':
                    sym.updateColorizer('RasterClassifyColorizer')
                
                # Set classification field and break count
                sym.colorizer.classificationField = "Value"
                sym.colorizer.breakCount = 5
                
                # First use EqualInterval to initialize breaks
                sym.colorizer.classificationMethod = 'EqualInterval'
                
                # Now switch to ManualInterval
                sym.colorizer.classificationMethod = 'ManualInterval'
                
                # Define breaks (upper bounds) and colors
                breaks = [1, 10, 25, 50, 200]
                colors = [
                    {'RGB': [176, 244, 250, 100]},  # #b0f4fa - light blue (0.1-1)
                    {'RGB': [117, 193, 101, 100]},  # #75c165 - green (1-10)
                    {'RGB': [169, 108, 0, 100]},    # #a96c00 - orange (10-25)
                    {'RGB': [139, 0, 105, 100]},    # #8b0069 - purple (25-50)
                    {'RGB': [100, 0, 75, 100]}      # darker purple (50-200)
                ]
                
                # Set breaks and colors for each class
                for i in range(min(len(breaks), len(sym.colorizer.classBreaks))):
                    sym.colorizer.classBreaks[i].upperBound = breaks[i]
                    if i < len(colors):
                        sym.colorizer.classBreaks[i].color = colors[i]
                        if i == 0:
                            sym.colorizer.classBreaks[i].label = f"0.1 - {breaks[i]} kPa"
                        else:
                            sym.colorizer.classBreaks[i].label = f"{breaks[i-1]} - {breaks[i]} kPa"
                
                # Set lower bound to exclude values below 0.1 (AFTER setting breaks)
                sym.colorizer.classBreaks[0].lowerBound = 0.1
                
                layer.symbology = sym
                layer.transparency = 30
            
            arcpy.AddMessage("Applied PPR symbology (70% opacity)")
        except Exception as e:
            arcpy.AddError(f"Error: {e}")

    def _apply_tracks_symbology(self, layer):
        """Apply tracks symbology."""
        try:
            sym = layer.symbology
            sym.updateRenderer('GraduatedColorsRenderer')
            sym.renderer.classificationField = "med_pres"
            sym.renderer.breakCount = 5
            
            # First compute with EqualInterval to initialize breaks
            sym.renderer.classificationMethod = "EqualInterval"
            
            # Now switch to Manual and set our custom breaks
            sym.renderer.classificationMethod = "Manual"
            
            # Define breaks (0 to >500 kPa) - these are upper bounds
            breaks = [50, 100, 200, 500, 99999]
            
            # Define colors
            colors = [
                {'RGB': [224, 243, 255, 100]},  # #e0f3ff - very light blue (0-50)
                {'RGB': [153, 214, 255, 100]},  # #99d6ff - light blue (50-100)
                {'RGB': [77, 166, 255, 100]},   # #4da6ff - medium blue (100-200)
                {'RGB': [0, 102, 204, 100]},    # #0066cc - dark blue (200-500)
                {'RGB': [0, 61, 122, 100]}      # #003d7a - very dark blue (>500)
            ]
            
            # Apply breaks and colors
            for i in range(min(len(breaks), len(sym.renderer.classBreaks))):
                sym.renderer.classBreaks[i].upperBound = breaks[i]
                if i < len(colors):
                    sym.renderer.classBreaks[i].symbol.color = colors[i]
                    if i == len(breaks) - 1:
                        sym.renderer.classBreaks[i].label = f"> {breaks[i-1]}"
                    else:
                        sym.renderer.classBreaks[i].label = f"{0 if i == 0 else breaks[i-1]} - {breaks[i]}"
            
            layer.symbology = sym
            layer.transparency = 10
            arcpy.AddMessage("Applied tracks symbology (90% opacity, blue gradient 0-500+ kPa)")
        except Exception as e:
            arcpy.AddError(f"Error: {e}")

    def _apply_pra_symbology(self, layer):
        """Apply PRA symbology."""
        try:
            sym = layer.symbology
            sym.updateRenderer('SimpleRenderer')
            symbol = sym.renderer.symbol
            symbol.color = {'RGB': [0, 0, 0, 0]}
            symbol.outlineColor = {'RGB': [0, 0, 0, 100]}
            symbol.outlineWidth = 1.5
            layer.symbology = sym
            arcpy.AddMessage("Applied PRA symbology (black outline, no fill)")
        except Exception as e:
            arcpy.AddError(f"Error: {e}")

    def _apply_risk_symbology(self, layer):
        """Apply risk assessment symbology."""
        try:
            sym = layer.symbology
            sym.updateRenderer('GraduatedColorsRenderer')
            sym.renderer.classificationField = "max_ppr"
            sym.renderer.breakCount = 5
            
            # First compute with EqualInterval to initialize breaks
            sym.renderer.classificationMethod = "EqualInterval"
            
            # Now switch to Manual and set our custom breaks
            sym.renderer.classificationMethod = "Manual"
            
            # Define breaks (upper bounds) and colors
            breaks = [25, 50, 100, 200, 10000]
            colors = [
                {'RGB': [255, 179, 217, 100]},  # #ffb3d9 - light pink (0-25)
                {'RGB': [255, 102, 179, 100]},  # #ff66b3 - pink (25-50)
                {'RGB': [255, 0, 128, 100]},    # #ff0080 - magenta (50-100)
                {'RGB': [204, 0, 102, 100]},    # #cc0066 - dark magenta (100-200)
                {'RGB': [153, 0, 80, 100]}      # #990050 - very dark magenta (>200)
            ]
            
            # Apply breaks and colors
            for i in range(min(len(breaks), len(sym.renderer.classBreaks))):
                sym.renderer.classBreaks[i].upperBound = breaks[i]
                if i < len(colors):
                    sym.renderer.classBreaks[i].symbol.color = colors[i]
                    sym.renderer.classBreaks[i].label = f"{0 if i == 0 else breaks[i-1]} - {breaks[i]}"
            
            layer.symbology = sym
            layer.transparency = 0
            arcpy.AddMessage("Applied risk assessment symbology (magenta/pink scale, 100% opacity)")
        except Exception as e:
            arcpy.AddError(f"Error: {e}")
