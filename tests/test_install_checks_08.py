# SPDX-License-Identifier: AGPL-3.0-or-later
"""The two install checks: the clean-install command and the stale-image guard.

``verify_clean_install`` has to pass a correct install of every module set, not
only the ones that carry the data-sync module, and has to fail an install whose
reference tables are empty. ``assert-image-fresh.sh`` has to list the files the
image is built from: the ones git has not been told about yet, but not the ones
git or the Docker build ignore.

The command tests build real databases in subprocesses, the way a deployment
does: one scratch database per module set, migrated and seeded for real, then
dropped. They take a few minutes.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "scripts" / "assert-image-fresh.sh"

# -- the command -------------------------------------------------------------

#: Module sets built the way the droppability harness builds a reduced one: a
#: list that names the modules to keep and lets the registry add what they need.
SETS = {
    "drinking": "core,geography,measurements,standards,drinking,setup,infrastructure,health,feedback",
    "surface": "core,geography,measurements,standards,parcels,accounting,surface,reporting,setup,infrastructure,health,feedback",
    "recharge": "core,geography,measurements,standards,parcels,accounting,surface,recharge,setup,infrastructure,health,feedback",
    "full": "all",
}


def _admin_url():
    # The maintenance database: the one the scratch databases are made from.
    parts = urlsplit(os.environ["DATABASE_URL"])
    return urlunsplit(parts._replace(path="/postgres"))


def _url_for(name):
    parts = urlsplit(_admin_url())
    return urlunsplit(parts._replace(path="/" + name))


def _pg_url(url):
    # django-environ spells the scheme "postgis"; psycopg wants "postgresql".
    return "postgresql" + url[url.index("://"):]


def _run_manage(shape, *args):
    settings_for_run = dict(os.environ)
    settings_for_run["OPENH2O_MODULES"] = SETS[shape]
    settings_for_run["DATABASE_URL"] = _url_for(f"openh2o_t8_ic_{shape}")
    settings_for_run["DJANGO_SETTINGS_MODULE"] = "config.settings.local"
    return subprocess.run(
        [sys.executable, "manage.py", *args],
        cwd=ROOT,
        env=settings_for_run,
        capture_output=True,
        text=True,
        timeout=900,
    )


def _sql(shape, statement):
    code = (
        "from django.db import connection\n"
        "with connection.cursor() as c:\n"
        f"    c.execute({statement!r})\n"
    )
    result = _run_manage(shape, "shell", "-c", code)
    assert result.returncode == 0, result.stderr
    return result


@pytest.fixture(scope="module")
def installs():
    import psycopg

    admin = psycopg.connect(_pg_url(_admin_url()), autocommit=True)
    names = {shape: f"openh2o_t8_ic_{shape}" for shape in SETS}
    try:
        for name in names.values():
            admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
            admin.execute(f'CREATE DATABASE "{name}"')
        for shape in SETS:
            for step in (("migrate", "--noinput"), ("seed_data",)):
                done = _run_manage(shape, *step)
                assert done.returncode == 0, f"{shape} {step}: {done.stderr[-2000:]}"
        yield names
    finally:
        for name in names.values():
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.close()


@pytest.mark.parametrize("shape", list(SETS))
def test_a_correct_install_of_every_module_set_passes(installs, shape):
    result = _run_manage(shape, "verify_clean_install")
    assert result.returncode == 0, result.stderr + result.stdout


def test_one_row_of_content_fails_the_check(installs):
    _sql(
        "drinking",
        "INSERT INTO geography_boundary (name, description, geometry, basin_code, huc, "
        "created_at, updated_at) VALUES ('Scratch', '', "
        "ST_Multi(ST_GeomFromText('POLYGON((0 0,0 1,1 1,0 0))', 4326)), '', '', now(), now())",
    )
    try:
        result = _run_manage("drinking", "verify_clean_install")
        assert result.returncode == 1
        assert "boundar" in result.stderr.lower()
    finally:
        _sql("drinking", "DELETE FROM geography_boundary")


@pytest.mark.parametrize(
    "shape, table, words",
    [
        ("full", "datasync_datasource", "data source"),
        ("drinking", "drinking_analyte", "analyte"),
        ("surface", "surface_waterrighttype", "water right type"),
        ("full", "reporting_reporttemplate", "report template"),
        ("full", "wells_welltype", "well type"),
        ("full", "accounting_watertype", "water type"),
        ("full", "standards_observedproperty", "observed propert"),
    ],
)
def test_an_enabled_module_with_an_empty_seed_table_fails_naming_it(
    installs, shape, table, words
):
    _sql(shape, f"TRUNCATE {table} CASCADE")
    try:
        result = _run_manage(shape, "verify_clean_install")
        assert result.returncode == 1
        assert words in result.stderr.lower()
        assert "empty" in result.stderr.lower()
    finally:
        done = _run_manage(shape, "seed_data")
        assert done.returncode == 0, done.stderr


def test_a_module_that_is_off_is_not_asked_for_its_seed_table(installs):
    # The drinking set has no data-sync module, so its data source table is
    # empty on a correct install and the check must not ask for it.
    result = _run_manage("drinking", "verify_clean_install")
    assert result.returncode == 0, result.stderr


# -- the guard ---------------------------------------------------------------

needs_git = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="the guard is a host script and needs git; the web image has none",
)


def _git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=t", *args],
        cwd=cwd, check=True, capture_output=True,
    )


def _guard_list(cwd):
    result = subprocess.run(
        ["bash", str(GUARD), "--list"], cwd=cwd, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


@pytest.fixture
def work(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "keep.py").write_text("x = 1\n")
    (tmp_path / "app" / "page.html").write_text("<p>a</p>\n")
    (tmp_path / ".gitignore").write_text("ignored.py\nbuild/\n")
    (tmp_path / ".dockerignore").write_text(
        "# comment\n.gitignore\n.dockerignore\n.planning\nbackups/\n*.pyc\n"
    )
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    return tmp_path


@needs_git
def test_the_list_holds_a_file_git_has_not_been_told_about(work):
    (work / "new_module.py").write_text("y = 2\n")
    assert "new_module.py" in _guard_list(work)


@needs_git
def test_the_list_leaves_out_what_git_ignores(work):
    (work / "ignored.py").write_text("z = 3\n")
    (work / "build").mkdir()
    (work / "build" / "out.json").write_text("{}\n")
    listed = _guard_list(work)
    assert "ignored.py" not in listed
    assert "build/out.json" not in listed


@needs_git
def test_the_list_leaves_out_what_the_image_build_leaves_out(work):
    # Tracked or not, a file the Docker build ignores is never in the image, so
    # listing it would report a stale image for ever.
    (work / "backups").mkdir()
    (work / "backups" / "dump.json").write_text("{}\n")
    (work / ".planning").mkdir()
    (work / ".planning" / "state.json").write_text("{}\n")
    _git(work, "add", "-f", "backups/dump.json")
    listed = _guard_list(work)
    assert "backups/dump.json" not in listed
    assert ".planning/state.json" not in listed
    assert ".gitignore" not in listed
    assert "keep.py" in listed and "app/page.html" in listed


@needs_git
def test_a_name_the_build_ignores_at_the_top_stays_in_below_it(work):
    # A .dockerignore pattern without a slash in the middle is read from the
    # top folder only.
    (work / "app" / "backups").mkdir()
    (work / "app" / "backups" / "keep.json").write_text("{}\n")
    assert "app/backups/keep.json" in _guard_list(work)


@needs_git
def test_the_count_moves_by_one_when_a_file_is_added(work):
    before = len(_guard_list(work))
    (work / "another.py").write_text("w = 4\n")
    assert len(_guard_list(work)) == before + 1
    counted = subprocess.run(
        ["bash", str(GUARD), "--count"], cwd=work, capture_output=True, text=True
    )
    assert counted.stdout.strip() == str(before + 1)


@needs_git
def test_a_file_deleted_from_disk_is_not_listed(work):
    (work / "keep.py").unlink()
    assert "keep.py" not in _guard_list(work)
