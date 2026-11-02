# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Unified parameter label registry.

Merges PARAMETER_MAP dicts from all adapters into a single lookup
keyed by (source_code, parameter_code). Provides human-readable
labels ("Name (unit)") for use across views and templates, and the plain words
for a daily statistic ("daily high") where a source publishes several.
"""

# USGS statistic codes, in the words a reader would use. Any other non-blank
# code is named by its number rather than guessed at.
STATISTIC_WORDS = {
    "00001": "daily high",
    "00002": "daily low",
    "00003": "daily average",
    "00008": "daily median",
}


def get_all_parameter_maps():
    """
    Return a dict keyed by (source_code, parameter_code) → {"name": str, "unit": str}.

    Imports each adapter's PARAMETER_MAP lazily to avoid circular import issues.
    Adapters without a PARAMETER_MAP are silently skipped.
    """
    # Import each adapter module and extract PARAMETER_MAP.
    # Done lazily here (inside the function) to avoid circular imports,
    # since each adapter module imports register_adapter from __init__.
    # Adapters without PARAMETER_MAP (e.g. openet) are simply omitted.
    def _safe_map(module_path):
        try:
            import importlib
            mod = importlib.import_module(module_path)
            return getattr(mod, "PARAMETER_MAP", None)
        except ImportError:
            return None

    sources = [
        ("cdec", _safe_map("datasync.adapters.cdec")),
        ("usgs", _safe_map("datasync.adapters.usgs")),
        ("dwr_wdl", _safe_map("datasync.adapters.dwr_wdl")),
        ("dwr_sgma", _safe_map("datasync.adapters.dwr_sgma")),
        ("cimis", _safe_map("datasync.adapters.cimis")),
        ("noaa", _safe_map("datasync.adapters.noaa")),
        ("cnrfc", _safe_map("datasync.adapters.cnrfc")),
        # The source whose readings are typed by hand has no adapter; its
        # parameters are the USGS ones, so a typed code reads with the same words.
        ("manual", _safe_map("datasync.adapters.usgs")),
    ]

    merged = {}
    for source_code, param_map in sources:
        if not isinstance(param_map, dict):
            continue
        for param_code, info in param_map.items():
            if not isinstance(info, dict):
                continue
            merged[(source_code, str(param_code))] = {
                "name": info.get("name", str(param_code)),
                "unit": info.get("unit", ""),
            }
    return merged


def statistic_words(statistic):
    """
    Return the plain words for a statistic code, or "" for a blank one.

    Examples:
        statistic_words("00001")  → "daily high"
        statistic_words("00099")  → "statistic 00099"
        statistic_words("")       → ""
    """
    if not statistic:
        return ""
    return STATISTIC_WORDS.get(statistic, f"statistic {statistic}")


def get_parameter_label(source_code, parameter_code, statistic=""):
    """
    Return "Name (unit)" for a given source + parameter code, with the
    statistic in words after the name when one is given.

    Falls back to the raw parameter_code string if not found. The caller
    passes a statistic only where the station holds more than one for the
    parameter; a lone statistic is left unnamed.

    Examples:
        get_parameter_label("cdec", "15")     → "Reservoir Storage (AF)"
        get_parameter_label("usgs", "00060")  → "Discharge (cfs)"
        get_parameter_label("usgs", "00010", "00001")
                                              → "Water Temperature, daily high (deg C)"
        get_parameter_label("cdec", "999")    → "999"
    """
    all_maps = get_all_parameter_maps()
    info = all_maps.get((source_code, str(parameter_code)))
    if info is None:
        name = str(parameter_code)
        unit = ""
    else:
        name = info.get("name", str(parameter_code))
        unit = info.get("unit", "")
    words = statistic_words(statistic)
    if words:
        name = f"{name}, {words}"
    if unit:
        return f"{name} ({unit})"
    return name


# The order the Add a reading form offers the parameters in: the four a person
# reads at a gauge or a well first, then the two groundwater elevations.
MANUAL_PARAMETER_ORDER = ("00065", "00060", "00010", "72019", "72020", "62610")


def manual_parameter_choices():
    """[(code, "Name (unit)")] for the Add a reading form, from the USGS parameter map."""
    maps = get_all_parameter_maps()
    return [
        (code, get_parameter_label("manual", code))
        for code in MANUAL_PARAMETER_ORDER
        if ("manual", code) in maps
    ]


def manual_parameter_unit(code):
    """The unit the USGS map gives a parameter code, or "" for an unknown code."""
    return get_all_parameter_maps().get(("manual", str(code)), {}).get("unit", "")
