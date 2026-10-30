"""Statistics report for a Risk Assessment layer (buildings), without arcpy.

The tool reads the rows with an arcpy cursor (so the layer's filter and selection apply) and
passes them here. The report states which filter and selection were active, so a report of
a filtered layer cannot be mistaken for one of the whole layer.
"""

import csv
import re
from datetime import datetime
from html import escape

from . import symbols
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


# ---------------------------------------------------- scenario and avalanche problem --

_PARAMS = re.compile(r"(\d+)-(\d+)(?:_|,\s*)prox(\d+)(?:_|,\s*)rel(\d+(?:[._]\d+)?)m")
_SCENARIO_FOLDER = re.compile(r"(?:^|[\\/_ ])([A-Z][0-9]?)_\d+-\d+_prox")


def scenario_params(text):
    """{'t_high', 't_low', 'proximity', 'release'} from a file name, folder or '80-60, prox0, rel1.2m'."""
    m = _PARAMS.search(text or "")
    if not m:
        return None
    return {'t_high': int(m.group(1)), 't_low': int(m.group(2)), 'proximity': int(m.group(3)),
            'release': float(m.group(4).replace("_", "."))}


def scenario_id(text):
    """Scenario letter from a result path or file name ('.../A_80-60_prox0_rel1.2m/...' -> 'A')."""
    m = _SCENARIO_FOLDER.search(text or "")
    return m.group(1) if m else None


def describe_params(params):
    return (f"PRA thresholds {params['t_high']} / {params['t_low']} %, proximity {params['proximity']} m, "
            f"release thickness {params['release']:g} m")


def problem_from_filters(parsed):
    """One avalanche problem (aspects, elev_min, elev_max) for the filters of several layers.

    parsed: [filters.parse_description(...)] of the risk layers. Without a filter a layer
    covers all aspects and elevations; several layers together cover the union.
    """
    if not parsed:
        return list(symbols.ASPECTS), None, None
    aspects = set()
    for p in parsed:
        aspects |= set(p['aspects'] if p['aspects'] is not None else symbols.ASPECTS)
    mins = [p['elev_min'] for p in parsed]
    maxs = [p['elev_max'] for p in parsed]
    elev_min = None if any(v is None for v in mins) else min(mins)
    elev_max = None if any(v is None for v in maxs) else max(maxs)
    return symbols.aspects_in_order(aspects), elev_min, elev_max


def scenario_section(scenarios, aspects, elev_min, elev_max):
    """HTML: the scenario(s) of the report and the avalanche problem symbol (as in Varsom).

    scenarios: [(label, params or None)], e.g. [("A (ALARM2.2)", {...})]
    """
    lines = []
    for label, params in scenarios:
        text = describe_params(params) if params else "parameters not known"
        lines.append(f"<p><strong>Scenario {escape(label)}:</strong> {escape(text)}</p>")
    all_aspects = len(aspects) == len(symbols.ASPECTS)
    aspect_text = "all aspects" if all_aspects else ", ".join(aspects) if aspects else "none"
    return f"""
    <div class="alarm-scenario">
        <div class="alarm-scenario-text">
            <h2>Scenario</h2>
            {"".join(lines) or "<p>Scenario not known.</p>"}
            <p>Release areas shown: <strong>{escape(aspect_text)}</strong>,
               <strong>{escape(symbols.elevation_text(elev_min, elev_max))}</strong>
               {"" if all_aspects and elev_min is None and elev_max is None else "(from the layer filter)"}</p>
        </div>
        <div class="alarm-problem">
            <div class="alarm-problem-title">Avalanche problem (as in Varsom)</div>
            <div class="alarm-problem-symbols">
                <figure>{symbols.rose_svg(aspects, size=110, title="Aspects: " + aspect_text)}
                    <figcaption>{escape(aspect_text)}</figcaption></figure>
                <figure>{symbols.elevation_svg(elev_min, elev_max, size=120)}
                    <figcaption>{escape(symbols.elevation_text(elev_min, elev_max))}</figcaption></figure>
            </div>
        </div>
    </div>
"""


