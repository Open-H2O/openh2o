# SPDX-License-Identifier: AGPL-3.0-or-later
"""The committed GSA fixture carries only the fictional set."""
import json

import pytest

from core.management.commands.seed_merced_gsas import FIXTURE


def _features():
    with open(FIXTURE) as f:
        return json.load(f)["features"]


@pytest.mark.django_db
def test_fixture_names_carry_no_real_agency_identity():
    """The committed fixture must never regain the real names, DWR IDs or URLs.

    The tripwire against a future session "restoring" the layer by re-fetching
    it from the SGMA portal, which would return the real agencies, their real
    DWR identifiers and their live websites. Asserted as an exact allow-list of
    the fictional set rather than a deny-list of the real names, because a
    deny-list would mean writing those real names back into the repo — the very
    thing this phase deleted.
    """
    features = _features()
    assert {ft["properties"]["GSA_Name"] for ft in features} == {
        "Halvern Valley GSA",
        "Halvern Irrigation-Urban GSA",
        "Verdano Island Water District GSA",
    }
    for props in (ft["properties"] for ft in features):
        # Real DWR GSA_IDs are low integers; 9000+ is outside the assigned range.
        assert props["GSA_ID"] >= 9000, "a real DWR GSA_ID is back in the fixture"
        assert props["GSA_URL"] == "", "a real agency URL is back in the fixture"
