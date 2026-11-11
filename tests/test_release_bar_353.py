# SPDX-License-Identifier: AGPL-3.0-or-later
"""When OpenET reports a different figure for a month, nothing that month counts changes on its own.

Ruling 134 (the plain write-up Brent approved): a month's crop ET from OpenET is recorded
once, the first time it is fetched, with the day it was fetched. The calculation and the
ledger's ET estimate entry use that record. A second fetch with a different figure leaves
the record, the entry, the calculated row and the pumped figure as they were, and the
person who ran the fetch is told which month now differs.

Rainfall is not covered by the ruling; its open part is the strict xfail in
``tests/test_openet_recorded_figure.py``.
"""

from decimal import Decimal as D

import pytest

from tests.test_openet_recorded_figure import (
    AUG_6,
    FIRST,
    JULY,
    NEWER,
    SEP_28,
    _calculated_row,
    _corn_field,
    _estimate,
    _fetch,
    _recorded,
    _run,
    _sync,
)
from tests import ledger_districts as ld

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _web_service(settings):
    settings.OPENET_MODE = "api"


def test_a_second_fetch_with_a_different_figure_changes_nothing_and_names_the_month():
    field = _corn_field()
    _fetch(field, FIRST, AUG_6)
    _sync()
    ld.run_months([JULY])

    assert _recorded(field) == (D("91.44"), AUG_6)
    assert -_estimate(field) == _run(field).gross_et_af == D("30.0000")

    out = _fetch(field, NEWER, SEP_28)
    _sync()
    ld.run_months([JULY])

    assert _recorded(field) == (D("91.44"), AUG_6)
    assert -_estimate(field) == _run(field).gross_et_af == D("30.0000")
    assert _calculated_row(field) == D("-30.0000")
    assert _run(field).gw_extracted_af == D("37.5000")
    assert "F4 Jul 2025" in out
