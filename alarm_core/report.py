"""Statistics report for a Risk Assessment layer (buildings), without arcpy.

The tool reads the rows with an arcpy cursor (so the layer's filter and selection apply) and
passes them here. The report states which filter and selection were active, so a report of
a filtered layer cannot be mistaken for one of the whole layer.
"""

import csv
from datetime import datetime
from html import escape

from .compare import PPR_CLASSES
from .filters import CARDINAL_RANGES

FIELDS = ['saf_class', 'max_ppr', 'mean_ppr', 'pra_elev', 'pra_aspct']

ELEVATION_CLASSES = [("<500m", None, 500), ("500-1000m", 500, 1000), ("1000-1500m", 1000, 1500),
                     ("1500-2000m", 1500, 2000), (">2000m", 2000, None)]
UNKNOWN = "Unknown"
ASPECT_ORDER = list(CARDINAL_RANGES) + [UNKNOWN]      # N, NE, E, ... NW, Unknown


def _aspect_class(value):
    """Cardinal direction of a pra_aspct value (normally 'N', 'NE', ...; degrees also accepted)."""
    if value is None or str(value).strip() == "":
        return UNKNOWN
    text = str(value).strip()
    if text in CARDINAL_RANGES:
        return text
    try:
        degrees = float(text) % 360
    except ValueError:
        return text
    for name, ranges in CARDINAL_RANGES.items():
        if any(lo <= degrees < hi for lo, hi in ranges):
            return name
    return UNKNOWN


def _class_of(value, classes):
    for label, lo, hi in classes:
        if (lo is None or value >= lo) and (hi is None or value < hi):
            return label
    return classes[-1][0]


def collect(rows):
    """Statistics from rows of (saf_class, max_ppr, mean_ppr, pra_elev, pra_aspct).

    A missing max_ppr counts as 0 kPa (as in Compare Scenarios). A missing elevation is
    counted as 'Unknown' and left out of the elevation range (it used to count as 0 m).
    """
    stats = {
        'total': 0,
        'saf': {},
        'ppr': {label: 0 for label, _, _ in PPR_CLASSES},
        'elevation': {label: 0 for label, _, _ in ELEVATION_CLASSES},
        'aspect': {},
        'max_ppr': [],
        'mean_ppr': [],
        'elev': [],
    }
    stats['elevation'][UNKNOWN] = 0
    for saf, max_ppr, mean_ppr, elev, aspect in rows:
        stats['total'] += 1
        saf = saf or UNKNOWN
        stats['saf'][saf] = stats['saf'].get(saf, 0) + 1

        value = max_ppr if max_ppr is not None else 0.0
        stats['max_ppr'].append(value)
        stats['ppr'][_class_of(value, PPR_CLASSES)] += 1

        if mean_ppr is not None:
            stats['mean_ppr'].append(mean_ppr)

        if elev is None:
            stats['elevation'][UNKNOWN] += 1
        else:
            stats['elev'].append(elev)
            stats['elevation'][_class_of(elev, ELEVATION_CLASSES)] += 1

        a = _aspect_class(aspect)
        stats['aspect'][a] = stats['aspect'].get(a, 0) + 1
    return stats


def summary(stats):
    """Key figures; None where there is no value."""
    def rng(values):
        return (min(values), max(values)) if values else (None, None)
    return {
        'buildings': stats['total'],
        'max_ppr_range': rng(stats['max_ppr']),
        'mean_ppr_average': (sum(stats['mean_ppr']) / len(stats['mean_ppr'])) if stats['mean_ppr'] else None,
        'elevation_range': rng(stats['elev']),
        'elevation_unknown': stats['elevation'][UNKNOWN],
    }


def tables(stats):
    """[(title, header, [(label, count)])] in display order."""
    saf = sorted(stats['saf'].items(), key=lambda kv: (kv[0] == UNKNOWN, kv[0]))
    elevation = [(label, stats['elevation'][label]) for label, _, _ in ELEVATION_CLASSES]
    if stats['elevation'][UNKNOWN]:
        elevation.append((UNKNOWN, stats['elevation'][UNKNOWN]))
    order = {name: i for i, name in enumerate(ASPECT_ORDER)}
    aspect = sorted(stats['aspect'].items(), key=lambda kv: (order.get(kv[0], len(order)), kv[0]))
    return [
        ("Buildings by Safety Class", "Safety Class", saf),
        ("Buildings by PPR Category", "PPR Range", [(label, stats['ppr'][label]) for label, _, _ in PPR_CLASSES]),
        ("Buildings by Elevation Range", "Elevation Range", elevation),
        ("Buildings by Aspect", "Aspect", aspect),
    ]


def context_lines(layer_name, definition_query, selected, source=None, description=None):
    """What the report is based on: layer, filter and selection.

    description is the readable name Filter Layers gives its filter (e.g. 'ALARM: Kommune Tromsø;
    >= 300 m'); the SQL is listed below it, since a municipality filter is a long list of IDs.
    """
    lines = [("Layer", layer_name)]
    if source:
        lines.append(("Data source", source))
    if definition_query and description:
        lines.append(("Filter", description))
        lines.append(("Filter (SQL)", definition_query))
    else:
        lines.append(("Filter", definition_query if definition_query else "none - all features of the layer"))
    if selected:
        lines.append(("Selection", f"{selected} selected features - only these are included"))
    return lines


def _pct(count, total):
    return (count / total * 100) if total else 0.0


def _fmt(value, digits):
    return "-" if value is None else f"{value:.{digits}f}"


