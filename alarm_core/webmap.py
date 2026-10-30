"""Interactive map for the HTML report (no arcpy).

The report embeds the buildings (and, as background, avalanche tracks, PRAs and municipality
boundaries) as GeoJSON and draws them with Leaflet on a Kartverket (or OpenStreetMap)
background: an overview map, a priority list of the affected areas to zoom to, and a small
map per area. Opening the report needs internet access for Leaflet and the background tiles;
the tables of the report work without it.
"""

import json
import math
from html import escape

from .i18n import number as _number, tr

LEAFLET_VERSION = "1.9.4"
LEAFLET_CSS = f"https://unpkg.com/leaflet@{LEAFLET_VERSION}/dist/leaflet.css"
LEAFLET_JS = f"https://unpkg.com/leaflet@{LEAFLET_VERSION}/dist/leaflet.js"
KARTVERKET_TILES = "https://cache.kartverket.no/v1/wmts/1.0.0/topo/default/webmercator/{z}/{y}/{x}.png"
OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

# all exposed buildings in bright red (their values are in the popup and the building table)
BUILDING_COLOR = "#ff0000"
MAX_SMALL_MAPS = 12

# Background layers: very light blue tracks, PRAs as thin black outlines, municipality boundary
STYLE_TRACKS = {"color": "#9ecae1", "weight": 0.5, "fillColor": "#c6dbef", "fillOpacity": 0.35}
STYLE_PRAS = {"color": "#000000", "weight": 1, "opacity": 0.55, "fill": False}
STYLE_BOUNDARY = {"color": "#8b0000", "weight": 2.5, "dashArray": "6 4", "fill": False}



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


def _collection(items, digits=5):
    """FeatureCollection of background features [{'geometry': GeoJSON, 'props': {...}}] (or None)."""
    if not items:
        return None
    features = []
    for item in items:
        geometry = item.get('geometry')
        if not geometry or not geometry.get('coordinates'):
            continue
        features.append({'type': 'Feature', 'properties': dict(item.get('props') or {}),
                         'geometry': {'type': geometry['type'],
                                      'coordinates': _round_coords(geometry['coordinates'], digits)}})
    return {'type': 'FeatureCollection', 'features': features} if features else None


def _priority(summary):
    """Sort key of an affected area: highest max PPR first, then more buildings."""
    ppr = summary['max_ppr']
    return (ppr is None, -(ppr or 0.0), -summary['buildings'])


def areas_for(buildings, max_gap_m=500.0):
    """Affected areas of the buildings, numbered in priority order (highest max PPR first).

    Args:
        buildings: [{'lon', 'lat', 'props'}] in WGS84
    Returns:
        [{'n', 'members' (indices into buildings), 'buildings', 'max_ppr', 'classes', 'bounds',
        'lon', 'lat' (mean position), 'name' (None; set by the caller)}]
    """
    areas = cluster_areas([(b['lon'], b['lat']) for b in buildings], max_gap_m)
    summaries = []
    for area in areas:
        members = [buildings[i]['props'] for i in area['members']]
        pprs = [m.get('max_ppr') for m in members if m.get('max_ppr') is not None]
        classes = {}
        for m in members:
            classes[m.get('saf_class') or "Unknown"] = classes.get(m.get('saf_class') or "Unknown", 0) + 1
        summaries.append({'members': area['members'], 'buildings': len(members),
                          'max_ppr': max(pprs) if pprs else None, 'classes': dict(sorted(classes.items())),
                          'bounds': _round_coords(list(area['bounds'])),
                          'lon': sum(buildings[i]['lon'] for i in area['members']) / len(members),
                          'lat': sum(buildings[i]['lat'] for i in area['members']) / len(members),
                          'name': None})
    summaries.sort(key=_priority)
    for n, summary in enumerate(summaries, start=1):
        summary['n'] = n
    return summaries


def area_label(area, lang="en"):
    """'Area 3: Tønsvik' (or 'Area 3' without a name; Norwegian 'Område 3: ...')."""
    _ = tr(lang)
    return _("area_n_name", n=area['n'], name=area['name']) if area.get('name') else _("area_n", n=area['n'])


