"""The report as PDF (A4), drawn with matplotlib (no arcpy, no browser).

Same content as the HTML report: scenario and avalanche problem, key figures, an overview
map and a small map per affected area (Kartverket background tiles, if they can be fetched),
the priority list of the areas, the table of exposed buildings and the statistics tables.
matplotlib is used without pyplot, so ArcGIS Pro's own plotting is not touched.
"""

import io
import math
import textwrap
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import symbols
from .i18n import aspect as _aspect, tr

PAGE = (8.27, 11.69)             # A4 portrait, inches
MARGIN = 0.6
TILE_URL = "https://cache.kartverket.no/v1/wmts/1.0.0/topo/default/webmercator/{z}/{y}/{x}.png"
MAX_TILES_PER_MAP = 36
MAX_TILES = 600                  # per document
EARTH = 6378137.0
SMALL_MAPS = 12
ROW_H = 0.235                    # building table row height, inches
RED, GREY = symbols.RED, symbols.EMPTY
BUILDING_RED = "#ff0000"
DPI = 200                        # resolution of the rasterized map content


def fetch_tile(z, x, y, timeout=15):
    """PNG bytes of a Kartverket background tile (raises on failure)."""
    request = urllib.request.Request(TILE_URL.format(z=z, x=x, y=y), headers={"User-Agent": "ALARM-ArcGIS-Tools"})
    with urllib.request.urlopen(request, timeout=timeout) as answer:
        return answer.read()


def mercator(lon, lat):
    lat = max(min(lat, 85.0), -85.0)
    return EARTH * math.radians(lon), EARTH * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


# ------------------------------------------------------------------ background tiles --

class _Tiles:
    """Tiles fetched for one document; stops asking after the first failure (no internet)."""

    def __init__(self, fetch):
        self.fetch = fetch
        self.cache = {}
        self.offline = fetch is None
        self.count = 0

    def image(self, x0, y0, x1, y1, width_px):
        """(RGB array, extent) of the background for a mercator box, or None."""
        if self.offline:
            return None
        import numpy as np
        from PIL import Image
        world = 2 * math.pi * EARTH
        z = int(max(3, min(17, math.floor(math.log2(width_px * world / (256 * max(x1 - x0, 1.0)))))))
        while True:
            n = 2 ** z
            tx0, tx1 = int((x0 + world / 2) / world * n), int((x1 + world / 2) / world * n)
            ty0, ty1 = int((world / 2 - y1) / world * n), int((world / 2 - y0) / world * n)
            if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) <= MAX_TILES_PER_MAP or z <= 3:
                break
            z -= 1
        wanted = [(z, tx, ty) for ty in range(ty0, ty1 + 1) for tx in range(tx0, tx1 + 1)
                  if 0 <= tx < n and 0 <= ty < n]
        if self.count + len(wanted) > MAX_TILES:
            return None
        todo = [k for k in wanted if k not in self.cache]
        if todo:
            try:
                self.cache[todo[0]] = self.fetch(*todo[0])
            except Exception:
                self.offline = True
                return None

            def one(key):
                try:
                    return key, self.fetch(*key)
                except Exception:
                    return key, None
            with ThreadPoolExecutor(6) as pool:
                for key, data in pool.map(one, todo[1:]):
                    self.cache[key] = data
        self.count += len(wanted)
        mosaic = np.full(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256, 3), 235, dtype=np.uint8)
        for (_, tx, ty) in wanted:
            data = self.cache.get((z, tx, ty))
            if not data:
                continue
            try:
                tile = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))
            except Exception:
                continue
            r, c = (ty - ty0) * 256, (tx - tx0) * 256
            mosaic[r:r + 256, c:c + 256] = tile[:256, :256]
        # crop to the map and scale to the resolution needed (keeps the PDF small)
        size = world / n
        left, top = tx0 * size - world / 2, world / 2 - ty0 * size
        px = size / 256                                           # metres per pixel
        c0, c1 = max(0, int((x0 - left) / px)), min(mosaic.shape[1], int(math.ceil((x1 - left) / px)))
        r0, r1 = max(0, int((top - y1) / px)), min(mosaic.shape[0], int(math.ceil((top - y0) / px)))
        crop = mosaic[r0:r1, c0:c1]
        extent = (left + c0 * px, left + c1 * px, top - r1 * px, top - r0 * px)
        if crop.shape[1] > width_px * 1.2:
            scale = width_px * 1.2 / crop.shape[1]
            crop = np.asarray(Image.fromarray(crop).resize((max(1, int(crop.shape[1] * scale)),
                                                            max(1, int(crop.shape[0] * scale))), Image.LANCZOS))
        return crop, extent


