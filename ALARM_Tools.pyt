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
import shutil
import sys
import tempfile
import uuid
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
import alarm_core.kommune as _kommune
import alarm_core.webmap as _webmap

# ArcGIS Pro keeps imported modules for the whole session. Reloading them here makes
# "Refresh" of the toolbox pick up edits without restarting Pro.
for _module in (_config, _data, _dbf, _filters, _kommune, _compare, _report, _webmap):
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
_FILTER_PARAMS = dict(any=0, kommuner=1, elev_min=2, elev_max=3, aspect_type=4, cardinal=5, aspect_min=6,
                      aspect_max=7, saf_classes=8, min_max_ppr=9)
_COMPARE_PARAMS = dict(kommuner=3, elev_min=5, elev_max=6, aspect_type=7, cardinal=8, aspect_min=9, aspect_max=10,
                       saf_classes=11, min_max_ppr=12)


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
        min_max_ppr=p('min_max_ppr').value,
        kommuner=_split_values(p('kommuner').valueAsText) if 'kommuner' in index else None)


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


OTHER_FOLDER = "Other folder..."
NO_REGIONS = "No regions found"
SELECT_REGIONS_FIRST = "Select regions first"


def _by_name(parameters):
    """The tool parameters by name (the order changes more easily than the names)."""
    return {param.name: param for param in parameters}


def _source_label(name, folder):
    return f"{name}  ({folder})"


def _make_source_params(cfg):
    """The 'Data Source' choice and the folder for 'Other folder...' (first two dialog parameters)."""
    labels = [_source_label(name, folder) for name, folder in cfg['sources'].items()]
    source = arcpy.Parameter(displayName="Data Source", name="source", datatype="GPString",
                             parameterType="Required", direction="Input")
    source.filter.type = "ValueList"
    source.filter.list = labels + [OTHER_FOLDER]
    source.value = labels[0]

    folder = arcpy.Parameter(displayName="Data Folder (for 'Other folder...')", name="source_folder",
                             datatype="DEFolder", parameterType="Optional", direction="Input")
    folder.enabled = False
    return source, folder


def _selected_source(source, folder, cfg):
    """(name, base folder) of the chosen data source; the folder is None if it is not set yet."""
    text = source.valueAsText or ""
    if text == OTHER_FOLDER:
        chosen = folder.valueAsText
        return OTHER_FOLDER, (Path(chosen) if chosen else None)
    for name, path in cfg['sources'].items():
        if text == _source_label(name, path):
            return name, Path(path)
    return _config.STANDARD_SOURCE, Path(cfg['results_base'])


def _source_tag(name, base):
    """Short tag for names of layers / groups of a non-standard source ('' for the standard results).

    A chosen folder is tagged with its own name, so two different folders do not share layer
    or cache names.
    """
    if name == _config.STANDARD_SOURCE:
        return ""
    label = base.name if name == OTHER_FOLDER and base is not None else name
    return re.sub(r"[^0-9A-Za-z_]", "_", label)


def _edited(param):
    """True if the user changed the parameter since the last validation."""
    return bool(param.altered and not param.hasBeenValidated)


def _scenario_options(name, base, regions, cfg):
    """Scenario choices ('A - description') for the chosen source and regions."""
    if name == _config.STANDARD_SOURCE:
        return [f"{k} - {v}" for k, v in cfg['scenarios'].items()]
    found = _data.discover_scenarios(base, regions) if base and regions else {}
    return [f"{k} - {v}" for k, v in found.items()] or [SELECT_REGIONS_FIRST]


def _refresh_source_dependent(source, folder, region, scenarios, cfg, multi_region, select_all_scenarios=False):
    """Keep the region and scenario lists in step with the chosen data source (updateParameters)."""
    folder.enabled = source.valueAsText == OTHER_FOLDER
    source_changed = _edited(source) or _edited(folder)
    regions_changed = _edited(region)
    if not (source_changed or regions_changed):
        return

    name, base = _selected_source(source, folder, cfg)
    if source_changed:
        found = _data.completed_regions(base) if base and base.is_dir() else []
        region.filter.list = found if found else [NO_REGIONS]
        keep = [r for r in _split_values(region.valueAsText) if r in found]
        region.value = (keep or None) if multi_region else (keep[0] if keep else None)

    options = _scenario_options(name, base, _split_values(region.valueAsText), cfg)
    scenarios.filter.list = options
    keep_ids = {o.split(' - ')[0] for o in options}
    kept = [v for v in _split_values(scenarios.valueAsText) if v.split(' - ')[0] in keep_ids]
    if not kept and select_all_scenarios and options != [SELECT_REGIONS_FIRST]:
        kept = options
    # the saved text may carry an older description; use the current one
    by_id = {o.split(' - ')[0]: o for o in options}
    scenarios.value = [by_id[v.split(' - ')[0]] for v in kept] or None


class _NoParam:
    valueAsText = None

    def setErrorMessage(self, message):
        pass


P_NONE = _NoParam()


def _check_source(source, folder, region, scenarios, cfg):
    """Errors for an unreachable data source or empty choices (updateMessages)."""
    name, base = _selected_source(source, folder, cfg)
    if source.valueAsText == OTHER_FOLDER:
        if base is None:
            folder.setErrorMessage("Choose the data folder (the one that contains the region folders).")
        elif not base.is_dir():
            folder.setErrorMessage(f"Folder not found: {base}")
    if region.valueAsText == NO_REGIONS:
        region.setErrorMessage(f"No regions found in {base if base else 'the data source'} - is the folder reachable "
                               f"(L: connected) and does it contain <region>/merged? See alarm_core/config.py.")
    if scenarios.valueAsText and SELECT_REGIONS_FIRST in scenarios.valueAsText:
        scenarios.setErrorMessage("Select the regions first; the scenarios are read from their folders.")


# --------------------------------------------------------------------- municipalities --
# The dialogs list municipalities from alarm_core/kommuner.json (no L: access). The exact
# boundaries come from the Kartverket dataset (config 'kommune_gdb') and are cached locally
# per municipality, since reading them over L: can take long.
_KOMMUNE_CACHE = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "ALARM_Tools" / "kommuner"


def _municipality_param(display_name="Municipalities (Kommuner)"):
    param = arcpy.Parameter(displayName=display_name, name="municipalities", datatype="GPString",
                            parameterType="Optional", direction="Input", multiValue=True)
    param.filter.type = "ValueList"
    param.filter.list = _kommune.labels_for(None)
    return param


def _layer_bbox(values):
    """Bounding box (EPSG:25833) of the given layers, or None."""
    boxes = []
    for value in values or []:
        try:
            extent = arcpy.Describe(value).extent
            if extent.spatialReference and extent.spatialReference.factoryCode not in (None, 0, 25833):
                extent = extent.projectAs(arcpy.SpatialReference(25833))
            boxes.append((extent.XMin, extent.YMin, extent.XMax, extent.YMax))
        except Exception:
            continue
    return _data.union_extent(boxes)


def _region_bbox(base, region):
    """Bounding box of a region's results, read from the shapefile headers (no arcpy)."""
    if not base or not region:
        return None
    merged = Path(base) / region / "merged"
    files = list(merged.glob("tracks_*.shp")) + list(merged.glob("*/tracks_*.shp")) \
        + list(merged.glob("*/risk_assessment/*.shp")) + list(merged.glob("risk_assessment/*.shp"))
    return _data.union_extent(_data.shp_extent(f) for f in files)


_REGION_BBOX = {}


def _region_bbox_cached(base, region):
    key = (str(base), region)
    if key not in _REGION_BBOX:
        _REGION_BBOX[key] = _region_bbox(base, region)
    return _REGION_BBOX[key]


def _kommune_bbox(labels):
    """Bounding box (EPSG:25833) of the selected municipalities, from the bundled list."""
    wanted = {_kommune.number_of(t) for t in labels}
    return _data.union_extent(k["bbox"] for k in _kommune.load_list() if k["nr"] in wanted)


