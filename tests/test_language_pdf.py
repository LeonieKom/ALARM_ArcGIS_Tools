"""Norwegian report texts and the PDF report."""
import io
import re

import pytest

from alarm_core import i18n, places, report, symbols, webmap
from test_report import ROWS, building_records


def test_every_text_has_both_languages():
    for key, texts in i18n.TEXT.items():
        assert len(texts) == 2 and all(texts), key


def test_aspects_and_numbers_in_norwegian():
    assert [i18n.aspect(a, "no") for a in symbols.ASPECTS] == ["N", "NØ", "Ø", "SØ", "S", "SV", "V", "NV"]
    assert i18n.aspect("NE", "en") == "NE"
    assert i18n.number(80.44, 1, "no") == "80,4" and i18n.number(80.44, 1, "en") == "80.4"


def test_elevation_texts_in_norwegian():
    assert symbols.elevation_text(None, None, "no") == "alle høyder"
    assert symbols.elevation_text(300, None, "no") == "over 300 moh"
    assert symbols.elevation_text(None, 900, "no") == "under 900 moh"
    assert symbols.elevation_text(300, 900, "no") == "300–900 moh"
    assert ">NØ</text>" in symbols.rose_svg(["N"], lang="no")


def test_norwegian_report(tmp_path):
    path = tmp_path / "r.html"
    params = report.scenario_params("80-60, prox0, rel1.2m")
    report.write_html(path, report.collect(ROWS), report.context_lines("lyr", "", 0, lang="no"),
                      scenario_html=report.scenario_section([("A", params)], ["SW", "W"], 300.0, None, lang="no"),
                      buildings_html=report.buildings_table(building_records(), {1: "Kårvik"}, lang="no"),
                      lang="no")
    html = path.read_text(encoding="utf-8")
    for text in ("<h1>Risikorapport</h1>", "Kartlag:", "ingen – alle objekter i kartlaget", "Sammendrag",
                 "Antall bygg analysert", "Skredproblem (som i Varsom)", "SV, V", "over 300 moh",
                 "løsnetykkelse 1,2 m", "Eksponerte bygg etter trykk", "Eksposisjon løsneområde", "80,0",
                 "Bygg etter sikkerhetsklasse", "Antall", "Andel", "«ved»", 'lang="nb"'):
        assert text in html, text
    assert "Release areas" not in html and "Summary" not in html


def test_norwegian_building_rows_and_csv(tmp_path):
    rows = report.table_rows(building_records(), {1: "Kårvik"}, lang="no")
    assert [r['aspect_text'] for r in rows] == ["N", "Ø", "S, SV"]      # highest max PPR first
    assert rows[2]['elevation'] == "130–300 moh" and rows[1]['ppr'] == "80,0"
    path = tmp_path / "r.csv"
    report.write_csv(path, report.collect(ROWS), report.context_lines("lyr", "", 0, lang="no"),
                     buildings=building_records(), lang="no")
    text = path.read_text(encoding="utf-8")
    assert "BYGG,bld_id,Sikkerhetsklasse,Adresse" in text and ",90.0," in text   # numbers stay with a point


def test_norwegian_map_section_and_names():
    b = [{'lon': 18.95, 'lat': 69.65, 'geometry': None, 'props': {'saf_class': 'S2', 'max_ppr': 30.0}}]
    areas = webmap.areas_for(b)
    areas[0]['name'] = "Kårvik"
    html = webmap.map_section(webmap.build_payload(b, areas=areas), lang="no")
    for text in ("Berørte bygg", "Område 1: Kårvik", "1 bygg, maks. 30,0 kPa", "Eksponert bygg", "Områdene i detalj",
                 '"address":"adresse"'):
        assert text in html, text
    assert places.address_label({'address': "Vengsøya 565", 'poststed': "", 'dist': 45}, "no") == "ved Vengsøya 565"
    assert webmap.area_label({'n': 2, 'name': None}, "no") == "Område 2"


# ------------------------------------------------------------------------- PDF --

matplotlib = pytest.importorskip("matplotlib")
pytest.importorskip("PIL")

from alarm_core import pdf_report   # noqa: E402


def pdf_pages(path):
    return len(re.findall(rb"/Type\s*/Page[^s]", path.read_bytes()))


def payload():
    buildings = [{'lon': 18.95 + i * 0.002, 'lat': 69.65, 'geometry': None,
                  'props': {'saf_class': "S2", 'max_ppr': 10.0 + i}} for i in range(3)]
    buildings.append({'lon': 19.5, 'lat': 69.7, 'geometry': None, 'props': {'saf_class': "S3", 'max_ppr': 90.0}})
    areas = webmap.areas_for(buildings)
    areas[0]['name'] = "Kårvik"
    track = {'type': 'Polygon', 'coordinates': [[[18.94, 69.64], [18.96, 69.64], [18.96, 69.66], [18.94, 69.64]]]}
    return webmap.build_payload(buildings, tracks=[{'geometry': track}], pras=[{'geometry': track}],
                                boundaries=[{'geometry': track, 'props': {'name': "X"}}], areas=areas)


def write(path, lang="en", fetch=None, data=None):
    stats = report.collect(ROWS)
    rows = report.table_rows(building_records(), {1: "Kårvik"}, lang=lang)
    return pdf_report.write_pdf(
        path, context=report.context_lines("lyr", "", 0, lang=lang),
        scenarios=report.scenario_lines([("A", report.scenario_params("80-60, prox0, rel1.2m"))], lang),
        problem=(["SW", "W"], 300.0, None), summary=report.summary_lines(stats, lang), payload=data,
        building_rows=rows, hidden_count=1, stats_tables=report.tables(stats, lang), lang=lang, fetch=fetch)


def test_pdf_without_maps(tmp_path):
    path = tmp_path / "r.pdf"
    pages = write(path)
    assert path.read_bytes().startswith(b"%PDF") and pages == pdf_pages(path) == 3   # head, buildings, statistics


def test_pdf_with_maps_offline_and_norwegian(tmp_path):
    asked = []

    def offline(z, x, y):
        asked.append((z, x, y))
        raise OSError("no internet")
    path = tmp_path / "r.pdf"
    pages = write(path, "no", fetch=offline, data=payload())
    assert pages == pdf_pages(path) == 5                       # + area list, small maps
    assert len(asked) == 1                                     # stops after the first failed tile


def test_pdf_draws_the_background_tiles(tmp_path):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (256, 256), (200, 220, 200)).save(buffer, "PNG")
    asked = []

    def tiles(z, x, y):
        asked.append((z, x, y))
        return buffer.getvalue()
    write(tmp_path / "r.pdf", fetch=tiles, data=payload())
    assert asked and all(3 <= z <= 17 for z, _, _ in asked)
    assert len(asked) <= pdf_report.MAX_TILES


def test_mercator_and_fit():
    x, y = pdf_report.mercator(0, 0)
    assert abs(x) < 1e-6 and abs(y) < 1e-6
    x0, y0, x1, y1 = pdf_report._fit(0, 0, 100, 100, 0.5)
    assert abs((y1 - y0) / (x1 - x0) - 0.5) < 1e-9 and x1 - x0 >= 600