def write_html(path, stats, context, generated=None, map_html=None, head_extra=None):
    """The report as HTML; map_html / head_extra add the map (see alarm_core.webmap)."""
    generated = generated or datetime.now()
    s = summary(stats)
    layer_name = dict(context).get("Layer", "")
    ctx = "".join(f"<p><strong>{escape(k)}:</strong> {escape(str(v))}</p>" for k, v in context)
    elev_note = (f" ({s['elevation_unknown']} buildings without elevation not included)"
                 if s['elevation_unknown'] else "")
    parts = [f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Risk Assessment Report - {escape(layer_name)}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        h2 {{ color: #666; margin-top: 30px; }}
        table {{ border-collapse: collapse; width: 100%; max-width: 600px; margin: 10px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #4CAF50; color: white; }}
        tr:nth-child(even) {{ background-color: #f2f2f2; }}
        .summary {{ background-color: #e7f3fe; padding: 15px; border-left: 6px solid #2196F3; margin: 20px 0; }}
        .context {{ background-color: #f2f2f2; padding: 10px 15px; border-left: 6px solid #999; }}
    </style>
    {head_extra or ""}
</head>
<body>
    <h1>Risk Assessment Report</h1>
    <div class="context">{ctx}<p><strong>Generated:</strong> {generated.strftime("%Y-%m-%d %H:%M:%S")}</p></div>

    <div class="summary">
        <h2>Summary</h2>
        <p><strong>Total Buildings Analyzed:</strong> {s['buildings']}</p>
        <p><strong>Max PPR Range:</strong> {_fmt(s['max_ppr_range'][0], 2)} - {_fmt(s['max_ppr_range'][1], 2)} kPa</p>
        <p><strong>Average of Mean PPR:</strong> {_fmt(s['mean_ppr_average'], 2)} kPa</p>
        <p><strong>Elevation Range:</strong> {_fmt(s['elevation_range'][0], 0)} - {_fmt(s['elevation_range'][1], 0)} m{escape(elev_note)}</p>
    </div>
"""]
    if map_html:
        parts.append(map_html)
    for title, header, rows in tables(stats):
        parts.append(f"""
    <h2>{escape(title)}</h2>
    <table>
        <tr><th>{escape(header)}</th><th>Count</th><th>Percentage</th></tr>
""")
        for label, count in rows:
            parts.append(f"        <tr><td>{escape(str(label))}</td><td>{count}</td>"
                         f"<td>{_pct(count, stats['total']):.1f}%</td></tr>\n")
        parts.append("    </table>\n")
    parts.append("</body>\n</html>\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("".join(parts))


def write_csv(path, stats, context, generated=None):
    generated = generated or datetime.now()
    s = summary(stats)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(['CONTEXT'])
        for key, value in context:
            writer.writerow([key, value])
        writer.writerow(['Generated', generated.strftime("%Y-%m-%d %H:%M:%S")])
        writer.writerow([])
        writer.writerow(['SUMMARY'])
        writer.writerow(['Total Buildings', s['buildings']])
        writer.writerow(['Max PPR Min', _fmt(s['max_ppr_range'][0], 2)])
        writer.writerow(['Max PPR Max', _fmt(s['max_ppr_range'][1], 2)])
        writer.writerow(['Average of Mean PPR', _fmt(s['mean_ppr_average'], 2)])
        writer.writerow(['Elevation Min', _fmt(s['elevation_range'][0], 0)])
        writer.writerow(['Elevation Max', _fmt(s['elevation_range'][1], 0)])
        writer.writerow(['Buildings without elevation', s['elevation_unknown']])
        for title, header, rows in tables(stats):
            writer.writerow([])
            writer.writerow([title.upper(), 'Count', 'Percentage'])
            for label, count in rows:
                writer.writerow([label, count, f"{_pct(count, stats['total']):.1f}%"])


# ------------------------------------------------------------ several risk layers --

def merge_buildings(records, key="bld_id"):
    """Buildings from several risk layers, each building once.

    A municipality can lie in several forecast regions, and neighbouring regions overlap, so
    the same building (same bld_id) can be in more than one layer. The record with the highest
    max_ppr is kept (the most unfavourable result). Records without an id are all kept.

    Args:
        records: dicts with at least key and 'max_ppr', in layer order
    Returns:
        (kept records in their original order, number of duplicates dropped)
    """
    best = {}
    for i, record in enumerate(records):
        building = record.get(key)
        if building is None or building == "":
            continue
        ppr = record.get('max_ppr')
        ppr = float("-inf") if ppr is None else ppr
        if building not in best or ppr > best[building][0]:
            best[building] = (ppr, i)
    keep = {i for _, i in best.values()}
    kept = [r for i, r in enumerate(records) if r.get(key) in (None, "") or i in keep]
    return kept, len(records) - len(kept)


def context_for_layers(entries, duplicates=0):
    """Context lines for one or several layers.

    entries: [{'name', 'sql', 'description', 'selected', 'source'}]; one entry gives the same
    lines as context_lines.
    """
    if len(entries) == 1:
        e = entries[0]
        return context_lines(e['name'], e.get('sql') or "", e.get('selected') or 0, e.get('source'),
                             description=e.get('description'))
    lines = [("Layers", f"{len(entries)} risk assessment layers, combined")]
    for n, e in enumerate(entries, start=1):
        lines.append((f"Layer {n}", e['name']))
        if e.get('sql'):
            lines.append((f"Layer {n} filter", e.get('description') or e['sql']))
        else:
            lines.append((f"Layer {n} filter", "none - all features of the layer"))
        if e.get('selected'):
            lines.append((f"Layer {n} selection", f"{e['selected']} selected features - only these are included"))
    if duplicates:
        lines.append(("Duplicates", f"{duplicates} buildings were in more than one layer; each is counted once "
                                    f"(with its highest max PPR)"))
    return lines