# ------------------------------------------------------------------------- drawing --

def _rings(geometry):
    """Outer rings of a GeoJSON (Multi)Polygon / LineString(s) as lists of mercator points."""
    if not geometry:
        return []
    kind, coords = geometry.get('type'), geometry.get('coordinates') or []
    if kind == "Polygon":
        parts = [coords[0]] if coords else []
    elif kind == "MultiPolygon":
        parts = [p[0] for p in coords if p]
    elif kind == "LineString":
        parts = [coords]
    elif kind == "MultiLineString":
        parts = coords
    else:
        return []
    return [[mercator(x, y) for x, y, *_ in part] for part in parts if len(part) > 1]


def _context_rings(payload, key):
    collection = (payload.get('context') or {}).get(key)
    if not collection:
        return []
    return [ring for f in collection['features'] for ring in _rings(f.get('geometry'))]


def _touches(ring, box):
    """True if the ring's bounding box overlaps the box (x0, y0, x1, y1)."""
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    return min(xs) <= box[2] and max(xs) >= box[0] and min(ys) <= box[3] and max(ys) >= box[1]


def _fit(x0, y0, x1, y1, aspect, pad=0.08, minimum=600.0):
    """A box around (x0..x1, y0..y1) with the axes' aspect (height / width), padded."""
    w, h = max(x1 - x0, minimum), max(y1 - y0, minimum)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, h = w * (1 + 2 * pad), h * (1 + 2 * pad)
    if h / w < aspect:
        h = w * aspect
    else:
        w = h / aspect
    return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2


def _draw_map(ax, payload, box, tiles, width_px, point_size=10, numbers=None, lang="en"):
    from matplotlib.collections import LineCollection, PolyCollection
    x0, y0, x1, y1 = box
    background = tiles.image(x0, y0, x1, y1, width_px)
    if background is not None:
        image, extent = background
        ax.imshow(image, extent=extent, interpolation="bilinear", zorder=0)
    else:
        ax.set_facecolor("#f4f4f4")
    # only what lies in the map (the PDF would embed every feature in every map), drawn as an
    # image: thousands of tracks as vectors make the file large and slow to open
    tracks = [r for r in _context_rings(payload, 'tracks') if _touches(r, box)]
    pras = [r for r in _context_rings(payload, 'pras') if _touches(r, box)]
    if tracks:
        ax.add_collection(PolyCollection(tracks, facecolors="#c6dbef", edgecolors="#9ecae1", linewidths=0.3,
                                         alpha=0.6, zorder=2, rasterized=True))
    if pras:
        ax.add_collection(PolyCollection(pras, facecolors="none", edgecolors="black", linewidths=0.4,
                                         alpha=0.6, zorder=3, rasterized=True))
    boundaries = _context_rings(payload, 'boundaries')
    if boundaries:
        ax.add_collection(LineCollection(boundaries, colors="#8b0000", linewidths=1.4, linestyles="--", zorder=4))
    points = [mercator(*f['geometry']['coordinates']) for f in payload['features']
              if not f['properties'].get('outline')]
    if points:
        ax.scatter([p[0] for p in points], [p[1] for p in points], s=point_size, c=BUILDING_RED,
                   edgecolors="#333", linewidths=0.4, zorder=5)
    for n, (x, y) in (numbers or {}).items():
        if x0 <= x <= x1 and y0 <= y <= y1:
            ax.annotate(str(n), (x, y), xytext=(4, 4), textcoords="offset points", fontsize=7, weight="bold",
                        zorder=6, bbox={"boxstyle": "round,pad=0.15", "fc": "white", "ec": "#333", "lw": 0.4})
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_xticks([])
    ax.set_yticks([])
    for side in ax.spines.values():
        side.set_linewidth(0.6)
        side.set_color("#999")


