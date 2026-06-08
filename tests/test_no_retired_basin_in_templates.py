"""Guard: no retired demo-basin name may be hardcoded in a user-facing template.

Post-mortem 2026-06-08: a hardcoded "Kaweah" GSA legend in
``templates/geography/map.html`` survived the v1.9 Kaweah->Merced demo migration
and displayed retired-basin names on the live evaluator-facing map for weeks. The
map legend and zone colors are now DERIVED from the live zone data
(``geography.views.map_view``), so they cannot name a basin that is not in the
database. This test stops a NEW hardcoded retired-basin string from re-entering a
template and reopening the same defect class.

Basin-specific copy belongs in the database, not the markup.
"""
from pathlib import Path

import pytest

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# Demo basins the product has retired. Never hand-type one into a template again.
RETIRED_BASIN_NAMES = ["Kaweah"]


def _template_files():
    return sorted(TEMPLATES_DIR.rglob("*.html"))


@pytest.mark.parametrize("name", RETIRED_BASIN_NAMES)
def test_no_retired_basin_name_in_templates(name):
    offenders = [
        str(path.relative_to(TEMPLATES_DIR.parent))
        for path in _template_files()
        if name.lower() in path.read_text(encoding="utf-8").lower()
    ]
    assert not offenders, (
        f"Retired basin name {name!r} found in user-facing template(s): "
        f"{offenders}. Basin-specific labels must come from the database "
        f"(see geography.views.map_view), not be hardcoded in markup."
    )
