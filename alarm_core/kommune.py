"""Municipalities (kommuner): labels for the dialogs and SQL for a set of object IDs (no arcpy).

A municipality filter is spatial: a feature belongs to a municipality if it lies at least partly
inside it. The tools find the object IDs of those features with arcpy and turn them into a
definition query; this module builds that query so that it stays short.
"""

import json as _json
import re
from pathlib import Path as _Path

_LABEL = re.compile(r"\((?P<nr>\d{4})\)\s*$")


def label(number, name):
    """Text shown in the dialogs, e.g. 'Tromsø - Romsa (5501)'."""
    return f"{name} ({number})" if name else f"Kommune {number} ({number})"


def number_of(text):
    """Municipality number from a dialog label ('Tromsø - Romsa (5501)' -> '5501'), or None."""
    match = _LABEL.search(text or "")
    return match.group("nr") if match else None


def names_by_key(rows):
    """{key: 'Name1 - Name2'} from rows (name, order, language, key) of the names table.

    The Kartverket dataset keeps the official names (Norwegian, Sami, Kven) in a separate table;
    they are joined in their official order, as in 'Tromsø - Romsa'.
    """
    collected = {}
    for name, order, _language, key in rows:
        if name:
            collected.setdefault(key, []).append((order if order is not None else 99, name))
    return {key: " - ".join(n for _, n in sorted(names)) for key, names in collected.items()}


def oid_condition(oid_field, oids, max_in=1000):
    """SQL selecting exactly these object IDs, as short as possible.

    Runs of consecutive IDs (common: neighbouring features were written one after another)
    become 'BETWEEN' ranges, the rest IN lists of at most max_in values. An empty set selects
    nothing ('<oid> < 0'; object IDs are never negative).
    """
    ids = sorted(set(int(i) for i in oids))
    if not ids:
        return f"{oid_field} < 0"
    ranges, singles = [], []
    start = prev = ids[0]
    for i in ids[1:] + [None]:
        if i is not None and i == prev + 1:
            prev = i
            continue
        if prev - start >= 2:
            ranges.append((start, prev))
        else:
            singles.extend(range(start, prev + 1))
        if i is not None:
            start = prev = i
    parts = [f"({oid_field} >= {a} AND {oid_field} <= {b})" for a, b in ranges]
    for k in range(0, len(singles), max_in):
        chunk = singles[k:k + max_in]
        parts.append(f"{oid_field} IN ({', '.join(str(i) for i in chunk)})")
    return parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"


def short_names(labels):
    """'Tromsø - Romsa (5501)' -> 'Tromsø' for compact filter descriptions."""
    out = []
    for text in labels:
        name = _LABEL.sub("", text).strip()
        out.append(name.split(" - ")[0] if name else text)
    return out


# ----------------------------------------------------------- bundled municipality list --
# alarm_core/kommuner.json: number, official name(s) and bounding box (EPSG:25833) of every
# municipality, made from the Kartverket dataset. The dialogs use it, so they never wait for L:;
# the exact boundaries for the spatial filter are read from the dataset itself (and cached).

LIST_PATH = _Path(__file__).resolve().parent / "kommuner.json"
_cache = {}


def load_list(path=None):
    """[{'nr', 'name', 'bbox'}] of all municipalities (read once)."""
    path = _Path(path) if path else LIST_PATH
    if path not in _cache:
        _cache[path] = _json.loads(path.read_text(encoding="utf-8"))["kommuner"]
    return _cache[path]


def bbox_overlaps(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def labels_for(bbox=None, path=None):
    """Dialog labels of the municipalities whose bounding box overlaps bbox (all if None), by name."""
    items = load_list(path)
    chosen = [k for k in items if bbox is None or bbox_overlaps(k["bbox"], bbox)]
    return [label(k["nr"], k["name"]) for k in sorted(chosen, key=lambda k: (k["name"].lower(), k["nr"]))]
