"""Central configuration: where the results are and which scenarios exist.

Defaults can be overridden without editing code:
  * environment variables ALARM_RESULTS_BASE / ALARM_OPTIMIZED_BASE, or
  * a file alarm_tools_config.json next to ALARM_Tools.pyt, e.g.
        {"results_base": "D:\\\\ALARM\\\\Results",
         "scenarios": {"A": "80-60, prox0, rel1.2m"}}
    (see alarm_tools_config.example.json)

optimized_base is where tools/optimize_results.py (pipeline repository) writes the fast
copies; it defaults to '<results_base>_optimized'. An empty value switches them off.

"sources" are the data folders the tools can read from, selectable in the tool dialogs
(next to "Other folder..."): the standard results folder plus, by default, the ALARM2.2 test
runs. Add your own with  "sources": {"My run": "D:\\ALARM\\run1"}; an empty path removes a
default source.
"""

import json
import os
from pathlib import Path

DEFAULT_RESULTS_BASE = r"L:\ALARM\Results"

# scenario id -> description shown in the tool dialogs
DEFAULT_SCENARIOS = {
    'A': '80-60, prox0, rel1.2m',
    'B': '80-60, prox0, rel1.8m',
    'C': '80-60, prox100, rel2.3m',
    'D': '75-55, prox0, rel2.3m',
    'E': '75-55, prox150, rel2.3m',
}

# Name of the source that is always the results folder (results_base)
STANDARD_SOURCE = "Standard results"

# Further data folders offered in the dialogs
DEFAULT_EXTRA_SOURCES = {
    'ALARM2.2': r"L:\ALARM\ALARM2.2",
}

# Municipality boundaries (Kartverket "Kommuner", feature class 'kommune' + names table)
DEFAULT_KOMMUNE_GDB = r"L:\ALARM\BaseData\Basisdata_0000_Norge_25833_Kommuner_FGDB.gdb"

CONFIG_FILENAME = "alarm_tools_config.json"


def config_path():
    """Location of the optional JSON config (the folder that contains the alarm_core package)."""
    return Path(__file__).resolve().parent.parent / CONFIG_FILENAME


def load_config(path=None, environ=None):
    """Return {'results_base': Path, 'optimized_base': Path or None, 'scenarios': dict,
    'sources': {name: Path}, 'kommune_gdb': Path}  (the first source is the standard results folder).

    Precedence: environment variable > JSON file > defaults. A broken JSON file raises
    ValueError with the file name, so the problem is visible instead of silently ignored.
    """
    environ = os.environ if environ is None else environ
    results_base = DEFAULT_RESULTS_BASE
    optimized_base = None  # None: derived from results_base below
    scenarios = dict(DEFAULT_SCENARIOS)
    extra_sources = dict(DEFAULT_EXTRA_SOURCES)
    kommune_gdb = DEFAULT_KOMMUNE_GDB

    cfg_file = Path(path) if path else config_path()
    if cfg_file.exists():
        try:
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"Cannot read {cfg_file}: {exc}") from exc
        if data.get("results_base"):
            results_base = data["results_base"]
        if "optimized_base" in data:
            optimized_base = data["optimized_base"] or ""
        if data.get("scenarios"):
            scenarios = {str(k): str(v) for k, v in data["scenarios"].items()}
        if data.get("kommune_gdb"):
            kommune_gdb = data["kommune_gdb"]
        for name, folder in (data.get("sources") or {}).items():
            if folder:
                extra_sources[str(name)] = str(folder)
            else:
                extra_sources.pop(str(name), None)

    if environ.get("ALARM_RESULTS_BASE"):
        results_base = environ["ALARM_RESULTS_BASE"]
    if environ.get("ALARM_KOMMUNE_GDB"):
        kommune_gdb = environ["ALARM_KOMMUNE_GDB"]
    if "ALARM_OPTIMIZED_BASE" in environ:
        optimized_base = environ["ALARM_OPTIMIZED_BASE"]

    results_base = Path(results_base)
    if optimized_base is None:
        optimized_base = results_base.with_name(results_base.name + "_optimized")
    sources = {STANDARD_SOURCE: results_base}
    sources.update({name: Path(folder) for name, folder in extra_sources.items() if name != STANDARD_SOURCE})
    return {'results_base': results_base,
            'optimized_base': Path(optimized_base) if optimized_base else None,
            'scenarios': scenarios,
            'sources': sources,
            'kommune_gdb': Path(kommune_gdb)}
