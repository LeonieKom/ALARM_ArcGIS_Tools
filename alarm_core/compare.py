"""Scenario comparison: counts with one shared filter, and the HTML/CSV tables (no arcpy).

The attribute tables are read directly from the .dbf files, so no layers have to be loaded.
"""

import csv
from datetime import datetime
from html import escape
from pathlib import Path

from .data import find_file
from .dbf import read_dbf_columns, to_number
from .filters import criteria_notes, matches_numeric, matches_risk

PPR_CLASSES = [("0-25 kPa", 0, 25), ("25-50 kPa", 25, 50), ("50-100 kPa", 50, 100),
               ("100-200 kPa", 100, 200), (">200 kPa", 200, None)]

# (key, file pattern, elevation field, aspect field) for the layers with numeric aspect in degrees
NUMERIC_LAYERS = (
    ('tracks', "tracks_*.shp", "pra_elev", "pra_aspdeg"),
    ('pras', "pra_*.shp", "elev_med", "aspect_deg"),
)


def compute_scenario(scenario_id, scenario_dir, criteria, label=None, warn=None):
    """Count features per layer type for one scenario, with and without the filter.

    Args:
        warn: optional callable receiving warning texts (e.g. arcpy.AddWarning)
    """
    warn = warn or (lambda message: None)
    scenario_dir = Path(scenario_dir)
    out = {'id': scenario_id, 'label': label or scenario_id, 'dir': scenario_dir.name}

    # Tracks and PRAs: elevation and aspect
    for key, pattern, elev_field, aspect_field in NUMERIC_LAYERS:
        shp = find_file(scenario_dir, pattern, warn=warn)
        if not shp:
            out[key] = None
            warn(f"  Scenario {scenario_id}: {pattern} not found")
            continue
        cols, total = read_dbf_columns(shp.with_suffix(".dbf"), [elev_field, aspect_field])
        matched = sum(1 for elev, asp in zip(cols[elev_field], cols[aspect_field])
                      if matches_numeric(to_number(elev), to_number(asp), criteria))
        out[key] = {'total': total, 'matched': matched}

    # Risk assessment: buildings
    risk_dir = scenario_dir / "risk_assessment"
    risk_shp = find_file(risk_dir, "risk_*.shp", warn=warn) if risk_dir.exists() else None
    if not risk_shp:
        out['risk'] = None
        warn(f"  Scenario {scenario_id}: risk assessment not found")
        return out

    cols, total = read_dbf_columns(risk_shp.with_suffix(".dbf"),
                                   ["saf_class", "max_ppr", "pra_elev", "pra_aspct"])
    saf_counts = {}
    ppr_counts = {label_: 0 for label_, _, _ in PPR_CLASSES}
    ppr_values = []
    for saf, ppr, elev, asp in zip(cols["saf_class"], cols["max_ppr"], cols["pra_elev"], cols["pra_aspct"]):
        if not matches_risk(saf, ppr, elev, asp, criteria):
            continue
        saf_counts[saf or "Unknown"] = saf_counts.get(saf or "Unknown", 0) + 1
        value = ppr if ppr is not None else 0.0
        ppr_values.append(value)
        for class_label, lo, hi in PPR_CLASSES:
            if value >= lo and (hi is None or value < hi):
                ppr_counts[class_label] += 1
                break
    out['risk'] = {
        'total': total, 'matched': len(ppr_values), 'saf': saf_counts, 'ppr_classes': ppr_counts,
        'ppr_max': max(ppr_values) if ppr_values else None,
        'ppr_mean': (sum(ppr_values) / len(ppr_values)) if ppr_values else None,
    }
    return out


# ------------------------------------------------------------------------ table --

def _fmt_count(info):
    if info is None:
        return "n/a"
    return f"{info['matched']:,} / {info['total']:,}"


def _fmt_num(value, digits=1):
    return "-" if value is None else f"{value:,.{digits}f}"


def build_rows(results):
    """Table rows: (kind, label, [one value per scenario]); kind is 'section' or 'row'."""
    rows = [("section", "Features (filtered / total)", None),
            ("row", "Avalanche tracks", [_fmt_count(r.get('tracks')) for r in results]),
            ("row", "PRAs", [_fmt_count(r.get('pras')) for r in results]),
            ("row", "Buildings", [_fmt_count(r.get('risk')) for r in results])]

    saf_classes = sorted({c for r in results if r.get('risk') for c in r['risk']['saf']})
    rows.append(("section", "Buildings by safety class (filtered)", None))
    for cls in saf_classes:
        rows.append(("row", cls, [str(r['risk']['saf'].get(cls, 0)) if r.get('risk') else "n/a" for r in results]))
    if not saf_classes:
        rows.append(("row", "-", ["-" for _ in results]))

    rows.append(("section", "Buildings by max PPR (filtered)", None))
    for label, _, _ in PPR_CLASSES:
        rows.append(("row", label, [str(r['risk']['ppr_classes'][label]) if r.get('risk') else "n/a" for r in results]))
    rows.append(("row", "Max PPR [kPa]", [_fmt_num(r['risk']['ppr_max']) if r.get('risk') else "n/a" for r in results]))
    rows.append(("row", "Mean PPR [kPa]", [_fmt_num(r['risk']['ppr_mean']) if r.get('risk') else "n/a" for r in results]))
    return rows


def table_lines(rows, results):
    """The table as plain text lines (for the tool messages)."""
    lines = [f"{'':32}" + "".join(f"{r['id']:>18}" for r in results)]
    for kind, label, values in rows:
        if kind == "section":
            lines.append(f"-- {label}")
        else:
            lines.append(f"{label:32}" + "".join(f"{v:>18}" for v in values))
    return lines


def write_csv(path, results, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(["Metric"] + [f"{r['id']} ({r['dir']})" for r in results])
        for kind, label, values in rows:
            writer.writerow([label] + ([""] * len(results) if kind == "section" else values))


def write_html(path, region, results, rows, criteria, generated=None):
    head = "".join(f"<th>{escape(r['id'])}<br><small>{escape(r['label'])}</small></th>" for r in results)
    body = []
    for kind, label, values in rows:
        if kind == "section":
            body.append(f'<tr class="section"><td colspan="{len(results) + 1}">{escape(label)}</td></tr>')
        else:
            cells = "".join(f"<td>{escape(v)}</td>" for v in values)
            body.append(f"<tr><td>{escape(label)}</td>{cells}</tr>")
    note_items = "".join(f"<li>{escape(n)}</li>" for n in criteria_notes(criteria))
    generated = generated or datetime.now()
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Scenario comparison - {escape(region)}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        table {{ border-collapse: collapse; margin: 10px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 6px 12px; text-align: right; }}
        th:first-child, td:first-child {{ text-align: left; }}
        th {{ background-color: #4CAF50; color: white; }}
        tr.section td {{ background-color: #e7f3fe; font-weight: bold; text-align: left; }}
        .filter {{ background-color: #f2f2f2; padding: 10px 15px; border-left: 6px solid #2196F3; }}
        small {{ font-weight: normal; }}
    </style>
</head>
<body>
    <h1>Scenario comparison: {escape(region)}</h1>
    <p>Generated: {generated.strftime("%Y-%m-%d %H:%M:%S")}</p>
    <div class="filter"><strong>Filter applied to every scenario</strong><ul>{note_items}</ul></div>
    <table>
        <tr><th>Metric</th>{head}</tr>
        {"".join(body)}
    </table>
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