def _rose(ax, cx, cy, r, aspects, labels=False, lang="en", fontsize=7):
    """Aspect rose in inch coordinates (N at the top)."""
    from matplotlib.patches import Wedge
    for i, name in enumerate(symbols.ASPECTS):
        centre = 90 - i * 45            # matplotlib: degrees counter-clockwise from east
        ax.add_patch(Wedge((cx, cy), r, centre - 22.5, centre + 22.5, facecolor=RED if name in aspects else GREY,
                           edgecolor="white", linewidth=0.6 if r > 0.2 else 0.3))
        if labels:
            a = math.radians(centre)
            ax.text(cx + 1.25 * r * math.cos(a), cy + 1.25 * r * math.sin(a), _aspect(name, lang),
                    ha="center", va="center", fontsize=fontsize, color="#333")


def _triangle(ax, x, y, w, h, elev_min, elev_max):
    """Elevation triangle in inch coordinates, red where the release areas are (as in Varsom)."""
    from matplotlib.patches import Polygon
    apex, left, right = (x + w / 2, y + h), (x, y), (x + w, y)
    ax.add_patch(Polygon([apex, right, left], closed=True, facecolor=GREY, edgecolor="#888", linewidth=0.8))

    def half(yy):
        return w / 2 * (1 - (yy - y) / h)
    if elev_min is None and elev_max is None:
        ax.add_patch(Polygon([apex, right, left], closed=True, facecolor=RED, edgecolor="#888", linewidth=0.8))
        return
    if elev_max is None:
        lo, hi = y + h * 0.5, y + h
    elif elev_min is None:
        lo, hi = y, y + h * 0.5
    else:
        lo, hi = y + h * 0.3, y + h * 0.65
    cx = x + w / 2
    pts = [(cx - half(lo), lo), (cx + half(lo), lo), (cx + half(hi), hi), (cx - half(hi), hi)]
    ax.add_patch(Polygon(pts, closed=True, facecolor=RED, edgecolor="none"))
    for yy in {lo, hi} - {y, y + h}:
        ax.plot([cx - half(yy) - 0.08, cx + half(yy) + 0.08], [yy, yy], color="#333", lw=0.7, ls="--")


# ------------------------------------------------------------------------ document --

class _Document:
    def __init__(self, pdf, lang):
        self.pdf, self.lang, self.page_no = pdf, lang, 0
        self._ = tr(lang)

    def page(self):
        """A new page: (figure, axes in inch coordinates, origin bottom left)."""
        from matplotlib.figure import Figure
        fig = Figure(figsize=PAGE)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, PAGE[0])
        ax.set_ylim(0, PAGE[1])
        ax.axis("off")
        self.page_no += 1
        ax.text(PAGE[0] - MARGIN, 0.35, self._("page", n=self.page_no), ha="right", fontsize=7, color="#777")
        ax.text(MARGIN, 0.35, self._("background_source"), fontsize=7, color="#777")
        return fig, ax

    def save(self, fig):
        self.pdf.savefig(fig, dpi=DPI)

    def map_axes(self, fig, left, bottom, width, height):
        return fig.add_axes([left / PAGE[0], bottom / PAGE[1], width / PAGE[0], height / PAGE[1]])