def _regions_for_kommuner(base, labels, bbox=None):
    """Forecast regions of a data folder whose results overlap the municipalities' bounding box.

    The dialog uses the bundled list; loading passes the box of the real boundaries.
    """
    bbox = bbox or _kommune_bbox(labels)
    if not base or bbox is None:
        return []
    return [r for r in _data.completed_regions(base)
            if (lambda e: e is not None and _kommune.bbox_overlaps(e, bbox))(_region_bbox_cached(base, r))]


def _update_municipality_list(param, bbox):
    """Offer the municipalities that overlap bbox; keep what is still offered."""
    options = _kommune.labels_for(bbox) or _kommune.labels_for(None)
    param.filter.list = options
    kept = [v for v in _split_values(param.valueAsText) if v in options]
    param.value = kept or None


def _dataset_stamp(gdb):
    """Changes when the dataset's data change, not when it is only read.

    Reading a file geodatabase creates lock files in its folder, so the folder's own time
    changes all the time; the time of its table files (*.gdbtable) does not.
    """
    tables = list(gdb.glob("*.gdbtable"))
    return int(max(p.stat().st_mtime for p in tables)) if tables else int(gdb.stat().st_mtime)


def _kommune_geometry(cfg, labels):
    """Union of the boundaries of the selected municipalities (EPSG:25833)."""
    shapes = _kommune_shapes(cfg, labels)
    if not shapes:
        return None
    union = shapes[0][1]
    for _, shape in shapes[1:]:
        union = union.union(shape)
    return union


def _kommune_shapes(cfg, labels):
    """[(number, boundary)] of the selected municipalities (EPSG:25833), cached locally."""
    gdb = Path(cfg['kommune_gdb'])
    try:
        stamp = _dataset_stamp(gdb)
    except OSError:
        stamp = None  # dataset not reachable: use any cached copy
    _KOMMUNE_CACHE.mkdir(parents=True, exist_ok=True)
    shapes, missing = [], []
    for text in labels:
        nr = _kommune.number_of(text)
        if nr is None:
            arcpy.AddWarning(f"  Unknown municipality '{text}' - ignored")
            continue
        cached = _KOMMUNE_CACHE / f"{nr}_{stamp}.json"
        if stamp is None:
            older = sorted(_KOMMUNE_CACHE.glob(f"{nr}_*.json"))
            cached = older[-1] if older else cached
        if cached.exists():
            shapes.append((nr, arcpy.AsShape(cached.read_text(encoding="utf-8"), True)))
        else:
            missing.append((nr, cached))
    if missing:
        if stamp is None:
            raise RuntimeError(f"Municipality boundaries not reachable: {gdb}")
        arcpy.AddMessage(f"  Reading the boundaries of {len(missing)} municipality(ies) from {gdb.name} "
                         f"(once; cached in {_KOMMUNE_CACHE})")
        numbers = ", ".join(f"'{nr}'" for nr, _ in missing)
        found = {}
        with arcpy.da.SearchCursor(str(gdb / "kommune"), ["kommunenummer", "SHAPE@"],
                                   f"kommunenummer IN ({numbers})") as cursor:
            for nr, shape in cursor:
                found[nr] = found[nr].union(shape) if nr in found else shape
        for nr, cached in missing:
            if nr not in found:
                arcpy.AddWarning(f"  Municipality {nr} not found in {gdb.name} - ignored")
                continue
            cached.write_text(found[nr].JSON, encoding="utf-8")
            shapes.append((nr, found[nr]))
    return shapes


def _oids_inside(data, geometry):
    """Object IDs of the features of a layer or feature class that intersect geometry."""
    name = f"alarm_k_{uuid.uuid4().hex[:8]}"
    arcpy.management.MakeFeatureLayer(data, name)
    try:
        arcpy.management.SelectLayerByLocation(name, "INTERSECT", geometry)
        with arcpy.da.SearchCursor(name, ["OID@"]) as cursor:
            return {row[0] for row in cursor}
    finally:
        arcpy.management.Delete(name)


def _layer_oids_inside(layer, geometry):
    """Like _oids_inside for a map layer, on all its features (not only filter or selection)."""
    query = layer.definitionQuery or ""
    try:
        selection = layer.getSelectionSet()
    except Exception:
        selection = None
    try:
        layer.definitionQuery = ""
        if selection:
            layer.setSelectionSet([], "NEW")
        return _oids_inside(layer, geometry)
    finally:
        layer.definitionQuery = query
        if selection:
            layer.setSelectionSet(list(selection), "NEW")


_RESOLVABLE = {}


def _resolvable_shapefile(shp):
    """A path arcpy can open: shapefiles with a dot in the name are copied once under a clean name."""
    shp = Path(shp)
    if "." not in shp.stem:
        return shp
    key = (str(shp), shp.stat().st_mtime)
    if key not in _RESOLVABLE:
        target_dir = Path(tempfile.mkdtemp(prefix="alarm_shp_"))
        clean = shp.stem.replace(".", "_")
        for part in shp.parent.glob(shp.stem + ".*"):
            suffix = part.name[len(shp.stem):]
            if suffix.lower() in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
                shutil.copy2(part, target_dir / (clean + suffix))
        _RESOLVABLE[key] = target_dir / (clean + ".shp")
    return _RESOLVABLE[key]


def _filter_name(layer):
    """Name of the layer's active definition query (the readable description), or None."""
    try:
        for query in layer.listDefinitionQueries():
            if query.get('isActive'):
                return query.get('name') or None
    except Exception:
        pass
    return None


def _set_filter(layer, sql, name=None):
    """Set the layer's definition query; with a name (shown in Layer Properties and in reports)."""
    if not sql:
        try:
            layer.updateDefinitionQueries([])
        except Exception:
            layer.definitionQuery = ""
        return
    if name:
        try:
            layer.updateDefinitionQueries([{'name': name[:250], 'sql': sql, 'isActive': True}])
            return
        except Exception:
            pass
    layer.definitionQuery = sql


def _short_sql(sql, limit=300):
    return sql if len(sql) <= limit else f"{sql[:limit]}... ({len(sql)} characters)"


def _unique_layers(layers):
    """The layers without repeats (the same map layer can be found twice)."""
    seen, out = set(), []
    for layer in layers:
        key = (layer.longName, getattr(layer, "dataSource", None))
        if key not in seen:
            seen.add(key)
            out.append(layer)
    return out


# Name prefix of the municipality boundary layers that Load ALARM Data adds
KOMMUNE_LAYER_PREFIX = "Kommune: "


