"""Filter criteria for ALARM layers: SQL for the map layers and the same logic in Python.

'Filter Layers' builds SQL definition queries from the criteria, 'Compare Scenarios' counts
with the Python predicates. Both use the same aspect boundaries, and the tests check that
they agree.
"""

# Aspect classes as degree ranges [from, to)
CARDINAL_RANGES = {
    'N': [(337.5, 360), (0, 22.5)],
    'NE': [(22.5, 67.5)],
    'E': [(67.5, 112.5)],
    'SE': [(112.5, 157.5)],
    'S': [(157.5, 202.5)],
    'SW': [(202.5, 247.5)],
    'W': [(247.5, 292.5)],
    'NW': [(292.5, 337.5)],
}

ASPECT_NONE = "None"
ASPECT_CARDINAL = "Cardinal Directions"
ASPECT_DEGREES = "Degree Range"


def make_criteria(elev_min=None, elev_max=None, aspect_type=ASPECT_NONE, cardinal=None,
                  aspect_min=None, aspect_max=None, saf_classes=None, min_max_ppr=None):
    """Normalised filter criteria (one dict shared by SQL builders and Python predicates)."""
    return {
        'elev_min': elev_min,
        'elev_max': elev_max,
        'aspect_type': aspect_type or ASPECT_NONE,
        'cardinal': list(cardinal or []),
        'aspect_min': aspect_min,
        'aspect_max': aspect_max,
        'saf_classes': list(saf_classes or []),
        'min_max_ppr': min_max_ppr,
    }


def validate(criteria, require_any=False):
    """Problems with the criteria, for the tool dialog: [(key, 'error'|'warning', message)].

    key is a criteria key (the tool shows the message at that parameter) or 'any' for
    "no criterion set" (only reported with require_any, e.g. in Filter Layers).
    """
    problems = []
    lo, hi = criteria['elev_min'], criteria['elev_max']
    if lo is not None and hi is not None and lo > hi:
        problems.append(('elev_max', 'error', f"Maximum elevation ({hi:g}) is lower than the minimum ({lo:g})."))

    if criteria['aspect_type'] == ASPECT_CARDINAL and not criteria['cardinal']:
        problems.append(('cardinal', 'error', "Select at least one direction (or set Aspect Filter Type to None)."))

    if criteria['aspect_type'] == ASPECT_DEGREES:
        for key in ('aspect_min', 'aspect_max'):
            value = criteria[key]
            if value is None:
                problems.append((key, 'error', "Required for a degree range."))
            elif not 0 <= value <= 360:
                problems.append((key, 'error', "Must be between 0 and 360 degrees."))

    if criteria['min_max_ppr'] is not None and criteria['min_max_ppr'] < 0:
        problems.append(('min_max_ppr', 'error', "Pressure cannot be negative."))

    if require_any and not problems and not has_any(criteria):
        problems.append(('any', 'warning', "No filter criterion is set - the layers would not be changed."))
    return problems


def has_any(criteria):
    """True if at least one criterion would restrict the features."""
    return any([criteria['elev_min'] is not None, criteria['elev_max'] is not None,
                criteria['aspect_type'] == ASPECT_CARDINAL and bool(criteria['cardinal']),
                criteria['aspect_type'] == ASPECT_DEGREES and criteria['aspect_min'] is not None
                and criteria['aspect_max'] is not None,
                bool(criteria['saf_classes']), criteria['min_max_ppr'] is not None])


def merged_cardinal_ranges(directions):
    """Degree ranges for the given cardinal directions, neighbouring ones merged.

    Example: N + NE + E -> [(0, 112.5), (337.5, 360)]. A range ending at 360 includes 360.
    """
    ranges = sorted(r for d in directions for r in CARDINAL_RANGES.get(d, []))
    merged = []
    for lo, hi in ranges:
        if merged and merged[-1][1] == lo:
            merged[-1] = (merged[-1][0], hi)
        else:
            merged.append((lo, hi))
    return merged


# ------------------------------------------------------------------------- SQL --

def cardinal_sql_conditions(field, directions):
    """SQL conditions (to be joined with OR) for cardinal directions on a numeric aspect field."""
    conditions = []
    for lo, hi in merged_cardinal_ranges(directions):
        upper = f"{field} <= {hi}" if hi >= 360 else f"{field} < {hi}"
        conditions.append(f"({field} >= {lo} AND {upper})")
    return conditions


