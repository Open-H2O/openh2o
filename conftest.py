# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest


@pytest.fixture(autouse=True)
def enable_db_access_for_all_tests(db):
    pass


@pytest.fixture(autouse=True)
def calculation_runs_inline(settings):
    """A saved record or a button press runs the calculation in-process.

    Production starts ``manage.py run_accounting --request N`` as its own
    process; the suite must never spawn one.
    """
    settings.OPENH2O_CALCULATION_INLINE = True


@pytest.fixture(autouse=True)
def import_runs_inline(settings, tmp_path):
    """Import on a bulk import page commits in-process, on a throwaway disk.

    Production starts ``manage.py run_pending_import --token <uuid>`` as its
    own process; the suite must never spawn one. A preview saves the upload
    under ``MEDIA_ROOT/imports/``, so the suite points that at the test's own
    temporary folder.
    """
    settings.OPENH2O_IMPORT_INLINE = True
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture(autouse=True)
def station_fetch_runs_inline(settings):
    """A press of Fetch readings now runs the fetch in-process.

    Production starts ``manage.py sync_source <code> --station N --log N`` as
    its own process; the suite must never spawn one. A test that counts the
    processes turns this off and patches ``subprocess.Popen``.
    """
    settings.OPENH2O_FETCH_INLINE = True
