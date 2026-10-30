"""Varsom-like avalanche problem symbols as inline SVG: aspect rose and elevation triangle.

The rose has eight sectors (N at the top); the aspects of the release areas are red, the rest
grey. The triangle is the mountain: red where the release areas are (all of it for all
elevations, the top above a limit, the foot below one, a band between two).
"""

import math
from html import escape

ASPECTS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
RED = "#C62828"
EMPTY = "#E3E3E3"


def aspects_in_order(values):
    """The known aspects among values, in compass order and each once."""
    wanted = {str(v).strip().upper() for v in values or []}
    return [a for a in ASPECTS if a in wanted]


def split_aspects(text):
    """'E, SW, S' -> ['E', 'S', 'SW'] (compass order)."""
    if text is None:
        return []
    return aspects_in_order(str(text).replace(";", ",").replace("/", ",").split(","))


def _point(cx, cy, r, degrees):
    a = math.radians(degrees)
    return cx + r * math.sin(a), cy - r * math.cos(a)


def _sectors(aspects, cx, cy, r, gap):
    red = set(aspects)
    paths = []
    for i, name in enumerate(ASPECTS):
        x1, y1 = _point(cx, cy, r, i * 45 - 22.5)
        x2, y2 = _point(cx, cy, r, i * 45 + 22.5)
        paths.append(f'<path d="M{cx:.2f},{cy:.2f} L{x1:.2f},{y1:.2f} A{r},{r} 0 0 1 {x2:.2f},{y2:.2f} Z" '
                     f'fill="{RED if name in red else EMPTY}" stroke="white" stroke-width="{gap}"/>')
    return "".join(paths)


def rose_paths(aspects, size=24):
    """The sectors of a small rose for a size x size box (no labels), for an SVG <symbol>."""
    r = size / 2 - 0.5
    return _sectors(aspects, size / 2, size / 2, r, 0.8)


def rose_svg(aspects, size=120, labels=True, title=None):
    """A rose with the given aspects red; with the direction labels around it."""
    pad = size * 0.16 if labels else 0
    total = size + 2 * pad
    c = total / 2
    r = size / 2
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{total:.0f}" height="{total:.0f}" '
             f'viewBox="0 0 {total:.1f} {total:.1f}" role="img">']
    if title:
        parts.append(f"<title>{escape(title)}</title>")
    parts.append(_sectors(aspects, c, c, r, 1.5))
    if labels:
        for i, name in enumerate(ASPECTS):
            x, y = _point(c, c, r + pad * 0.6, i * 45)
            parts.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size * 0.09:.1f}" fill="#333" '
                         f'text-anchor="middle" dominant-baseline="central" font-family="Arial">{name}</text>')
    parts.append("</svg>")
    return "".join(parts)


def elevation_text(elev_min=None, elev_max=None):
    """'all elevations', 'above 300 m', 'below 900 m' or '300-900 m'."""
    if elev_min is None and elev_max is None:
        return "all elevations"
    if elev_max is None:
        return f"above {elev_min:g} m"
    if elev_min is None:
        return f"below {elev_max:g} m"
    return f"{elev_min:g}-{elev_max:g} m"


def elevation_svg(elev_min=None, elev_max=None, size=120):
    """The mountain triangle, red where the release areas are (symbolic heights, as in Varsom)."""
    w, h = size, size * 0.9
    pad = 4
    top, base = pad, h - pad
    left, right, cx = pad, w - pad, w / 2

    def half_width(y):
        return (cx - left) * (y - top) / (base - top)

    def band(y1, y2):            # y1 above y2 (screen coordinates)
        if y1 <= top:
            return f"M{cx},{top} L{cx + half_width(y2):.1f},{y2:.1f} L{cx - half_width(y2):.1f},{y2:.1f} Z"
        return (f"M{cx - half_width(y1):.1f},{y1:.1f} L{cx + half_width(y1):.1f},{y1:.1f} "
                f"L{cx + half_width(y2):.1f},{y2:.1f} L{cx - half_width(y2):.1f},{y2:.1f} Z")

    outline = f"M{cx},{top} L{right},{base} L{left},{base} Z"
    if elev_min is None and elev_max is None:
        red, lines = outline, []
    elif elev_max is None:
        y = top + (base - top) * 0.5
        red, lines = band(top, y), [y]
    elif elev_min is None:
        y = top + (base - top) * 0.5
        red, lines = band(y, base), [y]
    else:
        y1, y2 = top + (base - top) * 0.35, top + (base - top) * 0.7
        red, lines = band(y1, y2), [y1, y2]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" '
             f'viewBox="0 0 {w:.1f} {h:.1f}" role="img"><title>{escape(elevation_text(elev_min, elev_max))}</title>',
             f'<path d="{outline}" fill="{EMPTY}" stroke="#888" stroke-width="1"/>',
             f'<path d="{red}" fill="{RED}"/>']
    for y in lines:
        hw = half_width(y) + 6
        parts.append(f'<line x1="{cx - hw:.1f}" y1="{y:.1f}" x2="{cx + hw:.1f}" y2="{y:.1f}" '
                     f'stroke="#333" stroke-width="1" stroke-dasharray="4 3"/>')
    parts.append(f'<path d="{outline}" fill="none" stroke="#888" stroke-width="1"/></svg>')
    return "".join(parts)
