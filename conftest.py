# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest


#: Each case boots its own Django process on its own database, so the cases
#: need not share a worker.
SPLIT_FILES = ("tests/test_droppability_acceptance.py",)


def pytest_xdist_make_scheduler(config, log):
    """``--dist loadfile``, except the module-drop file is dealt one test at a time.

    loadfile keeps a file on one worker. The module-drop file is about half the
    serial run on its own, so on one worker it decides when the whole run ends
    however many CPUs the others have. Only called when xdist is running.
    """
    if config.getoption("dist") != "loadfile":
        return None
    from xdist.scheduler import LoadFileScheduling

    class LoadFileSplittingDrop(LoadFileScheduling):
        def _split_scope(self, nodeid):
            if nodeid.split("::", 1)[0] in SPLIT_FILES:
                return nodeid
            return super()._split_scope(nodeid)

    return LoadFileSplittingDrop(config, log)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item, nextitem):
    """Put the migration-seeded rows back after a ``transaction=True`` test.

    Such a test ends with a flush that empties EVERY table, including the
    reference rows data migrations seed (irrigation methods and the like). A
    serial run hides that, because pytest-django runs transactional tests last.
    Under xdist a worker goes on to run other files after one, and they found
    the tables empty. ``serialized_rollback=True`` alone does not help: Django
    reloads the snapshot BEFORE such a test and still flushes after it. So the
    snapshot is reloaded here, after the flush, once the test's own teardown
    has finished. Not after the last test: by then the test database is gone.
    """
    result = yield
    marker = item.get_closest_marker("django_db")
    if nextitem is None or marker is None or not marker.kwargs.get("transaction"):
        return result
    from django.db import connection
    from pytest_django.plugin import blocking_manager_key

    contents = getattr(connection, "_test_serialized_contents", None)
    if contents is None:
        raise RuntimeError(
            f"{item.nodeid} is marked django_db(transaction=True) without "
            "serialized_rollback=True, so the seeded rows its flush deletes cannot be "
            "put back for the tests that follow. Add serialized_rollback=True to its "
            "mark. (For Claude, as the fixer. If you are not Claude, paste this "
            "message to Claude.)"
        )
    with item.config.stash[blocking_manager_key].unblock():
        connection.creation.deserialize_db_from_string(contents)
    return result


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