def build_payload(buildings, tracks=None, pras=None, boundaries=None, max_gap_m=500.0, areas=None):
    """Data for the map.

    Args:
        buildings: [{'lon', 'lat', 'geometry' (GeoJSON or None), 'props'}] in WGS84
        tracks, pras, boundaries: optional background features [{'geometry', 'props'}] in WGS84
        areas: the areas from areas_for (e.g. with names); computed when not given
    The affected areas are numbered in priority order (highest max PPR first).
    """
    summaries = areas if areas is not None else areas_for(buildings, max_gap_m)
    area_of = {}
    for summary in summaries:
        for i in summary['members']:
            area_of[i] = summary['n']

    features = []
    for i, b in enumerate(buildings):
        props = dict(b['props'])
        props['color'] = BUILDING_COLOR
        props['area'] = area_of.get(i)
        features.append({'type': 'Feature', 'properties': props,
                         'geometry': {'type': 'Point', 'coordinates': _round_coords([b['lon'], b['lat']])}})
        if b.get('geometry') and b['geometry'].get('type') in ('Polygon', 'MultiPolygon'):
            features.append({'type': 'Feature', 'properties': {'color': props['color'], 'outline': True},
                             'geometry': {'type': b['geometry']['type'],
                                          'coordinates': _round_coords(b['geometry']['coordinates'])}})
    context = {key: _collection(items) for key, items in
               (('tracks', tracks), ('pras', pras), ('boundaries', boundaries))}
    return {'type': 'FeatureCollection', 'features': features,
            'areas': [{k: s.get(k) for k in ('n', 'name', 'buildings', 'max_ppr', 'classes', 'bounds')}
                      for s in summaries],
            'legend': [[BUILDING_COLOR, "Exposed building (click for its values)"]],
            'context': {k: v for k, v in context.items() if v}}


