"""Interactive map for the HTML report (no arcpy).

The report embeds the buildings as GeoJSON and draws them with Leaflet on a Kartverket (or
OpenStreetMap) background: an overview map, a list of the affected areas to zoom to, and a
small map per area. Opening the report needs internet access for Leaflet and the background
tiles; the tables of the report work without it.
"""

import json
import math
from html import escape

LEAFLET_VERSION = "1.9.4"
LEAFLET_CSS = f"https://unpkg.com/leaflet@{LEAFLET_VERSION}/dist/leaflet.css"
LEAFLET_JS = f"https://unpkg.com/leaflet@{LEAFLET_VERSION}/dist/leaflet.js"
KARTVERKET_TILES = "https://cache.kartverket.no/v1/wmts/1.0.0/topo/default/webmercator/{z}/{y}/{x}.png"
OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

# max_ppr classes and colours, as in the Risk Assessment layer symbology
PPR_COLORS = [(25, "#ffb3d9", "0-25 kPa"), (50, "#ff66b3", "25-50 kPa"), (100, "#ff0080", "50-100 kPa"),
              (200, "#cc0066", "100-200 kPa"), (None, "#990050", "> 200 kPa")]
MAX_SMALL_MAPS = 12


def ppr_color(value):
    value = 0.0 if value is None else value
    for upper, color, _ in PPR_COLORS:
        if upper is None or value < upper:
            return color
    return PPR_COLORS[-1][1]


def _meters(lon, lat, lat0):
    """Local planar coordinates in metres (equirectangular, good enough for grouping)."""
    k = 111320.0
    return lon * k * math.cos(math.radians(lat0)), lat * k


