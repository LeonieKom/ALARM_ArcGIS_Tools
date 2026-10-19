"""Central configuration: where the results are and which scenarios exist.

Defaults can be overridden without editing code:
  * environment variable ALARM_RESULTS_BASE, or
  * a file alarm_tools_config.json next to ALARM_Tools.pyt, e.g.
        {"results_base": "D:\\\\ALARM\\\\Results",
         "scenarios": {"A": "80-60, prox0, rel1.2m"}}
    (see alarm_tools_config.example.json)
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

CONFIG_FILENAME = "alarm_tools_config.json"


def config_path():
    """Location of the optional JSON config (the folder that contains the alarm_core package)."""
    return Path(__file__).resolve().parent.parent / CONFIG_FILENAME


def load_config(path=None, environ=None):
    """Return {'results_base': Path, 'scenarios': dict}.

    Precedence: environment variable > JSON file > defaults. A broken JSON file raises
    ValueError with the file name, so the problem is visible instead of silently ignored.
    """
    environ = os.environ if environ is None else environ
    results_base = DEFAULT_RESULTS_BASE
    scenarios = dict(DEFAULT_SCENARIOS)

    cfg_file = Path(path) if path else config_path()
    if cfg_file.exists():
        try:
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"Cannot read {cfg_file}: {exc}") from exc
        if data.get("results_base"):
            results_base = data["results_base"]
        if data.get("scenarios"):
            scenarios = {str(k): str(v) for k, v in data["scenarios"].items()}

    if environ.get("ALARM_RESULTS_BASE"):
        results_base = environ["ALARM_RESULTS_BASE"]

    return {'results_base': Path(results_base), 'scenarios': scenarios}