def _json_for_script(data):
    """JSON that is safe inside a <script> element."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def head_html():
    """Tags for the <head> of the report."""
    return (f'<link rel="stylesheet" href="{LEAFLET_CSS}">\n'
            f'    <script src="{LEAFLET_JS}"></script>\n'
            '    <style>\n'
            '        #alarm-map { height: 560px; max-width: 1100px; border: 1px solid #ccc; }\n'
            '        .alarm-small { display: inline-block; width: 260px; margin: 6px; vertical-align: top; }\n'
            '        .alarm-small .m { height: 200px; border: 1px solid #ccc; }\n'
            '        .alarm-legend span { display: inline-block; width: 12px; height: 12px; margin: 0 4px 0 12px; '
            'border-radius: 6px; vertical-align: middle; }\n'
            '        .alarm-legend span.box { border-radius: 0; }\n'
            '        .alarm-areas td, .alarm-areas th { padding: 4px 8px; }\n'
            '        .alarm-areas button { cursor: pointer; }\n'
            '    </style>')


def _legend(payload, lang="en"):
    _ = tr(lang)
    parts = [f'<span style="background:{BUILDING_COLOR}"></span>{escape(_("legend_building"))}']
    context = payload.get('context', {})
    if 'tracks' in context:
        parts.append(f'<span class="box" style="background:{STYLE_TRACKS["fillColor"]};'
                     f'border:1px solid {STYLE_TRACKS["color"]}"></span>{escape(_("tracks"))}')
    if 'pras' in context:
        parts.append(f'<span class="box" style="border:1px solid #000"></span>{escape(_("pras"))}')
    if 'boundaries' in context:
        parts.append(f'<span class="box" style="border:2px dashed {STYLE_BOUNDARY["color"]}"></span>'
                     f'{escape(_("municipality"))}')
    return "".join(parts)


def area_caption(area, lang="en"):
    """'12 buildings, max 80.4 kPa' under a small map."""
    _ = tr(lang)
    text = _("buildings_n", n=area['buildings'])
    if area['max_ppr'] is not None:
        text += ", " + _("max_kpa", v=_number(area['max_ppr'], 1, lang))
    return text


def map_section(payload, title=None, lang="en"):
    """HTML of the map section (overview, priority list of areas, small maps)."""
    _ = tr(lang)
    title = title or _("affected_buildings")
    areas = payload['areas']
    if not payload['features']:
        return f"<h2>{escape(title)}</h2>\n<p>{escape(_('no_buildings_map'))}</p>\n"
    rows = []
    for a in areas:
        classes = ", ".join(f"{escape(str(k))}: {v}" for k, v in a['classes'].items())
        ppr = "-" if a['max_ppr'] is None else _number(a['max_ppr'], 1, lang)
        rows.append(f'<tr><td>{a["n"]}</td><td>{escape(a.get("name") or "")}</td><td>{ppr}</td>'
                    f'<td>{a["buildings"]}</td><td>{classes}</td>'
                    f'<td><button type="button" onclick="alarmZoom({a["n"]})">{escape(_("zoom"))}</button></td></tr>')
    smalls = "".join(
        f'<div class="alarm-small"><div class="m" id="alarm-small-{a["n"]}"></div>'
        f'<div><strong>{escape(area_label(a, lang))}</strong><br>{escape(area_caption(a, lang))}</div></div>'
        for a in areas[:MAX_SMALL_MAPS])
    more = (f"<p>{escape(_('more_areas', n=len(areas) - MAX_SMALL_MAPS))}</p>"
            if len(areas) > MAX_SMALL_MAPS else "")
    styles = _json_for_script({'tracks': STYLE_TRACKS, 'pras': STYLE_PRAS, 'boundaries': STYLE_BOUNDARY})
    labels = _json_for_script({'tracks': _("tracks"), 'pras': _("pras"), 'boundaries': _("municipality"),
                               'address': _("popup_address"), 'area': _("popup_area")})
    headers = "".join(f"<th>{escape(_(k))}</th>" for k in ("area", "name", "highest_ppr", "buildings", "safety_classes"))
    return f"""
    <h2>{escape(title)}</h2>
    <p class="alarm-legend">{_legend(payload, lang)}</p>
    <div id="alarm-map"><p style="padding:10px">{escape(_("map_needs_internet"))}</p></div>
    <h3>{escape(_("areas_priority"))}</h3>
    <p>{escape(_("areas_explained"))}</p>
    <table class="alarm-areas">
        <tr>{headers}<th></th></tr>
        {"".join(rows)}
    </table>
    <h3>{escape(_("areas_detail"))}</h3>
    {smalls}
    {more}
    <script type="application/json" id="alarm-data">{_json_for_script(payload)}</script>
    <script>
    (function () {{
        if (typeof L === "undefined") {{ return; }}
        var data = JSON.parse(document.getElementById("alarm-data").textContent);
        var styles = {styles};
        var labels = {labels};
        var kv = "{KARTVERKET_TILES}", osm = "{OSM_TILES}";
        function esc(v) {{
            return String(v).replace(/[&<>"]/g, function (c) {{
                return {{"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}}[c];
            }});
        }}
        function background() {{
            return L.tileLayer(kv, {{maxZoom: 18, attribution: "&copy; Kartverket"}});
        }}
        function context(map) {{
            var layers = {{}};
            [["tracks", labels.tracks], ["pras", labels.pras], ["boundaries", labels.boundaries]].forEach(function (k) {{
                var collection = data.context[k[0]];
                if (!collection) {{ return; }}
                layers[k[1]] = L.geoJSON(collection, {{
                    style: styles[k[0]],
                    interactive: k[0] === "boundaries",
                    onEachFeature: function (f, layer) {{
                        if (k[0] === "boundaries" && f.properties.name) {{ layer.bindTooltip(f.properties.name); }}
                    }}
                }}).addTo(map);
            }});
            return layers;
        }}
        function buildings(map) {{
            L.geoJSON(data, {{
                filter: function (f) {{ return f.properties.outline; }},
                style: function (f) {{ return {{color: f.properties.color, weight: 1, fillOpacity: 0.4}}; }},
                interactive: false
            }}).addTo(map);
            return L.geoJSON(data, {{
                filter: function (f) {{ return !f.properties.outline; }},
                pointToLayer: function (f, ll) {{
                    return L.circleMarker(ll, {{radius: 5, color: "#333", weight: 1,
                                               fillColor: f.properties.color, fillOpacity: 1}});
                }},
                onEachFeature: function (f, layer) {{
                    var p = f.properties, rows = [];
                    ["address", "bld_id", "saf_class", "max_ppr", "mean_ppr", "pra_elev", "pra_aspct", "source"].forEach(function (k) {{
                        if (p[k] !== undefined && p[k] !== null && p[k] !== "") {{ rows.push("<b>" + (k === "address" ? labels.address : k) + "</b>: " + esc(p[k])); }}
                    }});
                    if (p.area) {{
                        var a = data.areas[p.area - 1];
                        rows.push("<b>" + labels.area + "</b>: " + p.area + (a && a.name ? " " + esc(a.name) : ""));
                    }}
                    layer.bindPopup(rows.join("<br>"));
                }}
            }}).addTo(map);
        }}
        function boundsOf(a) {{ return L.latLngBounds([[a.bounds[1], a.bounds[0]], [a.bounds[3], a.bounds[2]]]); }}
        var el = document.getElementById("alarm-map");
        el.innerHTML = "";
        var map = L.map(el, {{preferCanvas: true}});
        var kvLayer = background().addTo(map);
        var overlays = context(map);
        var markers = buildings(map);
        L.control.layers({{"Kartverket topo": kvLayer,
                          "OpenStreetMap": L.tileLayer(osm, {{maxZoom: 19, attribution: "&copy; OpenStreetMap"}})}},
                         overlays).addTo(map);
        L.control.scale({{imperial: false}}).addTo(map);
        map.fitBounds(markers.getBounds().pad(0.05));
        window.alarmZoom = function (n) {{
            var a = data.areas[n - 1];
            map.fitBounds(boundsOf(a).pad(0.5), {{maxZoom: 16}});
            el.scrollIntoView({{behavior: "smooth"}});
        }};
        data.areas.slice(0, {MAX_SMALL_MAPS}).forEach(function (a) {{
            var small = L.map("alarm-small-" + a.n, {{attributionControl: false, preferCanvas: true}});
            background().addTo(small);
            context(small);
            buildings(small);
            small.fitBounds(boundsOf(a).pad(0.5), {{maxZoom: 16}});
        }});
    }})();
    </script>
"""