def numeric_query(criteria, elev_field, aspect_field):
    """SQL WHERE clause for tracks / PRAs (numeric elevation and aspect fields), or None."""
    conditions = []

    if elev_field and criteria['elev_min'] is not None:
        conditions.append(f"{elev_field} >= {criteria['elev_min']}")
    if elev_field and criteria['elev_max'] is not None:
        conditions.append(f"{elev_field} <= {criteria['elev_max']}")

    if aspect_field:
        aspect_type = criteria['aspect_type']
        if aspect_type == ASPECT_CARDINAL and criteria['cardinal']:
            parts = cardinal_sql_conditions(aspect_field, criteria['cardinal'])
            if parts:
                conditions.append(f"({' OR '.join(parts)})")
        elif aspect_type == ASPECT_DEGREES and criteria['aspect_min'] is not None \
                and criteria['aspect_max'] is not None:
            lo, hi = criteria['aspect_min'], criteria['aspect_max']
            if lo <= hi:
                conditions.append(f"({aspect_field} >= {lo} AND {aspect_field} <= {hi})")
            else:
                # wraps around 0/360 (e.g. 350 to 10 degrees)
                conditions.append(f"({aspect_field} >= {lo} OR {aspect_field} <= {hi})")

    return " AND ".join(conditions) if conditions else None


# Cluster tracks (several PRAs released together, ALARM pipeline with aspect-window clusters)
# carry these fields for all members; pra_elev/pra_aspdeg describe only the largest member.
TRACK_MEMBER_FIELDS = ('n_pras', 'asp_set', 'elev_lo', 'elev_hi')


def degree_range_classes(lo, hi):
    """Aspect classes whose degree range overlaps [lo, hi] (wrapping around 0 if lo > hi)."""
    spans = [(lo, hi)] if lo <= hi else [(lo, 360), (0, hi)]
    classes = []
    for name, ranges in CARDINAL_RANGES.items():
        for a, b in ranges:
            # class range [a, b), except that a range ending at 360 also includes 360
            if any(a <= s_hi and (s_lo < b or (b >= 360 and s_lo <= b)) for s_lo, s_hi in spans):
                classes.append(name)
                break
    return classes


def _aspect_classes(criteria):
    """Aspect classes selected by the criteria, or None if there is no aspect filter."""
    if criteria['aspect_type'] == ASPECT_CARDINAL and criteria['cardinal']:
        return [d for d in criteria['cardinal'] if d in CARDINAL_RANGES]
    if criteria['aspect_type'] == ASPECT_DEGREES and criteria['aspect_min'] is not None \
            and criteria['aspect_max'] is not None:
        return degree_range_classes(criteria['aspect_min'], criteria['aspect_max'])
    return None


def _member_conditions(criteria):
    """SQL conditions for cluster tracks: true if any member PRA matches."""
    conditions = []
    if criteria['elev_min'] is not None:
        conditions.append(f"elev_hi >= {criteria['elev_min']}")
    if criteria['elev_max'] is not None:
        conditions.append(f"elev_lo <= {criteria['elev_max']}")
    classes = _aspect_classes(criteria)
    if classes is not None:
        parts = [f"asp_set LIKE '%,{c},%'" for c in classes]
        conditions.append(f"({' OR '.join(parts)})" if parts else "1 = 0")
    return conditions


def track_query(criteria, has_members):
    """SQL WHERE clause for tracks, or None.

    A track of a single PRA is filtered exactly on pra_elev/pra_aspdeg (as numeric_query).
    A cluster track (n_pras > 1) passes when any member matches: its elevation range
    overlaps the filter and one of its aspect classes is selected. A degree range is
    applied to cluster tracks at the resolution of the eight aspect classes.

    Args:
        has_members: the layer has the TRACK_MEMBER_FIELDS (older results do not)
    """
    single = numeric_query(criteria, "pra_elev", "pra_aspdeg")
    if not has_members or single is None:
        return single
    member = " AND ".join(_member_conditions(criteria))
    return f"(((n_pras IS NULL OR n_pras <= 1) AND {single}) OR (n_pras > 1 AND {member}))"


def risk_query(criteria):
    """SQL WHERE clause for the Risk Assessment layer (buildings), or None.

    The aspect of a building is the text field pra_aspct (N, NE, ...), so only cardinal
    directions can be used; a degree range is ignored here.
    """
    conditions = []

    if criteria['elev_min'] is not None:
        conditions.append(f"pra_elev >= {criteria['elev_min']}")
    if criteria['elev_max'] is not None:
        conditions.append(f"pra_elev <= {criteria['elev_max']}")

    if criteria['saf_classes']:
        classes = "', '".join(criteria['saf_classes'])
        conditions.append(f"saf_class IN ('{classes}')")

    if criteria['aspect_type'] == ASPECT_CARDINAL:
        valid = [d for d in criteria['cardinal'] if d in CARDINAL_RANGES]
        if valid:
            dirs = "', '".join(valid)
            conditions.append(f"pra_aspct IN ('{dirs}')")

    if criteria['min_max_ppr'] is not None:
        conditions.append(f"max_ppr >= {criteria['min_max_ppr']}")

    return " AND ".join(conditions) if conditions else None


