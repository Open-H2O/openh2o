# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest


@pytest.fixture(autouse=True)
def enable_db_access_for_all_tests(db):
    pass


@pytest.fixture(autouse=True)
def calculation_runs_inline(settings):
    """149-01: a saved record or a button press runs the calculation in-process.

    Production starts ``manage.py run_accounting --request N`` as its own
    process; the suite must never spawn one.
    """
    settings.OPENH2O_CALCULATION_INLINE = True
