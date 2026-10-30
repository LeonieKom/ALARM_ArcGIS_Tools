import re

from alarm_core import symbols


def red_sectors(svg):
    return svg.count(f'fill="{symbols.RED}"')


def test_aspects_are_split_and_ordered():
    assert symbols.split_aspects("E, SW, S") == ["E", "S", "SW"]
    assert symbols.split_aspects("N/NE") == ["N", "NE"]
    assert symbols.split_aspects("x, n") == ["N"] and symbols.split_aspects(None) == []


def test_rose_has_eight_sectors_with_the_aspects_red():
    svg = symbols.rose_svg(["N", "SW"])
    assert svg.count("<path") == 8 and red_sectors(svg) == 2
    assert red_sectors(symbols.rose_svg(symbols.ASPECTS)) == 8      # no filter: all red
    assert ">NE</text>" in svg and ">NE<" not in symbols.rose_svg(["N"], labels=False)


def test_north_sector_is_at_the_top():
    svg = symbols.rose_svg(["N"], size=100, labels=False)
    red = re.search(r'<path d="M50.00,50.00 L([\d.]+),([\d.]+) A50.0,50.0 0 0 1 ([\d.]+),([\d.]+) Z" '
                    f'fill="{symbols.RED}"', svg)
    x1, y1, x2, y2 = map(float, red.groups())
    assert y1 < 10 and y2 < 10 and x1 < 50 < x2                     # both corners near the top


def test_small_rose_paths_for_the_table():
    assert symbols.rose_paths(["E"]).count("<path") == 8 and red_sectors(symbols.rose_paths(["E"])) == 1


def test_elevation_texts():
    assert symbols.elevation_text() == "all elevations"
    assert symbols.elevation_text(300) == "above 300 m"
    assert symbols.elevation_text(None, 900) == "below 900 m"
    assert symbols.elevation_text(300, 900.0) == "300-900 m"


def test_elevation_triangle():
    full = symbols.elevation_svg()
    assert "<line" not in full and red_sectors(full) == 1
    assert symbols.elevation_svg(300).count("<line") == 1            # dashed limit
    assert symbols.elevation_svg(300, 900).count("<line") == 2       # a band
    assert "<title>below 900 m</title>" in symbols.elevation_svg(None, 900)