# ---------------------------------------------------------------------- Python --

def in_elevation(elev, criteria):
    lo, hi = criteria['elev_min'], criteria['elev_max']
    if lo is None and hi is None:
        return True
    if elev is None:
        return False
    return (lo is None or elev >= lo) and (hi is None or elev <= hi)


def matches_numeric(elev, aspect, criteria):
    """Tracks / PRAs: the Python equivalent of numeric_query (numeric aspect in degrees)."""
    if not in_elevation(elev, criteria):
        return False
    aspect_type = criteria['aspect_type']
    if aspect_type == ASPECT_CARDINAL and criteria['cardinal']:
        if aspect is None:
            return False
        # [lo, hi), except that a range ending at 360 also includes 360
        return any(aspect >= lo and (aspect < hi or (hi >= 360 and aspect <= hi))
                   for lo, hi in merged_cardinal_ranges(criteria['cardinal']))
    if aspect_type == ASPECT_DEGREES and criteria['aspect_min'] is not None \
            and criteria['aspect_max'] is not None:
        if aspect is None:
            return False
        lo, hi = criteria['aspect_min'], criteria['aspect_max']
        return (lo <= aspect <= hi) if lo <= hi else (aspect >= lo or aspect <= hi)
    return True


def matches_track(elev, aspect, n_pras, asp_set, elev_lo, elev_hi, criteria):
    """Tracks: the Python equivalent of track_query (member fields may be None)."""
    if n_pras is None or n_pras <= 1:
        return matches_numeric(elev, aspect, criteria)
    lo, hi = criteria['elev_min'], criteria['elev_max']
    if lo is not None and (elev_hi is None or elev_hi < lo):
        return False
    if hi is not None and (elev_lo is None or elev_lo > hi):
        return False
    classes = _aspect_classes(criteria)
    if classes is not None:
        members = set((asp_set or "").strip(",").split(","))
        return any(c in members for c in classes)
    return True


def matches_risk(saf, ppr, elev, aspect_text, criteria):
    """Buildings: the Python equivalent of risk_query."""
    if not in_elevation(elev, criteria):
        return False
    if criteria['saf_classes'] and saf not in criteria['saf_classes']:
        return False
    if criteria['min_max_ppr'] is not None and (ppr is None or ppr < criteria['min_max_ppr']):
        return False
    if criteria['aspect_type'] == ASPECT_CARDINAL:
        dirs = [d for d in criteria['cardinal'] if d in CARDINAL_RANGES]
        if dirs and aspect_text not in dirs:
            return False
    return True


def criteria_notes(criteria):
    """Human readable list of the active criteria (and which layers they apply to)."""
    notes = []
    if criteria['elev_min'] is not None or criteria['elev_max'] is not None:
        lo = "-" if criteria['elev_min'] is None else f"{criteria['elev_min']:g}"
        hi = "-" if criteria['elev_max'] is None else f"{criteria['elev_max']:g}"
        notes.append(f"Elevation: {lo} to {hi} m (tracks, PRAs, buildings)")
    if criteria['aspect_type'] == ASPECT_CARDINAL and criteria['cardinal']:
        notes.append(f"Aspect: {', '.join(criteria['cardinal'])} (tracks, PRAs, buildings)")
    elif criteria['aspect_type'] == ASPECT_DEGREES and criteria['aspect_min'] is not None \
            and criteria['aspect_max'] is not None:
        notes.append(f"Aspect: {criteria['aspect_min']:g} to {criteria['aspect_max']:g} degrees "
                     f"(tracks and PRAs only; not available for buildings)")
    if criteria['saf_classes']:
        notes.append(f"Safety class: {', '.join(criteria['saf_classes'])} (buildings only)")
    if criteria['min_max_ppr'] is not None:
        notes.append(f"Max PPR at least {criteria['min_max_ppr']:g} kPa (buildings only)")
    if not notes:
        notes.append("No filter - all features")
    return notes


def combine_refine(previous_query, new_query):
    """Combine an existing definition query with a new one (AND) for step-by-step filtering."""
    if previous_query:
        return f"({previous_query}) AND ({new_query})"
    return new_query
