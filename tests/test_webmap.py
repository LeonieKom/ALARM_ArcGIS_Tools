import json
import re

from alarm_core import report, webmap


def test_ppr_colors_follow_the_classes():
    assert webmap.ppr_color(None) == "#ffb3d9"
    assert webmap.ppr_color(24.9) == "#ffb3d9"
    assert webmap.ppr_color(25) == "#ff66b3"
    assert webmap.ppr_color(199) == "#cc0066"
    assert webmap.ppr_color(5000) == "#990050"


def test_close_buildings_form_one_area_far_ones_another():
    # two groups ~3 km apart near Tromsø; inside a group the points are ~200 m apart (chained)
    a = [(18.95 + i * 0.0036, 69.65) for i in range(4)]       # 0.0036 deg lon at 69.65 N ~ 140 m
    b = [(19.05, 69.65), (19.05, 69.6518)]                      # 0.0018 deg lat ~ 200 m
    areas = webmap.cluster_areas(a + b, max_gap_m=500)
    assert [len(x['members']) for x in areas] == [4, 2]
    assert areas[1]['members'] == [4, 5]
    assert areas[0]['bounds'][0] == 18.95


def test_single_and_no_points():
    assert webmap.cluster_areas([]) == []
    assert len(webmap.cluster_areas([(10.0, 60.0)])) == 1


def buildings():
    return [
        {'lon': 18.95, 'lat': 69.65, 'geometry': {'type': 'Polygon', 'coordinates': [[[18.95, 69.65], [18.951, 69.65],
                                                                                      [18.951, 69.651], [18.95, 69.65]]]},
         'props': {'bld_id': 1, 'saf_class': 'S2', 'max_ppr': 30.0}},
        {'lon': 18.952, 'lat': 69.65, 'geometry': None, 'props': {'bld_id': 2, 'saf_class': 'S3', 'max_ppr': 120.0}},
        {'lon': 19.5, 'lat': 69.7, 'geometry': None, 'props': {'bld_id': 3, 'saf_class': None, 'max_ppr': None}},
    ]


def test_payload_has_points_outlines_and_area_summaries():
    p = webmap.build_payload(buildings())
    points = [f for f in p['features'] if not f['properties'].get('outline')]
    outlines = [f for f in p['features'] if f['properties'].get('outline')]
    assert len(points) == 3 and len(outlines) == 1
    assert points[1]['properties']['color'] == "#cc0066" and points[1]['properties']['area'] == 1
    assert p['areas'][0] == {'n': 1, 'buildings': 2, 'max_ppr': 120.0, 'classes': {'S2': 1, 'S3': 1},
                             'bounds': [18.95, 69.65, 18.952, 69.65]}
    assert p['areas'][1]['classes'] == {'Unknown': 1} and p['areas'][1]['max_ppr'] is None


def test_map_section_embeds_safe_json_and_one_small_map_per_area():
    b = buildings()
    b[0]['props']['saf_class'] = "</script><b>x"
    html = webmap.map_section(webmap.build_payload(b))
    assert "</script><b>x" not in html                          # cannot close the script element
    data = re.search(r'<script type="application/json" id="alarm-data">(.*?)</script>', html, re.S).group(1)
    assert json.loads(data)['areas'][0]['buildings'] == 2       # still valid JSON
    assert html.count('class="alarm-small"') == 2
    assert 'onclick="alarmZoom(2)"' in html


def test_many_areas_get_small_maps_for_the_first_ones_only():
    many = [{'lon': 10.0 + i * 0.5, 'lat': 60.0, 'geometry': None, 'props': {'max_ppr': 1.0}} for i in range(15)]
    html = webmap.map_section(webmap.build_payload(many))
    assert html.count('class="alarm-small"') == webmap.MAX_SMALL_MAPS
    assert "3 further areas" in html


def test_empty_map():
    assert "No buildings to show" in webmap.map_section(webmap.build_payload([]))


def test_report_with_map(tmp_path):
    rows = [("S2", 30.0, 10.0, 200.0, "E"), ("S3", 120.0, 50.0, 300.0, "S")]
    path = tmp_path / "r.html"
    report.write_html(path, report.collect(rows), report.context_lines("lyr", "", 0),
                      map_html=webmap.map_section(webmap.build_payload(buildings()[:2])), head_extra=webmap.head_html())
    html = path.read_text(encoding="utf-8")
    assert webmap.LEAFLET_JS in html and 'id="alarm-map"' in html
    assert html.index('id="alarm-map"') < html.index("Buildings by Safety Class")     # map before the tables


def test_report_without_map_has_no_leaflet(tmp_path):
    path = tmp_path / "r.html"
    report.write_html(path, report.collect([("S2", 30.0, 10.0, 200.0, "E")]), report.context_lines("lyr", "", 0))
    assert "leaflet" not in path.read_text(encoding="utf-8")