# ------------------------------------------------------------------ building table --

def _numbers(text):
    out = []
    for part in str(text or "").replace(";", ",").split(","):
        try:
            out.append(float(part))
        except ValueError:
            continue
    return out


def building_row(record, problem=None):
    """Aspects and elevation text of a building's release areas.

    Uses the lists pra_asplst / pra_elvls of the risk layer (all PRAs reaching the building,
    pairwise), else pra_aspct / pra_elev (the main PRA). With problem (aspects, elev_min,
    elev_max) only the release areas inside it are listed, as in the workshop tables
    (falls back to all when none or the lists do not pair up). Elevations are rounded to 10 m.
    """
    raw_aspects = [a.strip().upper() for a in str(record.get('pra_asplst') or "").split(",") if a.strip()]
    raw_elevs = [p.strip() for p in str(record.get('pra_elvls') or "").split(",") if p.strip()]
    aspects = symbols.split_aspects(record.get('pra_asplst')) or symbols.split_aspects(record.get('pra_aspct'))
    elevations = _numbers(record.get('pra_elvls')) or _numbers(record.get('pra_elev'))
    if problem and raw_aspects and len(raw_aspects) == len(raw_elevs):
        wanted, lo, hi = problem
        pairs = [(a, e) for a, e in zip(raw_aspects, _numbers(",".join(raw_elevs)))
                 if a in wanted and (lo is None or e >= lo) and (hi is None or e <= hi)]
        if pairs:
            aspects = symbols.aspects_in_order(a for a, _ in pairs)
            elevations = [e for _, e in pairs]
    if elevations:
        lo, hi = round(min(elevations), -1), round(max(elevations), -1)
        elevation = f"{lo:.0f} m" if lo == hi else f"{lo:.0f}-{hi:.0f} m"
    else:
        elevation = "-"
    return aspects, elevation


def buildings_table(records, area_names=None, hide_classes=("S1",), problem=None):
    """HTML table of the buildings, highest max PPR first.

    records: dicts with saf_class, max_ppr, address, area (number) and the PRA fields.
    Buildings of hide_classes are listed but hidden until 'show' is ticked. problem
    (aspects, elev_min, elev_max) limits the release areas listed (see building_row).
    """
    area_names = area_names or {}
    rows = sorted(records, key=lambda r: (r.get('max_ppr') is None, -(r.get('max_ppr') or 0.0)))
    symbols_used, body = {}, []
    hidden = rank = 0
    for r in rows:
        aspects, elevation = building_row(r, problem)
        key = "-".join(aspects) or "none"
        symbols_used[key] = aspects
        area = r.get('area')
        area_text = f"{area}. {area_names[area]}" if area in area_names and area_names[area] else (
            str(area) if area else "")
        hide = r.get('saf_class') in hide_classes
        if hide:
            hidden += 1
            row_start, shown_rank = '<tr class="alarm-hidden-class">', ""
        else:
            rank += 1
            row_start, shown_rank = "<tr>", str(rank)
        ppr = "-" if r.get('max_ppr') is None else f"{r['max_ppr']:.1f}"
        body.append(f'{row_start}<td>{shown_rank}</td>'
                    f'<td>{escape(str(r.get("saf_class") or ""))}</td><td>{escape(r.get("address") or "-")}</td>'
                    f'<td>{escape(area_text)}</td><td class="num">{ppr}</td>'
                    f'<td><svg class="alarm-rose" width="20" height="20"><use href="#rose-{key}"/></svg> '
                    f'{escape(", ".join(aspects) or "-")}</td><td>{escape(elevation)}</td></tr>')
    defs = "".join(f'<symbol id="rose-{k}" viewBox="0 0 24 24">{symbols.rose_paths(a)}</symbol>'
                   for k, a in symbols_used.items())
    toggle = (f'<p><label><input type="checkbox" onchange="document.getElementById(\'alarm-buildings\')'
              f'.classList.toggle(\'show-all\', this.checked)"> Also show the {hidden} buildings of class '
              f'{", ".join(hide_classes)}</label></p>') if hidden else ""
    hidden_note = f" (the {hidden} buildings of class {', '.join(hide_classes)} are hidden)" if hidden else ""
    return f"""
    <h2>Exposed buildings by pressure</h2>
    <p>{rank} buildings{hidden_note}, highest max PPR first.
       Aspect and elevation are those of the release areas reaching the building; the rose shows the aspects (N at the top), as in Varsom.</p>
    {toggle}
    <svg width="0" height="0" style="position:absolute">{defs}</svg>
    <table id="alarm-buildings" class="alarm-buildings">
        <tr><th>Rank</th><th>Class</th><th>Address</th><th>Area</th><th>Max PPR [kPa]</th>
            <th>Aspect of release area</th><th>Elevation of release area</th></tr>
        {"".join(body)}
    </table>
    <p class="alarm-note">Address: nearest address (Kartverket), "near" = more than 30 m away.</p>
"""