def cluster_areas(points, max_gap_m=500.0):
    """Group points into affected areas: points closer than max_gap_m (chained) share an area.

    Args:
        points: [(lon, lat)] in WGS84
    Returns:
        [{'members': [indices], 'bounds': (min_lon, min_lat, max_lon, max_lat)}], largest first
    """
    if not points:
        return []
    lat0 = sum(p[1] for p in points) / len(points)
    xy = [_meters(lon, lat, lat0) for lon, lat in points]
    parent = list(range(len(points)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    cell = max_gap_m
    grid = {}
    for i, (x, y) in enumerate(xy):
        grid.setdefault((int(x // cell), int(y // cell)), []).append(i)
    for (cx, cy), members in grid.items():
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grid.get((cx + dx, cy + dy), ()):
                    for i in members:
                        if i < j and math.dist(xy[i], xy[j]) <= max_gap_m:
                            parent[find(i)] = find(j)

    groups = {}
    for i in range(len(points)):
        groups.setdefault(find(i), []).append(i)
    areas = []
    for members in groups.values():
        lons = [points[i][0] for i in members]
        lats = [points[i][1] for i in members]
        areas.append({'members': sorted(members), 'bounds': (min(lons), min(lats), max(lons), max(lats))})
    areas.sort(key=lambda a: (-len(a['members']), a['bounds']))
    return areas


def _round_coords(obj, digits=6):
    if isinstance(obj, (list, tuple)):
        return [_round_coords(v, digits) for v in obj]
    if isinstance(obj, float):
        return round(obj, digits)
    return obj


def build_payload(buildings, max_gap_m=500.0):
    """Data for the map from buildings [{'lon', 'lat', 'geometry' (GeoJSON or None), 'props'}]."""
    areas = cluster_areas([(b['lon'], b['lat']) for b in buildings], max_gap_m)
    area_of = {}
    for n, area in enumerate(areas, start=1):
        for i in area['members']:
            area_of[i] = n
    features = []
    for i, b in enumerate(buildings):
        props = dict(b['props'])
        props['color'] = ppr_color(props.get('max_ppr'))
        props['area'] = area_of.get(i)
        features.append({'type': 'Feature', 'properties': props,
                         'geometry': {'type': 'Point', 'coordinates': _round_coords([b['lon'], b['lat']])}})
        if b.get('geometry') and b['geometry'].get('type') in ('Polygon', 'MultiPolygon'):
            features.append({'type': 'Feature', 'properties': {'color': props['color'], 'outline': True},
                             'geometry': {'type': b['geometry']['type'],
                                          'coordinates': _round_coords(b['geometry']['coordinates'])}})
    summaries = []
    for n, area in enumerate(areas, start=1):
        members = [buildings[i]['props'] for i in area['members']]
        pprs = [m.get('max_ppr') for m in members if m.get('max_ppr') is not None]
        classes = {}
        for m in members:
            classes[m.get('saf_class') or "Unknown"] = classes.get(m.get('saf_class') or "Unknown", 0) + 1
        summaries.append({'n': n, 'buildings': len(members), 'max_ppr': max(pprs) if pprs else None,
                          'classes': dict(sorted(classes.items())), 'bounds': _round_coords(list(area['bounds']))})
    return {'type': 'FeatureCollection', 'features': features, 'areas': summaries,
            'legend': [[color, text] for _, color, text in PPR_COLORS]}


def _json_for_script(data):
    """JSON that is safe inside a <script> element."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def head_html():
    """Tags for the <head> of the report."""
    return (f'<link rel="stylesheet" href="{LEAFLET_CSS}">\n'
            f'    <script src="{LEAFLET_JS}"></script>\n'
            '    <style>\n'
            '        #alarm-map { height: 520px; max-width: 1100px; border: 1px solid #ccc; }\n'
            '        .alarm-small { display: inline-block; width: 260px; margin: 6px; vertical-align: top; }\n'
            '        .alarm-small .m { height: 200px; border: 1px solid #ccc; }\n'
            '        .alarm-legend span { display: inline-block; width: 12px; height: 12px; margin: 0 4px 0 12px; '
            'border-radius: 6px; vertical-align: middle; }\n'
            '        .alarm-areas td, .alarm-areas th { padding: 4px 8px; }\n'
            '        .alarm-areas button { cursor: pointer; }\n'
            '    </style>')


def map_section(payload, title="Affected buildings"):
    """HTML of the map section (overview, list of areas, small maps)."""
    areas = payload['areas']
    if not payload['features']:
        return f"<h2>{escape(title)}</h2>\n<p>No buildings to show on the map.</p>\n"
    rows = []
    for a in areas:
        classes = ", ".join(f"{escape(str(k))}: {v}" for k, v in a['classes'].items())
        ppr = "-" if a['max_ppr'] is None else f"{a['max_ppr']:.1f}"
        rows.append(f'<tr><td>{a["n"]}</td><td>{a["buildings"]}</td><td>{ppr}</td><td>{classes}</td>'
                    f'<td><button type="button" onclick="alarmZoom({a["n"]})">Zoom</button></td></tr>')
    smalls = "".join(
        f'<div class="alarm-small"><div class="m" id="alarm-small-{a["n"]}"></div>'
        f'<div>Area {a["n"]}: {a["buildings"]} buildings</div></div>'
        for a in areas[:MAX_SMALL_MAPS])
    more = (f"<p>{len(areas) - MAX_SMALL_MAPS} further areas are listed above (Zoom).</p>"
            if len(areas) > MAX_SMALL_MAPS else "")
    legend = "".join(f'<span style="background:{c}"></span>{escape(t)}' for c, t in payload['legend'])
    return f"""
    <h2>{escape(title)}</h2>
    <p class="alarm-legend">Max PPR: {legend}</p>
    <div id="alarm-map"><p style="padding:10px">The map needs internet access (Leaflet and background map).</p></div>
    <h3>Affected areas</h3>
    <p>Buildings closer than 500 m to each other form one area. Click a building for its values.</p>
    <table class="alarm-areas">
        <tr><th>Area</th><th>Buildings</th><th>Highest max PPR [kPa]</th><th>Safety classes</th><th></th></tr>
        {"".join(rows)}
    </table>
    <h3>Areas in detail</h3>
    {smalls}
    {more}
    <script type="application/json" id="alarm-data">{_json_for_script(payload)}</script>
    <script>
    (function () {{
        if (typeof L === "undefined") {{ return; }}
        var data = JSON.parse(document.getElementById("alarm-data").textContent);
        var kv = "{KARTVERKET_TILES}", osm = "{OSM_TILES}";
        function background() {{
            return L.tileLayer(kv, {{maxZoom: 18, attribution: "&copy; Kartverket"}});
        }}
        function draw(map, interactive) {{
            L.geoJSON(data, {{
                filter: function (f) {{ return f.properties.outline; }},
                style: function (f) {{ return {{color: f.properties.color, weight: 1, fillOpacity: 0.4}}; }},
                interactive: false
            }}).addTo(map);
            return L.geoJSON(data, {{
                filter: function (f) {{ return !f.properties.outline; }},
                pointToLayer: function (f, ll) {{
                    return L.circleMarker(ll, {{radius: 5, color: "#333", weight: 1,
                                               fillColor: f.properties.color, fillOpacity: 0.9}});
                }},
                onEachFeature: function (f, layer) {{
                    if (!interactive) {{ return; }}
                    var p = f.properties, rows = [];
                    ["bld_id", "saf_class", "max_ppr", "mean_ppr", "pra_elev", "pra_aspct"].forEach(function (k) {{
                        if (p[k] !== undefined && p[k] !== null) {{ rows.push("<b>" + k + "</b>: " + p[k]); }}
                    }});
                    if (p.area) {{ rows.push("<b>area</b>: " + p.area); }}
                    layer.bindPopup(rows.join("<br>"));
                }}
            }}).addTo(map);
        }}
        function boundsOf(a) {{ return L.latLngBounds([[a.bounds[1], a.bounds[0]], [a.bounds[3], a.bounds[2]]]); }}
        var el = document.getElementById("alarm-map");
        el.innerHTML = "";
        var map = L.map(el);
        var kvLayer = background().addTo(map);
        L.control.layers({{"Kartverket topo": kvLayer,
                          "OpenStreetMap": L.tileLayer(osm, {{maxZoom: 19, attribution: "&copy; OpenStreetMap"}})}})
            .addTo(map);
        L.control.scale({{imperial: false}}).addTo(map);
        var markers = draw(map, true);
        map.fitBounds(markers.getBounds().pad(0.05));
        data.areas.forEach(function (a) {{
            L.rectangle(boundsOf(a).pad(0.3), {{color: "#2196F3", weight: 1, fill: false}})
                .bindTooltip("Area " + a.n).addTo(map);
        }});
        window.alarmZoom = function (n) {{
            var a = data.areas[n - 1];
            map.fitBounds(boundsOf(a).pad(0.5), {{maxZoom: 16}});
            el.scrollIntoView({{behavior: "smooth"}});
        }};
        data.areas.slice(0, {MAX_SMALL_MAPS}).forEach(function (a) {{
            var small = L.map("alarm-small-" + a.n, {{attributionControl: false}});
            background().addTo(small);
            draw(small, true);
            small.fitBounds(boundsOf(a).pad(0.5), {{maxZoom: 16}});
        }});
    }})();
    </script>
"""
