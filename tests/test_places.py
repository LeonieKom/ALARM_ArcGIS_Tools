import json

from alarm_core import places


def fake_fetch(answers, calls=None, fail=False):
    """fetch(url, params) answering from {api url: answer or callable(params)}."""
    def fetch(url, params):
        if calls is not None:
            calls.append((url, dict(params)))
        if fail:
            raise OSError("no internet")
        answer = answers[url]
        return answer(params) if callable(answer) else answer
    return fetch


ADDRESSES = {places.ADDRESS_API: {'adresser': [
    {'adressetekst': "Storgata 70", 'poststed': "TROMSØ", 'meterDistanseTilPunkt': 40.0},
    {'adressetekst': "Storgata 68C", 'poststed': "TROMSØ", 'meterDistanseTilPunkt': 11.3}]}}


def test_nearest_address_is_the_closest_one():
    calls = []
    entry = places.nearest_address(18.95, 69.65, fake_fetch(ADDRESSES, calls))
    assert entry == {'address': "Storgata 68C", 'poststed': "Tromsø", 'dist': 11.3}
    assert calls[0][1]['lat'] == 69.65 and calls[0][1]['lon'] == 18.95 and calls[0][1]['koordsys'] == 4258
    assert places.nearest_address(0, 0, fake_fetch({places.ADDRESS_API: {'adresser': []}}))['address'] is None


def test_address_label_says_near_when_far_away():
    assert places.address_label({'address': "Storgata 68C", 'poststed': "Tromsø", 'dist': 11.3}) == "Storgata 68C, Tromsø"
    assert places.address_label({'address': "Vengsøya 565", 'poststed': "", 'dist': 45}) == "near Vengsøya 565"
    assert places.address_label({'address': None}) == "" and places.address_label(None) == ""


def test_street_of_an_address():
    assert places.street_of({'address': "Oldervikvegen 515A"}) == "Oldervikvegen"
    assert places.street_of({'address': "Vengsøya 565"}) == "Vengsøya"
    assert places.street_of({'address': "Fredrik Langes gate 22"}) == "Fredrik Langes gate"
    assert places.street_of(None) == ""


def test_place_name_prefers_settlements_then_farms():
    names = {places.PLACE_API: {'navn': [
        {'navneobjekttype': "Park", 'meterFraPunkt': 10, 'stedsnavn': [{'skrivemåte': "Folkeparken"}]},
        {'navneobjekttype': "Gard", 'meterFraPunkt': 50, 'stedsnavn': [{'skrivemåte': "Elveneset"}]},
        {'navneobjekttype': "Grend", 'meterFraPunkt': 900, 'stedsnavn': [{'skrivemåte': "Kårvik"}]},
        {'navneobjekttype': "Bygd", 'meterFraPunkt': 400, 'stedsnavn': [{'skrivemåte': "Vengsøy"}]}]}}
    assert places.place_name(18.9, 69.6, fake_fetch(names)) == "Vengsøy"
    names[places.PLACE_API]['navn'] = names[places.PLACE_API]['navn'][:2]
    assert places.place_name(18.9, 69.6, fake_fetch(names)) == "Elveneset"
    names[places.PLACE_API]['navn'] = names[places.PLACE_API]['navn'][:1]
    assert places.place_name(18.9, 69.6, fake_fetch(names)) == ""


def test_lookups_are_cached(tmp_path):
    cache = tmp_path / "a.json"
    calls = []
    found, failed = places.lookup_addresses([("1", 18.95, 69.65), ("2", 18.96, 69.65)], cache,
                                            fake_fetch(ADDRESSES, calls))
    assert failed == 0 and set(found) == {"1", "2"} and len(calls) == 2
    assert set(json.loads(cache.read_text(encoding="utf-8"))) == {"1", "2"}
    calls.clear()
    found, _ = places.lookup_addresses([("1", 18.95, 69.65), ("3", 18.97, 69.65)], cache, fake_fetch(ADDRESSES, calls))
    assert len(calls) == 1 and set(found) == {"1", "3"}                # only the new one asked


def test_without_internet_the_lookups_stop_after_the_first_failure(tmp_path):
    calls = []
    found, failed = places.lookup_addresses([(str(i), 18.9, 69.6) for i in range(50)], tmp_path / "a.json",
                                            fake_fetch(ADDRESSES, calls, fail=True))
    assert found == {} and failed == 50 and len(calls) == 1


def test_areas_are_named_like_the_workshop_tables(tmp_path):
    def answer(params):
        name = {69.60: "Kårvik", 69.61: "Kårvik", 69.62: ""}[round(params['nord'], 2)]
        return {'navn': [{'navneobjekttype': "Grend", 'meterFraPunkt': 5, 'stedsnavn': [{'skrivemåte': name}]}]
                if name else []}
    areas = [{'n': 1, 'lon': 18.9, 'lat': 69.60, 'poststeds': [], 'streets': ["Skjellneslia", "Skjellneslia"]},
             {'n': 2, 'lon': 18.9, 'lat': 69.61, 'poststeds': [], 'streets': ["Kårvikvegen"]},
             {'n': 3, 'lon': 18.9, 'lat': 69.62, 'poststeds': ["Kvaløya", "Kvaløya", "Tromsø"], 'streets': []},
             {'n': 4, 'lon': 19.9, 'lat': 69.62, 'poststeds': [], 'streets': []}]
    names, failed = places.name_areas(areas, tmp_path / "p.json", fake_fetch({places.PLACE_API: answer}))
    assert failed == 0
    assert names == {1: "Kårvik (Skjellneslia)", 2: "Kårvik (Kårvikvegen)",   # same place: street added
                     3: "Kvaløya",                                            # no place: postal place
                     4: "Area 4"}


def test_equal_names_without_streets_get_numerals():
    answer = {places.PLACE_API: {'navn': [{'navneobjekttype': "Grend", 'meterFraPunkt': 5,
                                           'stedsnavn': [{'skrivemåte': "Vengsøya"}]}]}}
    areas = [{'n': n, 'lon': 18.9 + n, 'lat': 69.6} for n in (1, 2, 3)]
    names, _ = places.name_areas(areas, None, fake_fetch(answer))
    assert names == {1: "Vengsøya", 2: "Vengsøya II", 3: "Vengsøya III"}
