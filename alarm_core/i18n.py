"""Report texts in English and Norwegian (bokmål).

tr(lang) returns a function that gives the text of a key, filled with the keyword arguments:
    _ = tr("no"); _("buildings_n", n=3) -> "3 bygg"
Aspects are stored in the data as N, NE, ...; aspect() gives the label of the language
(Norwegian as in Varsom: N, NØ, Ø, SØ, S, SV, V, NV).
"""

LANGUAGES = {"English": "en", "Norsk": "no"}
DEFAULT = "en"

_ASPECTS_NO = {"N": "N", "NE": "NØ", "E": "Ø", "SE": "SØ", "S": "S", "SW": "SV", "W": "V", "NW": "NV"}

TEXT = {
    # report frame
    'report_title': ("Risk Assessment Report", "Risikorapport"),
    'generated': ("Generated", "Laget"),
    'layer': ("Layer", "Kartlag"),
    'layers': ("Layers", "Kartlag"),
    'layers_combined': ("{n} risk assessment layers, combined", "{n} risikokartlag, slått sammen"),
    'layer_n': ("Layer {n}", "Kartlag {n}"),
    'layer_n_filter': ("Layer {n} filter", "Filter kartlag {n}"),
    'layer_n_selection': ("Layer {n} selection", "Utvalg kartlag {n}"),
    'data_source': ("Data source", "Datakilde"),
    'filter': ("Filter", "Filter"),
    'filter_sql': ("Filter (SQL)", "Filter (SQL)"),
    'no_filter': ("none - all features of the layer", "ingen – alle objekter i kartlaget"),
    'selection': ("Selection", "Utvalg"),
    'selected_only': ("{n} selected features - only these are included", "{n} valgte objekter – bare disse er med"),
    'duplicates': ("Duplicates", "Duplikater"),
    'duplicates_text': ("{n} buildings were in more than one layer; each is counted once (with its highest max PPR)",
                        "{n} bygg lå i mer enn ett kartlag; hvert telles én gang (med høyeste maks. trykk)"),
    # summary
    'summary': ("Summary", "Sammendrag"),
    'total_buildings': ("Total Buildings Analyzed", "Antall bygg analysert"),
    'max_ppr_range': ("Max PPR Range", "Spenn i maks. trykk"),
    'mean_ppr_average': ("Average of Mean PPR", "Gjennomsnitt av middeltrykk"),
    'elevation_range': ("Elevation Range", "Høydespenn"),
    'without_elevation': ("{n} buildings without elevation not included", "{n} bygg uten høyde er ikke med"),
    # statistics tables
    'by_class': ("Buildings by Safety Class", "Bygg etter sikkerhetsklasse"),
    'safety_class': ("Safety Class", "Sikkerhetsklasse"),
    'by_ppr': ("Buildings by PPR Category", "Bygg etter trykklasse"),
    'ppr_range': ("PPR Range", "Trykk"),
    'by_elevation': ("Buildings by Elevation Range", "Bygg etter høyde"),
    'elevation': ("Elevation Range", "Høyde"),
    'by_aspect': ("Buildings by Aspect", "Bygg etter eksposisjon"),
    'aspect': ("Aspect", "Eksposisjon"),
    'count': ("Count", "Antall"),
    'percentage': ("Percentage", "Andel"),
    'unknown': ("Unknown", "Ukjent"),
    # scenario and avalanche problem
    'scenario': ("Scenario", "Scenario"),
    'scenario_label': ("Scenario {label}", "Scenario {label}"),
    'scenario_unknown': ("Scenario not known.", "Ukjent scenario."),
    'params': ("PRA thresholds {t_high} / {t_low} %, proximity {proximity} m, release thickness {release} m",
               "Terskler for løsneområder {t_high} / {t_low} %, nærhet {proximity} m, løsnetykkelse {release} m"),
    'params_unknown': ("parameters not known", "parametere ukjent"),
    'single_run': ("single run", "enkeltkjøring"),
    'release_areas_shown': ("Release areas shown", "Løsneområder som vises"),
    'from_filter': ("(from the layer filter)", "(fra filteret på kartlaget)"),
    'all_aspects': ("all aspects", "alle eksposisjoner"),
    'no_aspects': ("none", "ingen"),
    'avalanche_problem': ("Avalanche problem (as in Varsom)", "Skredproblem (som i Varsom)"),
    'all_elevations': ("all elevations", "alle høyder"),
    'above': ("above {v} m", "over {v} moh"),
    'below': ("below {v} m", "under {v} moh"),
    'between': ("{lo}-{hi} m", "{lo}–{hi} moh"),
    'elev_one': ("{v} m", "{v} moh"),
    # building table
    'exposed_buildings': ("Exposed buildings by pressure", "Eksponerte bygg etter trykk"),
    'buildings_listed': ("{n} buildings{hidden}, highest max PPR first.",
                         "{n} bygg{hidden}, sortert etter høyeste maks. trykk."),
    'hidden_note': (" (the {n} buildings of class {classes} are hidden)", " (de {n} byggene i klasse {classes} er skjult)"),
    'table_explained': ("Aspect and elevation are those of the release areas reaching the building; the rose shows "
                        "the aspects (N at the top), as in Varsom.",
                        "Eksposisjon og høyde gjelder løsneområdene som når bygget; rosen viser eksposisjonen "
                        "(N øverst), som i Varsom."),
    'show_hidden': ("Also show the {n} buildings of class {classes}", "Vis også de {n} byggene i klasse {classes}"),
    'rank': ("Rank", "Rang"),
    'class': ("Class", "Klasse"),
    'address': ("Address", "Adresse"),
    'area': ("Area", "Område"),
    'area_name': ("Area name", "Områdenavn"),
    'max_ppr_kpa': ("Max PPR [kPa]", "Trykk (kPa)"),
    'aspect_release': ("Aspect of release area", "Eksposisjon løsneområde"),
    'elevation_release': ("Elevation of release area", "Høyde løsneområde"),
    'address_note': ('Address: nearest address (Kartverket), "near" = more than 30 m away.',
                     "Adresse: nærmeste adresse (Kartverket), «ved» = over 30 m unna."),
    'near': ("near {address}", "ved {address}"),
    'buildings_section': ("BUILDINGS", "BYGG"),
    # map
    'affected_buildings': ("Affected buildings", "Berørte bygg"),
    'no_buildings_map': ("No buildings to show on the map.", "Ingen bygg å vise i kartet."),
    'map_needs_internet': ("The map needs internet access (Leaflet and background map).",
                           "Kartet trenger internett (Leaflet og bakgrunnskart)."),
    'areas_priority': ("Affected areas (priority: highest max PPR first)",
                       "Berørte områder (prioritet: høyeste maks. trykk først)"),
    'areas_explained': ("Buildings closer than 500 m to each other form one area. Click a building for its values.",
                        "Bygg nærmere enn 500 m fra hverandre danner ett område. Klikk på et bygg for verdiene."),
    'name': ("Name", "Navn"),
    'highest_ppr': ("Highest max PPR [kPa]", "Høyeste maks. trykk (kPa)"),
    'buildings': ("Buildings", "Bygg"),
    'safety_classes': ("Safety classes", "Sikkerhetsklasser"),
    'zoom': ("Zoom", "Zoom"),
    'areas_detail': ("Areas in detail", "Områdene i detalj"),
    'more_areas': ("{n} further areas are listed above (Zoom).", "{n} flere områder står i listen over (Zoom)."),
    'area_n': ("Area {n}", "Område {n}"),
    'area_n_name': ("Area {n}: {name}", "Område {n}: {name}"),
    'buildings_n': ("{n} buildings", "{n} bygg"),
    'max_kpa': ("max {v} kPa", "maks. {v} kPa"),
    'legend_building': ("Exposed building (click for its values)", "Eksponert bygg (klikk for verdier)"),
    'legend_building_print': ("Exposed building", "Eksponert bygg"),
    'tracks': ("Avalanche tracks", "Skredbaner"),
    'pras': ("PRAs", "Løsneområder"),
    'municipality': ("Municipality", "Kommune"),
    'popup_address': ("address", "adresse"),
    'popup_area': ("area", "område"),
    'background_source': ("Background map: © Kartverket", "Bakgrunnskart: © Kartverket"),
    'page': ("Page {n}", "Side {n}"),
}


def tr(lang=DEFAULT):
    """Text function for a language ('en' or 'no'; anything else is English)."""
    index = 1 if lang == "no" else 0

    def text(key, **values):
        template = TEXT[key][index]
        return template.format(**values) if values else template
    return text


def aspect(code, lang=DEFAULT):
    """Label of an aspect code (N, NE, ...) in the language."""
    return _ASPECTS_NO.get(code, code) if lang == "no" else code


def number(value, digits, lang=DEFAULT):
    """A number with a decimal comma in Norwegian."""
    text = f"{value:.{digits}f}"
    return text.replace(".", ",") if lang == "no" else text
