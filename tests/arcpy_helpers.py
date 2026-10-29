"""Shared helpers of the arcpy tests: stand-ins for tool parameters and the project, and the
environment fixture body (a copy of a project with a map, a scratch geodatabase, the toolbox
loaded as a module)."""

import importlib.machinery
import importlib.util
import shutil
from pathlib import Path

import arcpy

from alarm_core import config

ROOT = Path(__file__).resolve().parent.parent


class P:
    """Stand-in for an arcpy tool parameter."""

    def __init__(self, value=None, name=None, altered=False):
        self.value = value
        self.name = name
        self.enabled = True
        self.error = self.warning = None
        self.altered = altered                    # edited by the user since the last validation
        self.hasBeenValidated = not altered
        self.filter = type("Filter", (), {"type": None, "list": []})()

    def setErrorMessage(self, message):
        self.error = message

    def setWarningMessage(self, message):
        self.warning = message

    @property
    def valueAsText(self):
        if self.value is None:
            return None
        if isinstance(self.value, (list, tuple)):
            return ";".join(str(x) for x in self.value)
        return str(self.value)


def std_source():
    cfg = config.load_config()
    return f"{config.STANDARD_SOURCE}  ({cfg['sources'][config.STANDARD_SOURCE]})"


def load_params(regions, scenarios, data_types, group=True, source=None, folder=None):
    """The parameters of 'Load ALARM Data', in dialog order and with their names."""
    return [P(source or std_source(), "source"), P(folder, "source_folder"), P(regions, "region"),
            P(scenarios, "scenario"), P(data_types, "data_types"), P(group, "use_group")]


COMPARE_NAMES = ["source", "source_folder", "region", "scenarios", "elev_min", "elev_max", "aspect_type",
                 "cardinal_dirs", "aspect_min", "aspect_max", "saf_class", "min_max_ppr", "output_dir", "report_format"]


def compare_params(region, scenarios, emin=None, emax=None, aspect="None", cardinal=None, amin=None, amax=None,
                   saf=None, ppr=None, out="", fmt="HTML", source=None, folder=None):
    """The parameters of 'Compare Scenarios', in dialog order and with their names."""
    values = [source or std_source(), folder, region, scenarios, emin, emax, aspect, cardinal, amin, amax, saf, ppr,
              out, fmt]
    return [P(v, n) for v, n in zip(values, COMPARE_NAMES)]


class ProjectProxy:
    """What ArcGISProject('CURRENT') returns inside a tool: our map, our scratch geodatabase."""

    def __init__(self, raw, map_obj, gdb):
        self._raw, self.activeMap, self.activeView, self.defaultGeodatabase = raw, map_obj, None, gdb

    def __getattr__(self, name):
        return getattr(self._raw, name)


def env_context(tmp_path_factory, aprx):
    """Yield an object with .mod (the toolbox), .map, .gdb and .work; restores arcpy afterwards."""
    work = tmp_path_factory.mktemp("arcpy_it")
    aprx_copy = work / "test.aprx"
    shutil.copy(aprx, aprx_copy)
    arcpy.management.CreateFileGDB(str(work), "scratch.gdb")
    gdb = str(work / "scratch.gdb")

    loader = importlib.machinery.SourceFileLoader("alarm_tools_under_test", str(ROOT / "ALARM_Tools.pyt"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)

    real = arcpy.mp.ArcGISProject
    raw = real(str(aprx_copy))
    m = raw.listMaps()[0]
    proxy = ProjectProxy(raw, m, gdb)
    arcpy.mp.ArcGISProject = lambda p: proxy if p == "CURRENT" else real(p)
    try:
        yield type("Env", (), {"mod": mod, "map": m, "gdb": gdb, "work": work})
    finally:
        arcpy.mp.ArcGISProject = real