def _text_lines(ax, x, y, lines, size=8, width=110, step=0.17, max_lines=3):
    """'Key: value' lines, wrapped (at most max_lines each); returns the y below them."""
    for key, value in lines:
        wrapped = textwrap.wrap(f"{key}: {value}", width) or [""]
        if len(wrapped) > max_lines:
            wrapped = wrapped[:max_lines]
            wrapped[-1] = wrapped[-1][:width - 3] + "..."
        for line in wrapped:
            ax.text(x, y, line, fontsize=size, va="top")
            y -= step
    return y


def _clip(text, n):
    text = str(text)
    return text if len(text) <= n else text[:n - 1] + "…"


def write_pdf(path, *, context, generated=None, scenarios=(), problem=None, summary=(), payload=None,
              building_rows=(), hidden_count=0, hidden_classes=("S1",), stats_tables=(), lang="en",
              fetch=fetch_tile):
    """Write the report as PDF.

    Args:
        context: [(label, text)] (layer, filter, ...); summary: [(label, text)] key figures
        scenarios: [(label, text)] scenario lines; problem: (aspects, elev_min, elev_max)
        payload: webmap.build_payload(...) or None (no maps)
        building_rows: report.table_rows(...) of the buildings to list (e.g. without S1)
        stats_tables: report.tables(stats, lang)
        fetch: fetch_tile(z, x, y) -> PNG bytes; None draws the maps without background
    """
    from matplotlib.backends.backend_pdf import PdfPages
    _ = tr(lang)
    generated = generated or datetime.now()
    tiles = _Tiles(fetch)
    aspects, elev_min, elev_max = problem or (list(symbols.ASPECTS), None, None)
    with PdfPages(path) as pdf:
        doc = _Document(pdf, lang)

        # ---- page 1: head, scenario, avalanche problem, key figures, overview map
        fig, ax = doc.page()
        top = PAGE[1] - MARGIN
        ax.text(MARGIN, top, _("report_title"), fontsize=18, weight="bold", va="top")
        y = _text_lines(ax, MARGIN, top - 0.45, list(context) + [(_("generated"),
                                                                  generated.strftime("%Y-%m-%d %H:%M"))],
                        size=7.5, width=120)
        block = y - 0.1
        # left: scenario and key figures; right: avalanche problem symbols
        ax.text(MARGIN, block, _("scenario"), fontsize=11, weight="bold", va="top")
        y = _text_lines(ax, MARGIN, block - 0.25, list(scenarios) or [(_("scenario"), _("scenario_unknown"))],
                        size=8, width=72)
        all_aspects = len(aspects) == len(symbols.ASPECTS)
        aspect_text = _("all_aspects") if all_aspects else ", ".join(_aspect(a, lang) for a in aspects)
        elevation = symbols.elevation_text(elev_min, elev_max, lang)
        y = _text_lines(ax, MARGIN, y - 0.05, [(_("release_areas_shown"), f"{aspect_text}, {elevation}")],
                        size=8, width=72)
        y -= 0.1
        ax.text(MARGIN, y, _("summary"), fontsize=11, weight="bold", va="top")
        y = _text_lines(ax, MARGIN, y - 0.25, list(summary), size=8, width=72)
        sx = PAGE[0] - MARGIN - 2.6
        ax.text(sx, block, _("avalanche_problem"), fontsize=9, weight="bold", va="top")
        _rose(ax, sx + 0.6, block - 0.95, 0.45, aspects, labels=True, lang=lang)
        _triangle(ax, sx + 1.45, block - 1.45, 1.05, 0.95, elev_min, elev_max)
        ax.text(sx + 0.6, block - 1.62, aspect_text, ha="center", fontsize=8, weight="bold", va="top")
        ax.text(sx + 1.97, block - 1.62, elevation, ha="center", fontsize=8, weight="bold", va="top")
        y = min(y, block - 1.9) - 0.1
        if payload and payload.get('features'):
            ax.text(MARGIN, y, _("affected_buildings"), fontsize=11, weight="bold", va="top")
            map_top = y - 0.3
            height = map_top - 0.7
            width = PAGE[0] - 2 * MARGIN
            mx = doc.map_axes(fig, MARGIN, 0.7, width, height)
            points = [mercator(*f['geometry']['coordinates']) for f in payload['features']
                      if not f['properties'].get('outline')]
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            box = _fit(min(xs), min(ys), max(xs), max(ys), height / width, pad=0.06, minimum=1500)
            numbers = {a['n']: mercator((a['bounds'][0] + a['bounds'][2]) / 2, (a['bounds'][1] + a['bounds'][3]) / 2)
                       for a in payload['areas'][:40]}
            _draw_map(mx, payload, box, tiles, 1400, point_size=9, numbers=numbers, lang=lang)
        doc.save(fig)

        # ---- areas: priority list and small maps
        areas = payload['areas'] if payload else []
        if areas:
            from .webmap import area_caption, area_label
            per_page = 40
            for start in range(0, len(areas), per_page):
                fig, ax = doc.page()
                y = PAGE[1] - MARGIN
                ax.text(MARGIN, y, _("areas_priority"), fontsize=11, weight="bold", va="top")
                y -= 0.35
                cols = [(_("area"), 0.0), (_("name"), 0.55), (_("highest_ppr"), 3.3), (_("buildings"), 5.0),
                        (_("safety_classes"), 5.8)]
                y -= _table_header(ax, MARGIN, y, cols)
                for i, a in enumerate(areas[start:start + per_page]):
                    if i % 2:
                        _shade(ax, y)
                    ppr = "-" if a['max_ppr'] is None else f"{a['max_ppr']:.1f}"
                    ppr = ppr.replace(".", ",") if lang == "no" else ppr
                    values = [str(a['n']), _clip(a.get('name') or "", 40), ppr, str(a['buildings']),
                              ", ".join(f"{k}: {v}" for k, v in a['classes'].items())]
                    for (_label, dx), value in zip(cols, values):
                        ax.text(MARGIN + dx + 0.05, y - ROW_H / 2, value, fontsize=7.5, va="center")
                    y -= ROW_H
                doc.save(fig)
            shown = areas[:SMALL_MAPS]
            for start in range(0, len(shown), 6):
                fig, ax = doc.page()
                ax.text(MARGIN, PAGE[1] - MARGIN, _("areas_detail"), fontsize=11, weight="bold", va="top")
                w, h = (PAGE[0] - 2 * MARGIN - 0.3) / 2, 2.85
                for k, a in enumerate(shown[start:start + 6]):
                    col, row = k % 2, k // 2
                    left = MARGIN + col * (w + 0.3)
                    bottom = PAGE[1] - MARGIN - 0.45 - (row + 1) * (h + 0.55) + 0.55
                    mx = doc.map_axes(fig, left, bottom, w, h)
                    b = a['bounds']
                    (bx0, by0), (bx1, by1) = mercator(b[0], b[1]), mercator(b[2], b[3])
                    box = _fit(bx0, by0, bx1, by1, h / w, pad=0.35, minimum=700)
                    _draw_map(mx, payload, box, tiles, 700, point_size=16, lang=lang)
                    ax.text(left, bottom - 0.08, area_label(a, lang), fontsize=8.5, weight="bold", va="top")
                    ax.text(left, bottom - 0.26, area_caption(a, lang), fontsize=7.5, va="top")
                doc.save(fig)

        # ---- exposed buildings
        rows = list(building_rows)
        per_page = int((PAGE[1] - 2 * MARGIN - 1.0) / ROW_H)
        cols = [(_("rank"), 0.0), (_("class"), 0.42), (_("address"), 0.9), (_("area"), 3.15),
                (_("max_ppr_kpa"), 4.85), (_("aspect_release"), 5.6), (_("elevation_release"), 6.45)]
        for start in range(0, max(len(rows), 1), per_page):
            fig, ax = doc.page()
            y = PAGE[1] - MARGIN
            ax.text(MARGIN, y, _("exposed_buildings"), fontsize=11, weight="bold", va="top")
            note = _("buildings_listed", n=len(rows), hidden=_("hidden_note", n=hidden_count,
                                                                   classes=", ".join(hidden_classes))
                     if hidden_count else "")
            ax.text(MARGIN, y - 0.3, note, fontsize=7.5, va="top", color="#444")
            y -= 0.6
            y -= _table_header(ax, MARGIN, y, cols, size=6.8)
            for i, r in enumerate(rows[start:start + per_page]):
                if i % 2:
                    _shade(ax, y)
                mid = y - ROW_H / 2
                values = [str(start + i + 1), r['saf_class'], _clip(r['address'], 34), _clip(r['area'], 26),
                          r['ppr'], None, r['elevation']]
                for (_label, dx), value in zip(cols, values):
                    if value is not None:
                        ax.text(MARGIN + dx + 0.05, mid, value, fontsize=7, va="center",
                                ha="left")
                _rose(ax, MARGIN + cols[5][1] + 0.14, mid, 0.085, r['aspects'])
                ax.text(MARGIN + cols[5][1] + 0.28, mid, _clip(r['aspect_text'], 12), fontsize=7, va="center")
                y -= ROW_H
            ax.text(MARGIN, y - 0.15, _("address_note"), fontsize=7, color="#666", va="top")
            doc.save(fig)

        # ---- statistics
        fig, ax = doc.page()
        y = PAGE[1] - MARGIN
        for title, header, table in stats_tables:
            total = sum(count for _l, count in table) or 1
            ax.text(MARGIN, y, title, fontsize=10, weight="bold", va="top")
            y -= 0.3
            cols = [(header, 0.0), (_("count"), 2.2), (_("percentage"), 3.2)]
            y -= _table_header(ax, MARGIN, y, cols, width=4.2)
            for i, (label, count) in enumerate(table):
                if i % 2:
                    _shade(ax, y, width=4.2)
                pct = f"{count / total * 100:.1f}%"
                for (_l, dx), value in zip(cols, [str(label), str(count), pct.replace(".", ",") if lang == "no"
                                                  else pct]):
                    ax.text(MARGIN + dx + 0.05, y - ROW_H / 2, value, fontsize=7.5, va="center")
                y -= ROW_H
            y -= 0.25
            if y < 2.2:
                doc.save(fig)
                fig, ax = doc.page()
                y = PAGE[1] - MARGIN
        doc.save(fig)
    return doc.page_no


