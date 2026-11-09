# SPDX-License-Identifier: AGPL-3.0-or-later
"""
152-03.2: EPA pads facility and system names with runs of spaces; OpenH2O saves them single-spaced.

Names are INVENTED padding in the shape EPA sends ("WELL 05 - CHLORINATION
<14 spaces> XCLD"), on the invented system XX0000044. `XCLD` is not expanded: no
published EPA or state source defines it.
"""

import json
from pathlib import Path

import pytest

from drinking import envirofacts_mapping, glossary
from drinking.models import SystemFacility, WaterSystem
from tests.factories import SystemFacilityFactory, WaterSystemFactory

FIXTURES = Path(__file__).resolve().parent.parent / "drinking" / "fixtures"

PADDED = "WELL 05 - CHLORINATION              XCLD"
COLLAPSED = "WELL 05 - CHLORINATION XCLD"
PADDED_SYSTEM = "DEMONSTRATION   WATER\tCOMPANY  "
COLLAPSED_SYSTEM = "DEMONSTRATION WATER COMPANY"


def _facility(**changes):
    row = dict(json.loads((FIXTURES / "envirofacts_facilities.json").read_text())[0])
    row.update(changes)
    return row


def _system(**changes):
    row = dict(json.loads((FIXTURES / "envirofacts_water_system.json").read_text())[0])
    row.update(changes)
    return row


def test_a_facility_name_is_collapsed():
    mapped = envirofacts_mapping.map_facility(_facility(facility_name=PADDED))
    assert mapped["name"] == COLLAPSED


@pytest.mark.parametrize(
    "raw",
    ["  WELL 05  ", "WELL\t05", "WELL  05", "WELL \t 05"],
)
def test_leading_trailing_tab_and_double_spaces_go(raw):
    mapped = envirofacts_mapping.map_facility(_facility(facility_name=raw))
    assert mapped["name"] == "WELL 05"


def test_the_system_name_is_collapsed():
    mapped = envirofacts_mapping.map_water_system(_system(pws_name=PADDED_SYSTEM))
    assert mapped["name"] == COLLAPSED_SYSTEM


def test_a_refresh_rewrites_a_stored_padded_name(db):
    system = WaterSystemFactory(pwsid="XX0000044", name=PADDED_SYSTEM)
    SystemFacilityFactory(system=system, facility_id="010", name=PADDED)

    envirofacts_mapping.commit_system(
        _system(pwsid="XX0000044", pws_name=PADDED_SYSTEM),
        [_facility(pwsid="XX0000044", state_facility_id="010", facility_name=PADDED)],
    )

    assert WaterSystem.objects.get(pwsid="XX0000044").name == COLLAPSED_SYSTEM
    assert SystemFacility.objects.get(system=system, facility_id="010").name == COLLAPSED


def test_a_new_commit_saves_collapsed_names(db):
    envirofacts_mapping.commit_system(
        _system(pwsid="XX0000044", pws_name=PADDED_SYSTEM),
        [_facility(pwsid="XX0000044", state_facility_id="010", facility_name=PADDED)],
    )
    assert WaterSystem.objects.get().name == COLLAPSED_SYSTEM
    assert SystemFacility.objects.get().name == COLLAPSED


def test_xcld_is_not_expanded():
    assert "XCLD" not in glossary.SHORTHAND