def _layers_of(param):
    """Map layers chosen in a (multi-value) layer parameter; values may be layer objects or names."""
    values = param.values if getattr(param, "values", None) else ([param.value] if param.value is not None else [])
    layers, names = [], []
    for value in values or []:
        if hasattr(value, "longName") and hasattr(value, "definitionQuery"):
            layers.append(value)
        else:
            names.append(str(value).strip().strip("'\""))
    if names:
        try:
            map_obj = arcpy.mp.ArcGISProject("CURRENT").activeMap
        except Exception:
            map_obj = None
        candidates = map_obj.listLayers() if map_obj else []
        for name in names:
            match = [l for l in candidates if l.isFeatureLayer and l.longName == name] or                     [l for l in candidates if l.isFeatureLayer and l.name == name]
            if match:
                layers.append(match[0])
            else:
                arcpy.AddWarning(f"Layer '{name}' not found in the active map - skipped")
    return layers


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
    MODE_REGIONS = "Forecast regions (Varslingsregioner)"
    MODE_KOMMUNER = "Municipalities (Kommuner)"

    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "1. Load ALARM Data"
        self.description = "Load ALARM data for a specific region and scenario into the current map"
        self.canRunInBackground = False

        # Configuration (see alarm_core/config.py; can be overridden in alarm_tools_config.json)
        cfg = _config.load_config()
        self.results_base = cfg['results_base']
        self.optimized_base = cfg['optimized_base']
        self.scenarios = cfg['scenarios']
        self.source_tag = ""  # '' = standard results; otherwise names layers and groups of other sources

    def getParameterInfo(self):
        """Define parameter definitions"""

        cfg = _config.load_config()
        source, source_folder = _make_source_params(cfg)

        # Load by forecast region or by municipality
        load_by = arcpy.Parameter(
            displayName="Load by",
            name="load_by",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        load_by.filter.type = "ValueList"
        load_by.filter.list = [self.MODE_REGIONS, self.MODE_KOMMUNER]
        load_by.value = self.MODE_REGIONS

        # Parameter: Regions (required in region mode; checked in updateMessages)
        param0 = arcpy.Parameter(
            displayName="Regions",
            name="region",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True)

        # Get list of completed regions
        regions = self._get_completed_regions()
        param0.filter.type = "ValueList"
        param0.filter.list = regions if regions else ["No regions found"]

        # Municipalities (municipality mode): the tool finds the regions and cuts them to the municipalities
        municipalities = _municipality_param()
        municipalities.enabled = False

        # Parameter 1: Scenario
        param1 = arcpy.Parameter(
            displayName="Scenarios",
            name="scenario",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True)

        param1.filter.type = "ValueList"
        param1.filter.list = [f"{k} - {v}" for k, v in self.scenarios.items()]

        # Parameter: Data types to load
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

        return [source, source_folder, load_by, param0, municipalities, param1, param2, param3]

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Follow the chosen data source and mode: regions or municipalities, and their scenarios."""
        p = _by_name(parameters)
        cfg = _config.load_config()
        kommune_mode = p['load_by'].valueAsText == self.MODE_KOMMUNER
        p['region'].enabled = not kommune_mode
        p['municipalities'].enabled = kommune_mode
        _refresh_source_dependent(p['source'], p['source_folder'], p['region'], p['scenario'],
                                  cfg, multi_region=True)
        if kommune_mode and (_edited(p['municipalities']) or _edited(p['load_by'])
                             or _edited(p['source']) or _edited(p['source_folder'])):
            name, base = _selected_source(p['source'], p['source_folder'], cfg)
            if name == _config.STANDARD_SOURCE:
                options = [f"{k} - {v}" for k, v in cfg['scenarios'].items()]
            else:
                kommuner = _split_values(p['municipalities'].valueAsText)
                regions = _regions_for_kommuner(base, kommuner) if kommuner else []
                found = _data.discover_scenarios(base, regions) if regions else {}
                options = [f"{k} - {v}" for k, v in found.items()] or [SELECT_REGIONS_FIRST]
            p['scenario'].filter.list = options
            by_id = {o.split(' - ')[0]: o for o in options}
            kept = [by_id[v.split(' - ')[0]] for v in _split_values(p['scenario'].valueAsText)
                    if v.split(' - ')[0] in by_id]
            p['scenario'].value = kept or None
        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter."""
        p = _by_name(parameters)
        if p['load_by'].valueAsText == self.MODE_KOMMUNER:
            if not p['municipalities'].valueAsText:
                p['municipalities'].setErrorMessage("Select at least one municipality.")
            elif p['scenario'].valueAsText and SELECT_REGIONS_FIRST in p['scenario'].valueAsText:
                p['scenario'].setErrorMessage("No results in this data source overlap these municipalities.")
            _check_source(p['source'], p['source_folder'], p['municipalities'], P_NONE, _config.load_config())
        else:
            if not p['region'].valueAsText:
                p['region'].setErrorMessage("Select at least one region.")
            _check_source(p['source'], p['source_folder'], p['region'], p['scenario'], _config.load_config())
        return

    def execute(self, parameters, messages):
        """Load every selected region/scenario combination into the active map."""
        p = _by_name(parameters)
        cfg = _config.load_config()
        source_name, base = _selected_source(p['source'], p['source_folder'], cfg)
        if base is None or not base.is_dir():
            arcpy.AddError(f"Data folder not found: {base}")
            return
        # All lookups of this run use the chosen data folder. Optimized copies belong to the
        # standard results only.
        self.results_base = base
        self.optimized_base = cfg['optimized_base'] if source_name == _config.STANDARD_SOURCE else None
        self.source_tag = _source_tag(source_name, base)
        arcpy.AddMessage(f"Data source: {source_name} ({base})")

        regions = _split_values(p['region'].valueAsText)
        scenario_ids = [v.split(' - ')[0] for v in _split_values(p['scenario'].valueAsText)]
        data_types = _split_values(p['data_types'].valueAsText)
        use_group = p['use_group'].value

        aprx = arcpy.mp.ArcGISProject("CURRENT")
        map_obj = aprx.activeMap
        if not map_obj:
            arcpy.AddError("No active map found. Please open a map in ArcGIS Pro.")
            return

        if p['load_by'].valueAsText == self.MODE_KOMMUNER:
            self._load_kommuner(cfg, _split_values(p['municipalities'].valueAsText), scenario_ids, data_types,
                                use_group, aprx, map_obj)
            return

        combinations = [(r, sid) for r in regions for sid in scenario_ids]
        arcpy.AddMessage(f"Loading {len(combinations)} region/scenario combination(s): "
                         f"{len(regions)} region(s) x {len(scenario_ids)} scenario(s)")
        arcpy.AddMessage(f"Data types to load: {data_types}")
        if "PRAs" in data_types and len(combinations) > 1:
            arcpy.AddMessage("PRAs are converted once per region/scenario (about a minute for a large region); "
                             "later loads use the cached copy.")

        total_layers = 0
        missing = []
        for number, (region, scenario_id) in enumerate(combinations, start=1):
            arcpy.AddMessage("")
            arcpy.AddMessage(f"[{number}/{len(combinations)}] {region}, Scenario {scenario_id}")
            scenario_dir = self._find_scenario_dir(region, scenario_id)
            if not scenario_dir:
                arcpy.AddWarning(f"  No data found for {region}, Scenario {scenario_id} - skipped")
                missing.append(f"{region} / {scenario_id}")
                continue
            total_layers += self._load_scenario(region, scenario_id, scenario_dir, data_types, use_group,
                                                aprx, map_obj)

        arcpy.AddMessage("")
        arcpy.AddMessage(f"Successfully loaded {total_layers} layers from "
                         f"{len(combinations) - len(missing)} of {len(combinations)} combination(s)")
        if missing:
            arcpy.AddWarning(f"No data for: {', '.join(missing)}")
        return

    def _load_scenario(self, region, scenario_id, scenario_dir, data_types, use_group, aprx, map_obj):
        """Load the selected data of one region/scenario; returns the number of layers added."""
        arcpy.AddMessage(f"Found data directory: {scenario_dir}")

        layers_added = []

        # Load PPR Raster
        if "PPR Raster" in data_types:
            ppr_file = self._find_file(scenario_dir, "ppr_*.tif")
            ppr_copy = self._optimized(ppr_file)
            if ppr_file and self._already_loaded(map_obj, ppr_file, ppr_copy):
                pass
            elif ppr_file:
                arcpy.AddMessage(f"Loading PPR raster: {ppr_file.name}")
                layer = self._add(map_obj, ppr_file, ppr_copy)
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
                raster_copy = self._optimized(raster_file)
                if raster_file and self._already_loaded(map_obj, raster_file, raster_copy):
                    pass
                elif raster_file:
                    arcpy.AddMessage(f"Loading {label}: {raster_file.name}")
                    layer = self._add(map_obj, raster_file, raster_copy)
                    self._apply_lyrx(layer, raster_file.with_suffix(".lyrx"))
                    layers_added.append(layer)
                else:
                    arcpy.AddWarning(f"{label} not found")

        # Load Tracks
        if "Tracks" in data_types:
            tracks_file = self._find_file(scenario_dir, "tracks_*.shp")
            tracks_copy = self._optimized(tracks_file)
            if tracks_file and self._already_loaded(map_obj, tracks_file, tracks_copy):
                pass
            elif tracks_file:
                arcpy.AddMessage(f"Loading tracks: {tracks_file.name}")
                layer = self._add(map_obj, tracks_file, tracks_copy)
                self._apply_tracks_symbology(layer)
                layers_added.append(layer)
            else:
                arcpy.AddWarning("Tracks shapefile not found")

        # Load PRAs - Convert to File Geodatabase to fix String field types
        if "PRAs" in data_types:
            pra_file = self._find_file(scenario_dir, "pra_*.shp")
            if pra_file:
                arcpy.AddMessage(f"Loading PRAs: {pra_file.name}")
                base_name = re.sub(r"[^0-9A-Za-z_]", "_", f"pra_{region}_{scenario_id}")
                if self.source_tag:
                    base_name += f"_s_{self.source_tag}"        # a second data source must not share the cache
                pra_copy = self._optimized(pra_file)

                if pra_copy is not None:
                    # The optimized GeoPackage already has numeric fields; no conversion needed.
                    fc_path = str(pra_copy)
                    arcpy.AddMessage(f"  From the optimized copy (numeric fields): {fc_path}")
                else:
                    self._note_missing_copy()
                    gdb_path = aprx.defaultGeodatabase

                    # The converted copy is cached in the project geodatabase. The name carries
                    # the modification time and size of the shapefile, so the cache is reused
                    # as long as the source is unchanged and rebuilt automatically when it changes.
                    # (GDB names must not contain - or .)
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

                # Load the numeric copy instead of the shapefile
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
                risk_file = _data.find_risk_file(risk_dir, warn=arcpy.AddWarning)
                risk_copy = self._optimized(risk_file)
                if risk_file and self._already_loaded(map_obj, risk_file, risk_copy):
                    pass
                elif risk_file:
                    arcpy.AddMessage(f"Loading risk assessment: {risk_file.name}")
                    layer = self._add(map_obj, risk_file, risk_copy)
                    self._apply_risk_symbology(layer)
                    layers_added.append(layer)
                else:
                    arcpy.AddWarning("Risk assessment shapefile not found")
            else:
                arcpy.AddWarning("Risk assessment directory not found")

        # Move layers to group if requested
        if use_group and layers_added:
            group_name = f"{region} - Scenario {scenario_id}"
            if self.source_tag:
                group_name += f" [{self.source_tag}]"
            self._put_in_group(map_obj, group_name, layers_added)

        return len(layers_added)

    def _put_in_group(self, map_obj, group_name, layers_added):
        """Move the added layers into a group layer (created if needed)."""
        if layers_added:
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

    # ------------------------------------------------------------ municipality mode --

    def _load_kommuner(self, cfg, kommuner, scenario_ids, data_types, use_group, aprx, map_obj):
        """Load the selected scenarios cut to the municipalities, all forecast regions together."""
        if not kommuner:
            arcpy.AddError("Select at least one municipality.")
            return
        names = ", ".join(_kommune.short_names(kommuner))
        shapes = _kommune_shapes(cfg, kommuner)
        if not shapes:
            arcpy.AddError("None of the selected municipalities could be read.")
            return
        geometry = shapes[0][1]
        for _, shape in shapes[1:]:
            geometry = geometry.union(shape)
        bbox = _data.union_extent((s.extent.XMin, s.extent.YMin, s.extent.XMax, s.extent.YMax) for _, s in shapes)
        regions = _regions_for_kommuner(self.results_base, kommuner, bbox)
        if not regions:
            arcpy.AddError(f"No results in {self.results_base} overlap {names}.")
            return
        arcpy.AddMessage(f"Municipalities: {names}")
        arcpy.AddMessage(f"Forecast regions that may overlap them: {', '.join(regions)}")
        gdb = aprx.defaultGeodatabase
        tag = f" [{self.source_tag}]" if self.source_tag else ""

        # the boundaries, as their own layer above everything
        boundary_fc = self._kommune_boundary_fc(gdb, kommuner, shapes)
        if not self._already_loaded(map_obj, boundary_fc):
            boundary = map_obj.addDataFromPath(boundary_fc)
            boundary.name = f"{KOMMUNE_LAYER_PREFIX}{names}"
            self._apply_boundary_symbology(boundary)

        numbers = "_".join(sorted(_kommune.number_of(k) for k in kommuner))
        total = 0
        for sid in scenario_ids:
            arcpy.AddMessage("")
            arcpy.AddMessage(f"Scenario {sid}")
            folders = [(r, self._find_scenario_dir(r, sid)) for r in regions]
            folders = [(r, d) for r, d in folders if d]
            if not folders:
                arcpy.AddWarning(f"  No data for scenario {sid} in {', '.join(regions)} - skipped")
                continue
            layers_added = []
            for kind, label, pattern in (("tracks", "Tracks", "tracks_*.shp"), ("pras", "PRAs", "pra_*.shp"),
                                         ("risk", "Risk Assessment", None)):
                if label not in data_types:
                    continue
                sources = []
                for region, folder in folders:
                    if kind == "risk":
                        risk_dir = folder / "risk_assessment"
                        found = _data.find_risk_file(risk_dir, warn=arcpy.AddWarning) if risk_dir.exists() else None
                    else:
                        found = self._find_file(folder, pattern)
                    if found:
                        sources.append((region, found))
                layer = self._load_cut_layer(map_obj, gdb, kind, sid, sources, geometry, numbers, names, tag)
                if layer is not None:
                    layers_added.append(layer)
            for label, prefix in (("PPR Raster", "ppr"), ("PFV Raster", "pfv"), ("PFT Raster", "pft")):
                if label not in data_types:
                    continue
                for region, folder in folders:
                    raster = self._find_file(folder, f"{prefix}_*.tif")
                    if raster:
                        layer = self._load_region_raster(map_obj, raster, region, sid)
                        if layer is not None:
                            layers_added.append(layer)
            if use_group:
                self._put_in_group(map_obj, f"{names} - Scenario {sid}{tag}", layers_added)
            total += len(layers_added)
        arcpy.AddMessage("")
        arcpy.AddMessage(f"Successfully loaded {total} layers for {names}")

    def _cut_name(self, kind, sid, sources, numbers):
        """Name of the cached cut-out: changes when a source file or the municipalities change."""
        import hashlib
        parts = [numbers, kind, sid, self.source_tag]
        for region, path in sources:
            try:
                st = Path(path).stat()
                parts.append(f"{region}|{path}|{st.st_size}|{int(st.st_mtime)}")
            except OSError:
                parts.append(f"{region}|{path}")
        digest = hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:10]
        return re.sub(r"[^0-9A-Za-z_]", "_", f"k{numbers[:40]}_{kind}_{sid}_{digest}")

    def _reading_path(self, path):
        """What arcpy reads for a result file: its optimized copy if up to date, else a resolvable path."""
        copy = self._optimized(path)
        return str(copy) if copy is not None else str(_resolvable_shapefile(path))

    def _load_cut_layer(self, map_obj, gdb, kind, sid, sources, geometry, numbers, names, tag):
        """Tracks / PRAs / buildings of all regions inside the municipalities, as one layer."""
        if not sources:
            arcpy.AddWarning(f"  {kind}: no files found")
            return None
        fc = os.path.join(gdb, self._cut_name(kind, sid, sources, numbers))
        if arcpy.Exists(fc):
            arcpy.AddMessage(f"  {kind}: using the cut-out made earlier (sources unchanged)")
        else:
            fc = self._cut_and_merge(kind, sources, geometry, fc)
            if fc is None:
                arcpy.AddWarning(f"  {kind}: nothing inside {names}")
                return None
        if self._already_loaded(map_obj, fc):
            return None
        layer = map_obj.addDataFromPath(fc)
        # unique names without brackets: arcpy resolves layers by name in some contexts
        prefix = {"tracks": "tracks", "pras": "pra", "risk": "risk"}[kind]
        layer.name = f"{prefix} - {names} - {sid}" + (f" - {self.source_tag}" if self.source_tag else "")
        if kind == "tracks":
            self._apply_tracks_symbology(layer)
        elif kind == "pras":
            self._apply_pra_symbology(layer)
        else:
            self._apply_risk_symbology(layer)
        return layer

    def _cut_and_merge(self, kind, sources, geometry, fc):
        """Select what lies (partly) inside geometry in every source, merge, drop duplicate buildings."""
        parts = []
        for region, path in sources:
            name = f"alarm_cut_{uuid.uuid4().hex[:8]}"
            arcpy.management.MakeFeatureLayer(self._reading_path(path), name)
            try:
                arcpy.management.SelectLayerByLocation(name, "INTERSECT", geometry)
                count = int(arcpy.management.GetCount(name)[0])
                arcpy.AddMessage(f"  {kind}: {count} features from {region}")
                if not count:
                    continue
                part = f"memory\\alarm_part_{uuid.uuid4().hex[:8]}"
                mappings = self._numeric_mappings(name) if kind == "pras" else None
                if mappings is not None:
                    arcpy.conversion.ExportFeatures(name, part, field_mapping=mappings)
                else:
                    arcpy.conversion.ExportFeatures(name, part)
                arcpy.management.AddField(part, "alarm_region", "TEXT", field_length=60)
                arcpy.management.CalculateField(part, "alarm_region", repr(region), "PYTHON3")
                parts.append(part)
            finally:
                arcpy.management.Delete(name)
        if not parts:
            return None
        arcpy.management.Merge(parts, fc)
        for part in parts:
            arcpy.management.Delete(part)
        if kind == "risk":
            dropped = self._drop_duplicate_buildings(fc)
            if dropped:
                arcpy.AddMessage(f"  risk: {dropped} buildings were in more than one region - kept once "
                                 f"(highest max PPR)")
        return fc

    def _numeric_mappings(self, layer_name):
        """Field mappings that turn the PRA numbers stored as text into DOUBLE (None if not needed)."""
        mappings = arcpy.FieldMappings()
        mappings.addTable(layer_name)
        numeric_fields = {"elev_med", "aspect_deg", "area_m2", "t_high", "t_low"}
        changed = False
        for i in range(mappings.fieldCount):
            fmap = mappings.getFieldMap(i)
            out_field = fmap.outputField
            if out_field.name.lower() in numeric_fields and out_field.type == "String":
                out_field.type = "Double"
                fmap.outputField = out_field
                mappings.replaceFieldMap(i, fmap)
                changed = True
        return mappings if changed else None

    def _drop_duplicate_buildings(self, fc):
        """Keep each bld_id once (highest max_ppr); returns the number of rows removed."""
        names = {f.name.lower(): f.name for f in arcpy.ListFields(fc)}
        if "bld_id" not in names or "max_ppr" not in names:
            return 0
        records = [{'oid': oid, 'bld_id': bld, 'max_ppr': ppr}
                   for oid, bld, ppr in arcpy.da.SearchCursor(fc, ["OID@", names["bld_id"], names["max_ppr"]])]
        kept, dropped = _report.merge_buildings(records)
        if dropped:
            keep = {r['oid'] for r in kept}
            with arcpy.da.UpdateCursor(fc, ["OID@"]) as cursor:
                for (oid,) in cursor:
                    if oid not in keep:
                        cursor.deleteRow()
        return dropped

    def _load_region_raster(self, map_obj, raster, region, sid):
        """A result raster of a whole region (one per region).

        Not cut to the municipality: cutting read the full raster over the network and took
        about a minute per raster; the boundary layer shows where the municipality is.
        """
        copy = self._optimized(raster)
        if self._already_loaded(map_obj, raster, copy):
            return None
        arcpy.AddMessage(f"  Loading {raster.name} (whole region {region})")
        layer = self._add(map_obj, raster, copy)
        layer.name = f"{raster.stem.split('_')[0]} - {region} - {sid}" + (f" - {self.source_tag}" if self.source_tag else "")
        lyrx = raster.with_suffix(".lyrx")
        if lyrx.exists():
            self._apply_lyrx(layer, lyrx)
        elif raster.stem.startswith("ppr"):
            self._apply_ppr_symbology(layer)
        return layer

    def _kommune_boundary_fc(self, gdb, kommuner, shapes):
        """Feature class with the boundaries of the selected municipalities (one row each)."""
        numbers = sorted(nr for nr, _ in shapes)
        name = "kommune_" + "_".join(numbers)
        if len(name) > 60:
            import hashlib
            name = "kommune_" + hashlib.sha1(name.encode()).hexdigest()[:10]
        fc = os.path.join(gdb, name)
        if arcpy.Exists(fc):
            return fc
        arcpy.management.CreateFeatureclass(gdb, name, "POLYGON", spatial_reference=arcpy.SpatialReference(25833))
        arcpy.management.AddField(fc, "kommunenummer", "TEXT", field_length=4)
        arcpy.management.AddField(fc, "kommunenavn", "TEXT", field_length=120)
        labels = {_kommune.number_of(k): k for k in kommuner}
        with arcpy.da.InsertCursor(fc, ["SHAPE@", "kommunenummer", "kommunenavn"]) as cursor:
            for nr, shape in shapes:
                cursor.insertRow((shape, nr, _kommune.short_names([labels.get(nr, nr)])[0]))
        return fc

    def _apply_boundary_symbology(self, layer):
        """Municipality boundary: dark red outline, no fill."""
        try:
            sym = layer.symbology
            if hasattr(sym, 'renderer'):
                sym.updateRenderer('SimpleRenderer')
                symbol = sym.renderer.symbol
                symbol.color = {'RGB': [0, 0, 0, 0]}
                symbol.outlineColor = {'RGB': [139, 0, 0, 100]}
                symbol.outlineWidth = 2.5
                layer.symbology = sym
        except Exception as e:
            arcpy.AddWarning(f"Could not style the municipality boundary: {e}")

    def _optimized(self, path):
        """Up-to-date optimized copy of a result file (see alarm_core.data.optimized_copy), or None."""
        if path is None:
            return None
        return _data.optimized_copy(self.results_base, self.optimized_base, path)

    def _note_missing_copy(self):
        """Say why a file is read from the (slower) original although optimized copies exist."""
        if self.optimized_base is not None and self.optimized_base.is_dir():
            arcpy.AddMessage("  No up-to-date optimized copy (tools/optimize_results.py) - loading the original")

    def _add(self, map_obj, path, copy):
        """Add a result file to the map, from its optimized copy when there is one."""
        if copy is None:
            self._note_missing_copy()
            return map_obj.addDataFromPath(str(path))
        arcpy.AddMessage(f"  From the optimized copy: {copy}")
        layer = map_obj.addDataFromPath(str(copy))
        if path.suffix.lower() == ".shp":
            layer.name = path.stem  # GeoPackage layers would be called 'main.<table>'
        return layer

    def _already_loaded(self, map_obj, *paths):
        """True (with a message) if a layer of the active map already shows one of these files.

        Loading the same scenario twice used to add every layer a second time. A result is
        given as original and optimized copy, so a layer from either one counts.
        """
        targets = {_data.comparable_source(p) for p in paths if p is not None}
        for lyr in map_obj.listLayers():
            try:
                if lyr.isGroupLayer or not lyr.supports("DATASOURCE"):
                    continue
                if _data.comparable_source(lyr.dataSource) in targets:
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

        municipalities = _municipality_param()

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

        return [param0, municipalities, param1, param2, param3, param4, param5, param6, param7, param8, param9,
                param10]

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Municipality list for the chosen layers; aspect parameters for the aspect filter type."""
        p = _by_name(parameters)
        if _edited(p['layers_to_filter']):
            _update_municipality_list(p['municipalities'], _layer_bbox(p['layers_to_filter'].values))
        if p['aspect_type'].value:
            aspect_type = p['aspect_type'].valueAsText
            p['cardinal_dirs'].enabled = aspect_type == _filters.ASPECT_CARDINAL
            p['aspect_min'].enabled = aspect_type == _filters.ASPECT_DEGREES
            p['aspect_max'].enabled = aspect_type == _filters.ASPECT_DEGREES
        return

    def updateMessages(self, parameters):
        """Check the criteria before the tool runs (not needed for a reset)."""
        if _by_name(parameters)['filter_mode'].valueAsText != self.MODE_RESET:
            _show_validation(parameters, _FILTER_PARAMS, require_any=True)
        return

    def execute(self, parameters, messages):
        """The source code of the tool."""

        # Get parameters
        layer_names = _split_values(parameters[0].valueAsText)
        criteria = _criteria_from(parameters, _FILTER_PARAMS)
        p = _by_name(parameters)
        mode = p['filter_mode'].valueAsText or self.MODE_REFINE
        count_features = bool(p['count_features'].value) if p['count_features'].value is not None else True
        reset = mode == self.MODE_RESET
        refine = mode == self.MODE_REFINE

        # Municipalities: one boundary for all layers (the features inside are found per layer)
        kommune_geometry = None
        if criteria['kommuner'] and not reset:
            kommune_geometry = _kommune_geometry(_config.load_config(), criteria['kommuner'])
            if kommune_geometry is None:
                arcpy.AddError("None of the selected municipalities could be read.")
                return
        description = "ALARM: " + _filters.describe(criteria)

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
                    _set_filter(layer, "")
                    arcpy.AddMessage(f"  Reset filter: {layer.name}")
                    layers_filtered += 1
                    continue

                layer_type = self._detect_layer_type(layer)
                if layer_type == "tracks":
                    # cluster tracks pass when any member PRA matches (needs the member fields)
                    filter_query = _filters.track_query(
                        criteria, self._has_fields(layer, _filters.TRACK_MEMBER_FIELDS))
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

                if not filter_query and kommune_geometry is None:
                    arcpy.AddWarning(f"  {layer.name}: no filter criteria apply to this layer type - skipped")
                    continue

                previous_query = layer.definitionQuery or ""
                previous_name = _filter_name(layer)
                try:
                    if kommune_geometry is not None:
                        # spatial part: the features that lie at least partly in the municipalities
                        inside = _layer_oids_inside(layer, kommune_geometry)
                        arcpy.AddMessage(f"  {layer.name}: {len(inside)} features in "
                                         f"{', '.join(_kommune.short_names(criteria['kommuner']))}")
                        kommune_sql = _kommune.oid_condition(arcpy.Describe(layer).OIDFieldName, inside)
                        filter_query = f"({kommune_sql}) AND ({filter_query})" if filter_query else kommune_sql

                    # Refine: keep the filter that is already on the layer and add the new one
                    name = description
                    if refine:
                        filter_query = _filters.combine_refine(previous_query, filter_query)
                        if previous_query:
                            name = f"{previous_name or 'ALARM: earlier filter'} + {_filters.describe(criteria)}"

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

                    _set_filter(layer, filter_query, name)
                    action = "Refined" if (refine and previous_query) else "Applied"
                    arcpy.AddMessage(f"  {action} filter on: {layer.name} ({layer_type})")
                    arcpy.AddMessage(f"    Filter: {name}")
                    arcpy.AddMessage(f"    Query: {_short_sql(filter_query)}")

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
                        _set_filter(layer, previous_query, previous_name)
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

    def _has_fields(self, layer, field_names):
        try:
            fields = {f.name.lower() for f in arcpy.ListFields(layer)}
        except Exception:
            return False
        return all(name.lower() in fields for name in field_names)

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
            if self._has_64bit_ids(layer):
                self._copy_rows(layer, output_path)
            else:
                arcpy.conversion.ExportFeatures(layer, output_path)

            # Count features
            result = arcpy.management.GetCount(output_path)
            count = int(result.getOutput(0))

            arcpy.AddMessage(f"Successfully exported {count} features to:")
            arcpy.AddMessage(f"  {output_path}")

        except Exception as e:
            arcpy.AddError(f"Export failed: {e}")

        return

    # Field types that can be written to a shapefile (BigInteger as DOUBLE, as shapefiles store
    # wide integers); OID, geometry and the like are left out.
    _SHAPEFILE_FIELD_TYPES = {"String": "TEXT", "Double": "DOUBLE", "Single": "FLOAT", "Integer": "LONG",
                              "SmallInteger": "SHORT", "BigInteger": "DOUBLE", "Date": "DATE",
                              "DateOnly": "DATE"}

    def _has_64bit_ids(self, layer):
        """True for layers with 64-bit object IDs (GeoPackage, e.g. the optimized copies)."""
        try:
            return any(f.type == "OID" and f.length == 8 for f in arcpy.ListFields(layer))
        except Exception:
            return False

    def _copy_rows(self, layer, output_path):
        """Write the features the layer shows into a new shapefile, row by row.

        ArcGIS Pro cannot export a layer with 64-bit object IDs to a shapefile (ERROR 002809,
        whichever tool is used). The cursors respect the filter and the selection like
        ExportFeatures does.
        """
        desc = arcpy.Describe(layer)
        fields = [f for f in arcpy.ListFields(layer) if f.type in self._SHAPEFILE_FIELD_TYPES]
        out_dir, out_name = os.path.split(output_path)
        arcpy.management.CreateFeatureclass(out_dir, out_name, desc.shapeType,
                                            spatial_reference=desc.spatialReference)
        for f in fields:
            arcpy.management.AddField(output_path, f.name, self._SHAPEFILE_FIELD_TYPES[f.type],
                                      field_length=f.length if f.type == "String" else None)
        # CreateFeatureclass gives every new shapefile an 'Id' field
        if fields and "id" not in {f.name.lower() for f in fields}:
            arcpy.management.DeleteField(output_path, "Id")

        names = ["SHAPE@"] + [f.name for f in fields]
        with arcpy.da.SearchCursor(layer, names) as rows, arcpy.da.InsertCursor(output_path, names) as out:
            for row in rows:
                out.insertRow(row)


class GenerateReport(object):
    # background of the report map: tracks and PRAs near the buildings, simplified
    MAP_CONTEXT_DISTANCE_M = 1000
    MAP_GENERALIZE_M = 5
    MAP_MAX_CONTEXT_FEATURES = 20000
    MAP_FIELDS = ["bld_id", "saf_class", "max_ppr", "mean_ppr", "pra_elev", "pra_aspct"]

    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "3. Generate Report"
        self.description = ("Statistics report (HTML with map, CSV) for one or several Risk Assessment layers, "
                            "e.g. all regions a municipality lies in")
        self.canRunInBackground = False

    def getParameterInfo(self):
        """Define parameter definitions"""

        # Parameter 0: Risk Assessment layers (several: combined, each building once). Tracks and
        # PRA layers chosen here too are drawn on the map.
        param0 = arcpy.Parameter(
            displayName="Risk Assessment Layers (tracks/PRAs chosen too are drawn on the map)",
            name="risk_layer",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
            multiValue=True)

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

        # Parameter 3: interactive map in the HTML report
        param3 = arcpy.Parameter(
            displayName="Include map (HTML; needs internet when opened)",
            name="include_map",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input")
        param3.value = True

        return [param0, param1, param2, param3]

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal validation is performed."""
        return

    def updateMessages(self, parameters):
        """Say before the run which chosen layers are used how."""
        if not parameters[0].valueAsText:
            return
        try:
            kinds = self._sort_layers(_layers_of(parameters[0]), quiet=True)
        except Exception:
            return
        if not kinds['risk']:
            parameters[0].setErrorMessage("Choose at least one Risk Assessment layer.")
        elif kinds['tracks'] or kinds['pras'] or kinds['other']:
            notes = []
            if kinds['tracks'] or kinds['pras']:
                notes.append(f"{', '.join(l.name for l in kinds['tracks'] + kinds['pras'])}: drawn on the map")
            if kinds['other']:
                notes.append(f"{', '.join(l.name for l in kinds['other'])}: not used")
            parameters[0].setWarningMessage("; ".join(notes))
        return

    def _sort_layers(self, layers, quiet=False):
        """{'risk', 'tracks', 'pras', 'other': [layers]} by their fields."""
        detector = FilterLayers()
        kinds = {'risk': [], 'tracks': [], 'pras': [], 'other': []}
        for layer in layers:
            kind = detector._detect_layer_type(layer)
            kinds[kind if kind in kinds else 'other'].append(layer)
        if not quiet:
            for layer in kinds['tracks'] + kinds['pras']:
                arcpy.AddMessage(f"{layer.name}: not a Risk Assessment layer - drawn on the map")
            for layer in kinds['other']:
                arcpy.AddWarning(f"{layer.name}: not a Risk Assessment, tracks or PRA layer - not used")
        return kinds

    def execute(self, parameters, messages):
        """The source code of the tool."""
        kinds = self._sort_layers(_layers_of(parameters[0]))
        layers = kinds['risk']
        output_dir = parameters[1].valueAsText
        report_format = parameters[2].valueAsText
        include_map = bool(parameters[3].value) if len(parameters) > 3 and parameters[3].value is not None else True
        if not layers:
            arcpy.AddError("None of the chosen layers is a Risk Assessment layer.")
            return
        with_map = include_map and report_format in ["HTML", "Both"]
        self._extra_context = (kinds['tracks'], kinds['pras'])

        entries, records = [], []
        for layer in layers:
            arcpy.AddMessage(f"Analyzing layer: {layer.name}")
            sql = getattr(layer, 'definitionQuery', "") or ""
            if sql:
                arcpy.AddMessage(f"  Active filter: {_filter_name(layer) or _short_sql(sql)}")
            selected = _selection_count(layer)
            if selected:
                arcpy.AddWarning(f"  {selected} features are selected in '{layer.name}' - the report only covers "
                                 f"the selection. Clear the selection to report everything the filter shows.")
            try:
                layer_records = self._read_buildings(layer, with_map, tag=layer.name if len(layers) > 1 else None)
            except Exception as e:
                arcpy.AddError(f"Could not read {', '.join(_report.FIELDS)} from '{layer.name}' - "
                               f"is it a Risk Assessment layer? ({e})")
                return
            arcpy.AddMessage(f"  {len(layer_records)} buildings")
            records.extend(layer_records)
            entries.append({'name': layer.name, 'sql': _short_sql(sql), 'selected': selected,
                            'source': getattr(layer, 'dataSource', None),
                            'description': _filter_name(layer) if sql else None})

        records, duplicates = _report.merge_buildings(records)
        if duplicates:
            arcpy.AddMessage(f"{duplicates} buildings are in more than one layer - each is counted once "
                             f"(highest max PPR)")
        stats = _report.collect((r['saf_class'], r['max_ppr'], r['mean_ppr'], r['pra_elev'], r['pra_aspct'])
                                for r in records)
        arcpy.AddMessage(f"Analyzed {stats['total']} buildings")
        if stats['elevation'][_report.UNKNOWN]:
            arcpy.AddWarning(f"{stats['elevation'][_report.UNKNOWN]} buildings have no elevation (listed as Unknown)")

        context = _report.context_for_layers(entries, duplicates)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        more = f"_and_{len(layers) - 1}_more" if len(layers) > 1 else ""
        base = re.sub(r"[^0-9A-Za-z_]", "_", f"risk_report_{layers[0].name}{more}_{timestamp}")

        if report_format in ["HTML", "Both"]:
            html_path = os.path.join(output_dir, base + ".html")
            if include_map:
                payload = self._map_payload(layers, records)
                context_info = ", ".join(f"{len(v['features'])} {k}" for k, v in payload['context'].items())
                arcpy.AddMessage(f"Map: {sum(1 for r in records if r.get('lon') is not None)} buildings in "
                                 f"{len(payload['areas'])} affected areas"
                                 + (f"; background: {context_info}" if context_info else ""))
                _report.write_html(html_path, stats, context, map_html=_webmap.map_section(payload),
                                   head_extra=_webmap.head_html())
            else:
                _report.write_html(html_path, stats, context)
            arcpy.AddMessage(f"HTML report: {html_path}")
        if report_format in ["CSV", "Both"]:
            csv_path = os.path.join(output_dir, base + ".csv")
            _report.write_csv(csv_path, stats, context)
            arcpy.AddMessage(f"CSV report: {csv_path}")
        return

    # ------------------------------------------------------------------- reading --

    def _read_buildings(self, layer, with_shape, tag=None):
        """Records of a risk layer (respects filter and selection), optionally with WGS84 geometry."""
        names = {f.name.lower(): f.name for f in arcpy.ListFields(layer)}
        missing = [f for f in _report.FIELDS if f not in names]
        if missing:
            raise KeyError(", ".join(missing))
        present = [f for f in self.MAP_FIELDS if f in names]     # older results may lack some of them
        fields = [names[f] for f in present] + (["SHAPE@"] if with_shape else [])
        kwargs = {'spatial_reference': arcpy.SpatialReference(4326)} if with_shape else {}
        records = []
        with arcpy.da.SearchCursor(layer, fields, **kwargs) as cursor:
            for row in cursor:
                record = {name: value for name, value in zip(present, row)}
                for name in self.MAP_FIELDS:
                    record.setdefault(name, None)
                if tag:
                    record['source'] = tag
                if with_shape and row[-1] is not None:
                    shape = row[-1]
                    centre = shape.centroid if shape.type != "point" else shape.firstPoint
                    record['lon'], record['lat'] = centre.X, centre.Y
                    try:
                        record['geometry'] = shape.__geo_interface__ if shape.type == "polygon" else None
                    except Exception:
                        record['geometry'] = None
                records.append(record)
        return records

    def _map_payload(self, layers, records):
        """Buildings plus background (tracks and PRAs near them, municipality boundaries)."""
        buildings = []
        for r in records:
            if r.get('lon') is None:
                continue
            props = {k: (round(r[k], 1) if isinstance(r[k], float) else r[k])
                     for k in self.MAP_FIELDS + ['source'] if r.get(k) is not None}
            buildings.append({'lon': r['lon'], 'lat': r['lat'], 'geometry': r.get('geometry'), 'props': props})
        tracks_layers, pra_layers, boundary_layers = self._context_layers(layers)
        # tracks / PRA layers chosen in the dialog are drawn as well (each layer once)
        extra_tracks, extra_pras = getattr(self, "_extra_context", ([], []))
        tracks_layers = _unique_layers(tracks_layers + list(extra_tracks))
        pra_layers = _unique_layers(pra_layers + list(extra_pras))
        tracks = [g for lyr in tracks_layers for g in self._features_near(lyr, layers)]
        pras = [g for lyr in pra_layers for g in self._features_near(lyr, layers)]
        boundaries = [g for lyr in boundary_layers for g in self._all_features(lyr, 20)]
        return _webmap.build_payload(buildings, tracks=tracks, pras=pras, boundaries=boundaries)

    def _context_layers(self, risk_layers):
        """Tracks and PRA layers of the same groups as the risk layers, and municipality boundaries."""
        try:
            map_obj = arcpy.mp.ArcGISProject("CURRENT").activeMap
        except Exception:
            map_obj = None
        if map_obj is None:
            return [], [], []
        groups = {lyr.longName.rsplit("\\", 1)[0] for lyr in risk_layers if "\\" in lyr.longName}
        detector = FilterLayers()
        tracks, pras, boundaries = [], [], []
        for lyr in map_obj.listLayers():
            if not lyr.isFeatureLayer or not lyr.visible:
                continue
            if lyr.name.startswith(KOMMUNE_LAYER_PREFIX):
                boundaries.append(lyr)
                continue
            parent = lyr.longName.rsplit("\\", 1)[0] if "\\" in lyr.longName else None
            if parent is None or parent not in groups:
                continue
            kind = detector._detect_layer_type(lyr)
            if kind == "tracks":
                tracks.append(lyr)
            elif kind == "pras":
                pras.append(lyr)
        return tracks, pras, boundaries

    def _geojson(self, shape, tolerance):
        """Simplified WGS84 GeoJSON of a shape (simplified in metres when the layer is projected)."""
        if shape is None:
            return None
        if tolerance and shape.spatialReference and shape.spatialReference.type == "Projected":
            shape = shape.generalize(tolerance)
        try:
            return shape.projectAs(arcpy.SpatialReference(4326)).__geo_interface__
        except Exception:
            return None

    def _features_near(self, layer, risk_layers):
        """Features of layer (its filter applies) within MAP_CONTEXT_DISTANCE_M of the buildings."""
        name = f"alarm_ctx_{uuid.uuid4().hex[:8]}"
        arcpy.management.MakeFeatureLayer(layer, name)
        try:
            for i, risk in enumerate(risk_layers):
                arcpy.management.SelectLayerByLocation(
                    name, "WITHIN_A_DISTANCE", risk, f"{self.MAP_CONTEXT_DISTANCE_M} Meters",
                    "NEW_SELECTION" if i == 0 else "ADD_TO_SELECTION")
            out = []
            with arcpy.da.SearchCursor(name, ["SHAPE@"]) as cursor:
                for (shape,) in cursor:
                    if len(out) >= self.MAP_MAX_CONTEXT_FEATURES:
                        arcpy.AddWarning(f"  {layer.name}: only the first {self.MAP_MAX_CONTEXT_FEATURES} features "
                                         f"near the buildings are drawn on the map")
                        break
                    geometry = self._geojson(shape, self.MAP_GENERALIZE_M)
                    if geometry:
                        out.append({'geometry': geometry})
            return out
        finally:
            arcpy.management.Delete(name)

    def _all_features(self, layer, tolerance):
        """All features of a (boundary) layer, with their name if the layer has a name field."""
        names = {f.name.lower(): f.name for f in arcpy.ListFields(layer)}
        name_field = next((names[n] for n in ("kommunenavn", "navn", "name") if n in names), None)
        fields = ["SHAPE@"] + ([name_field] if name_field else [])
        out = []
        with arcpy.da.SearchCursor(layer, fields) as cursor:
            for row in cursor:
                geometry = self._geojson(row[0], tolerance)
                if geometry:
                    out.append({'geometry': geometry, 'props': {'name': row[1]} if len(row) > 1 else {}})
        return out


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
        source, source_folder = _make_source_params(cfg)

        param0 = arcpy.Parameter(displayName="Region", name="region", datatype="GPString",
                                 parameterType="Required", direction="Input")
        regions = _data.completed_regions(cfg['results_base'])
        param0.filter.type = "ValueList"
        param0.filter.list = regions if regions else [NO_REGIONS]
        municipalities = _municipality_param()

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

        return [source, source_folder, param0, municipalities, param1, param2, param3, param4, param5, param6,
                param7, param8, param9, param10, param11]

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Follow the chosen data source; enable the aspect parameters for the aspect filter type."""
        p = _by_name(parameters)
        cfg = _config.load_config()
        region_changed = _edited(p['source']) or _edited(p['source_folder']) or _edited(p['region'])
        _refresh_source_dependent(p['source'], p['source_folder'], p['region'], p['scenarios'],
                                  cfg, multi_region=False, select_all_scenarios=True)
        if region_changed:
            _, base = _selected_source(p['source'], p['source_folder'], cfg)
            _update_municipality_list(p['municipalities'], _region_bbox(base, p['region'].valueAsText))
        if p['aspect_type'].value:
            aspect_type = p['aspect_type'].valueAsText
            p['cardinal_dirs'].enabled = aspect_type == _filters.ASPECT_CARDINAL
            p['aspect_min'].enabled = aspect_type == _filters.ASPECT_DEGREES
            p['aspect_max'].enabled = aspect_type == _filters.ASPECT_DEGREES
        return

    def updateMessages(self, parameters):
        """Check data source, region and criteria before the tool runs."""
        p = _by_name(parameters)
        _check_source(p['source'], p['source_folder'], p['region'], p['scenarios'], _config.load_config())
        _show_validation(parameters, _COMPARE_PARAMS)
        return

    def execute(self, parameters, messages):
        """The source code of the tool."""
        p = _by_name(parameters)
        cfg = _config.load_config()
        source_name, base = _selected_source(p['source'], p['source_folder'], cfg)
        if base is None or not base.is_dir():
            arcpy.AddError(f"Data folder not found: {base}")
            return
        arcpy.AddMessage(f"Data source: {source_name} ({base})")

        region = p['region'].valueAsText
        scenario_ids = [v.split(' - ')[0] for v in _split_values(p['scenarios'].valueAsText)]
        criteria = _criteria_from(parameters, _COMPARE_PARAMS)
        output_dir = p['output_dir'].valueAsText
        report_format = p['report_format'].valueAsText

        descriptions = cfg['scenarios'] if source_name == _config.STANDARD_SOURCE \
            else _data.discover_scenarios(base, [region])
        inside = None
        if criteria['kommuner']:
            geometry = _kommune_geometry(cfg, criteria['kommuner'])
            if geometry is None:
                arcpy.AddError("None of the selected municipalities could be read.")
                return
            names = ", ".join(_kommune.short_names(criteria['kommuner']))
            arcpy.AddMessage(f"Counting only features in {names} (spatial selection, takes a while for large layers)")

            def inside(shp):
                return _oids_inside(str(_resolvable_shapefile(shp)), geometry)

        results = []
        for sid in scenario_ids:
            scenario_dir = _data.find_scenario_dir(base, region, sid)
            if not scenario_dir:
                arcpy.AddWarning(f"Scenario {sid}: no data found for {region} - skipped")
                continue
            arcpy.AddMessage(f"Scenario {sid}: reading {_data.scenario_dir_label(scenario_dir)}")
            results.append(_compare.compute_scenario(
                sid, scenario_dir, criteria, label=descriptions.get(sid, sid), warn=arcpy.AddWarning, inside=inside))

        if not results:
            arcpy.AddError("No scenarios could be read.")
            return

        rows = _compare.build_rows(results)
        arcpy.AddMessage("")
        for line in _compare.table_lines(rows, results):
            arcpy.AddMessage(line)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_base = re.sub(r"[^0-9A-Za-z_]", "_", f"compare_{region}_{timestamp}")
        if report_format in ("HTML", "Both"):
            html_path = os.path.join(output_dir, file_base + ".html")
            _compare.write_html(html_path, region, results, rows, criteria, source=f"{source_name}: {base}")
            arcpy.AddMessage(f"HTML report: {html_path}")
        if report_format in ("CSV", "Both"):
            csv_path = os.path.join(output_dir, file_base + ".csv")
            _compare.write_csv(csv_path, results, rows)
            arcpy.AddMessage(f"CSV report: {csv_path}")
        return
