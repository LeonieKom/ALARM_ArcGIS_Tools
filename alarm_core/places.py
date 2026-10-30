"""Addresses and place names from Kartverket's open APIs (ws.geonorge.no), without arcpy.

The report lists each building with its nearest address and names each affected area after
a nearby place, as the printed workshop tables do (workshop_figurer/lag_workshop_figurer.py).
Answers are cached in JSON files, so a building or an area is only looked up once.
Without internet access the lookups are skipped and the report is written without them.
"""

import json
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ADDRESS_API = "https://ws.geonorge.no/adresser/v1/punktsok"
PLACE_API = "https://ws.geonorge.no/stedsnavn/v1/punkt"
ADDRESS_RADIUS_M = 100
PLACE_RADIUS_M = 3000
FAR_M = 30                       # an address further away than this is given as 'near ...'
# place name types in order of preference (as in the workshop tables)
PLACE_TYPES = [["Bydel", "Boligfelt", "Tettbebyggelse", "Tettsted", "Grend", "Bygd"],
               ["Gard", "Bruk", "Dal", "Fjellside", "Vik i sjø", "Nes i sjø"]]
WORKERS = 4


def get_json(url, params, timeout=20):
    """GET url?params and decode the JSON answer (raises on any failure)."""
    with urllib.request.urlopen(f"{url}?{urllib.parse.urlencode(params)}", timeout=timeout) as answer:
        return json.loads(answer.read().decode("utf-8"))


def nearest_address(lon, lat, fetch=None):
    """{'address', 'poststed', 'dist'} of the address nearest to the point; address None if none is near."""
    data = (fetch or get_json)(ADDRESS_API, {'lat': lat, 'lon': lon, 'koordsys': 4258, 'utkoordsys': 4258,
                               'radius': ADDRESS_RADIUS_M, 'treffPerSide': 10})
    found = data.get("adresser") or []
    if not found:
        return {'address': None, 'poststed': "", 'dist': None}
    best = min(found, key=lambda a: a.get("meterDistanseTilPunkt", 1e9))
    return {'address': best.get("adressetekst") or None, 'poststed': (best.get("poststed") or "").title(),
            'dist': best.get("meterDistanseTilPunkt")}


def place_name(lon, lat, fetch=None):
    """Name of the nearest settlement-like place around the point ('' if there is none)."""
    data = (fetch or get_json)(PLACE_API, {'nord': lat, 'ost': lon, 'koordsys': 4258,
                             'radius': PLACE_RADIUS_M, 'treffPerSide': 500})
    names = data.get("navn") or []
    for types in PLACE_TYPES:
        candidates = [n for n in names if n.get("navneobjekttype") in types and n.get("stedsnavn")]
        if candidates:
            best = min(candidates, key=lambda n: n.get("meterFraPunkt", 1e9))
            return best["stedsnavn"][0].get("skrivemåte") or ""
    return ""


def address_label(entry):
    """'Storgata 68C, Tromsø' (or 'near ...' when the address is more than FAR_M away), '' if none."""
    if not entry or not entry.get('address'):
        return ""
    text = entry['address'] + (f", {entry['poststed']}" if entry.get('poststed') else "")
    dist = entry.get('dist')
    return f"near {text}" if dist is not None and dist > FAR_M else text


def street_of(entry):
    """Street (or place) part of an address: 'Storgata' of 'Storgata 68C'."""
    if not entry or not entry.get('address'):
        return ""
    words = entry['address'].split()
    while len(words) > 1 and any(ch.isdigit() for ch in words[-1]):
        words.pop()
    return " ".join(words)


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(path, data):
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _lookup(items, cache_file, ask, fetch):
    """Answers for [(key, lon, lat)] from the cache, the rest from ask(lon, lat, fetch).

    Returns ({key: answer}, number of failed lookups). The first failed lookup of the
    uncached items stops the lookups (no internet: do not wait for every request to time out).
    """
    cache = _load(cache_file) if cache_file else {}
    todo = [(k, lon, lat) for k, lon, lat in items if k not in cache]
    failed = 0
    if todo:
        try:
            first = todo[0]
            cache[first[0]] = ask(first[1], first[2], fetch)
        except Exception:
            failed = len(todo)
            todo = []
        rest = todo[1:]

        def one(item):
            try:
                return item[0], ask(item[1], item[2], fetch)
            except Exception:
                return item[0], None

        if rest:
            with ThreadPoolExecutor(WORKERS) as pool:
                for key, answer in pool.map(one, rest):
                    if answer is None:
                        failed += 1
                    else:
                        cache[key] = answer
        if cache_file:
            _save(cache_file, cache)
    return {k: cache[k] for k, _, _ in items if k in cache}, failed


def lookup_addresses(items, cache_file=None, fetch=None):
    """Nearest addresses for [(key, lon, lat)] -> ({key: entry}, failed); key e.g. the bld_id."""
    return _lookup(items, cache_file, nearest_address, fetch)


def place_key(lon, lat):
    """Cache key of a place name lookup (about 100 m grid)."""
    return f"{lon:.3f}_{lat:.3f}"


def name_areas(areas, cache_file=None, fetch=None):
    """Names of affected areas, as in the workshop tables.

    areas: [{'n', 'lon', 'lat', 'poststeds': [...], 'streets': [...]}] (poststeds and streets
    of the area's buildings). An area gets the nearest place name, else its most common
    postal place, else 'Area n'. Equal names are told apart by the most common street, then
    by II, III, ...
    Returns ({n: name}, failed lookups).
    """
    found, failed = _lookup([(place_key(a['lon'], a['lat']), a['lon'], a['lat']) for a in areas],
                            cache_file, place_name, fetch)
    names = {}
    for a in areas:
        name = found.get(place_key(a['lon'], a['lat'])) or ""
        if not name:
            posts = Counter(p for p in a.get('poststeds', []) if p)
            name = posts.most_common(1)[0][0] if posts else f"Area {a['n']}"
        names[a['n']] = name
    count = Counter(names.values())
    for a in areas:
        if count[names[a['n']]] > 1:
            streets = Counter(s for s in a.get('streets', []) if s)
            if streets:
                names[a['n']] = f"{names[a['n']]} ({streets.most_common(1)[0][0]})"
    seen = Counter()
    for n in sorted(names):
        seen[names[n]] += 1
        if seen[names[n]] > 1:
            k = seen[names[n]]
            names[n] = f"{names[n]} {'I' * k if k < 4 else k}"
    return names, failed