REPORT_STYLE = """
        .alarm-scenario { display: flex; flex-wrap: wrap; gap: 30px; align-items: flex-start; margin: 20px 0; }
        .alarm-scenario-text { flex: 1 1 380px; }
        .alarm-problem-title { font-weight: bold; margin-bottom: 6px; }
        .alarm-problem-symbols { display: flex; gap: 16px; align-items: flex-end; }
        .alarm-problem figure { margin: 0; text-align: center; }
        .alarm-problem figcaption { font-weight: bold; margin-top: 4px; }
        table.alarm-buildings { max-width: 1200px; }
        table.alarm-buildings th { background-color: #263238; }
        table.alarm-buildings td.num { text-align: right; }
        table.alarm-buildings .alarm-rose { vertical-align: middle; }
        table.alarm-buildings tr.alarm-hidden-class { display: none; }
        table.alarm-buildings.show-all tr.alarm-hidden-class { display: table-row; }
        .alarm-note { color: #666; font-size: 0.9em; }
"""


def write_html(path, stats, context, generated=None, map_html=None, head_extra=None,
               scenario_html=None, buildings_html=None):
    """The report as HTML; map_html / head_extra add the map (see alarm_core.webmap),
    scenario_html the scenario and avalanche problem, buildings_html the building table."""
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
{REPORT_STYLE}
    </style>
    {head_extra or ""}
</head>
<body>
    <h1>Risk Assessment Report</h1>
    <div class="context">{ctx}<p><strong>Generated:</strong> {generated.strftime("%Y-%m-%d %H:%M:%S")}</p></div>
{scenario_html or ""}

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
    if buildings_html:
        parts.append(buildings_html)
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


def write_csv(path, stats, context, generated=None, buildings=None, area_names=None, problem=None):
    """The report as CSV; buildings (records as for buildings_table) adds the building list."""
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
        if buildings:
            area_names = area_names or {}
            writer.writerow([])
            writer.writerow(['BUILDINGS', 'bld_id', 'Safety Class', 'Address', 'Area', 'Area name',
                             'Max PPR [kPa]', 'Aspect of release area', 'Elevation of release area'])
            ordered = sorted(buildings, key=lambda r: (r.get('max_ppr') is None, -(r.get('max_ppr') or 0.0)))
            for rank, r in enumerate(ordered, start=1):
                aspects, elevation = building_row(r, problem)
                writer.writerow([rank, r.get('bld_id'), r.get('saf_class') or "", r.get('address') or "",
                                 r.get('area') or "", area_names.get(r.get('area'), ""),
                                 _fmt(r.get('max_ppr'), 1), ", ".join(aspects), elevation])


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