def _table_header(ax, x, y, cols, size=7.5, width=None):
    """Dark header row; labels wider than their column wrap onto a second line.

    Returns the height of the header (one or two rows).
    """
    from matplotlib.patches import Rectangle
    width = width or PAGE[0] - 2 * MARGIN
    char_w = size * 0.0085                                          # inches per character, bold
    labels = []
    for i, (label, dx) in enumerate(cols):
        room = (cols[i + 1][1] if i + 1 < len(cols) else width) - dx - 0.08
        labels.append("\n".join(textwrap.wrap(label, max(4, int(room / char_w)))[:2]))
    height = ROW_H * (1.7 if any("\n" in label for label in labels) else 1)
    ax.add_patch(Rectangle((x, y - height), width, height, facecolor="#263238", edgecolor="none"))
    for label, (_label, dx) in zip(labels, cols):
        ax.text(x + dx + 0.05, y - height / 2, label, fontsize=size, color="white", weight="bold", va="center",
                linespacing=1.1)
    return height


def _shade(ax, y, width=None):
    from matplotlib.patches import Rectangle
    width = width or PAGE[0] - 2 * MARGIN
    ax.add_patch(Rectangle((MARGIN, y - ROW_H), width, ROW_H, facecolor="#f2f2f2", edgecolor="none"))
