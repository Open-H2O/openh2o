"""
Unified parameter label registry.

Merges PARAMETER_MAP dicts from all adapters into a single lookup
keyed by (source_code, parameter_code). Provides human-readable
labels ("Name (unit)") for use across views and templates.
"""


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


def get_parameter_label(source_code, parameter_code):
    """
    Return "Name (unit)" for a given source + parameter code.

    Falls back to the raw parameter_code string if not found.

    Examples:
        get_parameter_label("cdec", "15")     → "Reservoir Storage (AF)"
        get_parameter_label("usgs", "00060")  → "Discharge (cfs)"
        get_parameter_label("cdec", "999")    → "999"
    """
    all_maps = get_all_parameter_maps()
    info = all_maps.get((source_code, str(parameter_code)))
    if info is None:
        return str(parameter_code)
    name = info.get("name", str(parameter_code))
    unit = info.get("unit", "")
    if unit:
        return f"{name} ({unit})"
    return name
