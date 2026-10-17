# SPDX-License-Identifier: AGPL-3.0-or-later
"""150.2-01: irrigation methods move from `surface` into `parcels`.

The software has to serve groundwater-only growers and water managers. A
groundwater-only district runs without
`surface`, and its fields have irrigation methods too, so the two models and
the ``field_efficiency`` lookup now live in `parcels`.

Three paths, each run for real:

1. A deployment that already has the tables (every existing one): migrated to
   the last state before the move, given rows, then migrated forward in a
   scratch database. Every method row and every use area's method keeps its
   pk, an agency's edit to a method is kept rather than re-seeded, the history
   rows move with their tables, and the history triggers fire on the new ones.
2. A fresh deployment without `surface`: ``migrate`` from zero in a scratch
   database builds the tables, seeds East Turlock's 18 rows, and
   ``field_efficiency`` reads a field's method.
3. A fresh deployment with every module: this suite's own test database,
   built by the ordinary ``migrate``, holds the tables under `parcels` names
   and no `surface` copy.

Paths 1 and 2 shell out to ``manage.py`` with a DATABASE_URL naming a
throwaway database, the way ``tests/test_droppability_acceptance.py`` boots a
reduced deployment: a process's app registry is fixed at start-up, so a module
set cannot be changed inside this one.
"""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from django.conf import settings
from django.db import connection

from tests.test_droppability_acceptance import _module_list

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_URL = "postgis://openh2o:openh2o@db:5432/openh2o"

PARCELS_TABLES = {
    "parcels_irrigationmethod",
    "parcels_parcelirrigationmethod",
    "parcels_irrigationmethodevent",
    "parcels_parcelirrigationmethodevent",
}
SURFACE_TABLES = {name.replace("parcels_", "surface_", 1) for name in PARCELS_TABLES}
OLD_TRIGGER_NAMES = {
    "pgtrigger_insert_insert_2d181",
    "pgtrigger_before_update_update_4002a",
    "pgtrigger_update_update_67c5f",
    "pgtrigger_delete_delete_1192b",
    "pgtrigger_insert_insert_a16f6",
    "pgtrigger_before_update_update_799a0",
    "pgtrigger_update_update_7e0a3",
    "pgtrigger_delete_delete_21b22",
}


# ---------------------------------------------------------------------------
# A scratch database per test
# ---------------------------------------------------------------------------


def _admin_conninfo():
    db = settings.DATABASES["default"]
    return {
        "host": db["HOST"],
        "port": db["PORT"] or 5432,
        "user": db["USER"],
        "password": db["PASSWORD"],
        "dbname": "postgres",
    }


@pytest.fixture
def scratch_db():
    """A database name nobody else uses, dropped afterwards."""
    name = f"openh2o_irrmove_{uuid.uuid4().hex[:8]}"
    yield name
    with psycopg.connect(**_admin_conninfo(), autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _url(name):
    base = os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL
    return urlunsplit(urlsplit(base)._replace(path=f"/{name}"))


def _manage(db_name, *args, modules=None, must_succeed=True):
    env = dict(os.environ)
    env["DATABASE_URL"] = _url(db_name)
    if modules is not None:
        env["OPENH2O_MODULES"] = modules
    else:
        env.pop("OPENH2O_MODULES", None)
    env["DJANGO_SETTINGS_MODULE"] = "config.settings.local"
    result = subprocess.run(
        [sys.executable, "manage.py", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0 or not must_succeed, (
        f"manage.py {' '.join(args)} failed\n--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    return result.stdout


def _create(db_name):
    with psycopg.connect(**_admin_conninfo(), autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{db_name}"')


def _sql(db_name, statement, params=None):
    info = dict(_admin_conninfo(), dbname=db_name)
    with psycopg.connect(**info, autocommit=True) as conn:
        cur = conn.execute(statement, params)
        return cur.fetchall() if cur.description else None


def _tables(db_name):
    rows = _sql(
        db_name,
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'",
    )
    return {row[0] for row in rows}


def _shell(db_name, code, modules=None):
    """Run ``code`` in a Django shell; its last printed line is JSON."""
    out = _manage(db_name, "shell", "-c", code, modules=modules)
    return json.loads(out.strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# 1. An existing deployment: every row keeps its pk
# ---------------------------------------------------------------------------


def test_existing_rows_move_with_their_pks(scratch_db):
    _create(scratch_db)
    # `sites` and `core` first: `core`'s post_migrate handler (site identity)
    # reads both tables, and a partial migrate still fires it. `sites` alone
    # applies and commits its migrations, then that handler fails on the
    # missing `core` table; `core` next finds both.
    _manage(scratch_db, "migrate", "sites", must_succeed=False)
    _manage(scratch_db, "migrate", "core")
    _manage(scratch_db, "migrate", "surface", "0022_field_labels_calwatrs_pin_max_rate")
    _manage(scratch_db, "migrate", "parcels", "0012_parcelledger_etaw_words")
    assert SURFACE_TABLES <= _tables(scratch_db)
    assert not PARCELS_TABLES & _tables(scratch_db)

    # Three use areas, two of them with a method; one method edited by the
    # agency (its UPDATE writes two history rows through the old triggers).
    for number in ("MOVE-1", "MOVE-2", "MOVE-3"):
        _sql(
            scratch_db,
            "INSERT INTO parcels_parcel (parcel_number, owner_name, area_override, "
            "status, address, notes, created_at, updated_at) "
            "VALUES (%s, '', false, 'active', '', '', now(), now())",
            (number,),
        )
    parcel_ids = dict(_sql(scratch_db, "SELECT parcel_number, id FROM parcels_parcel"))
    method_ids = dict(_sql(scratch_db, "SELECT name, id FROM surface_irrigationmethod"))
    _sql(
        scratch_db,
        "INSERT INTO surface_parcelirrigationmethod (parcel_id, method_id) "
        "VALUES (%s, %s), (%s, %s)",
        (
            parcel_ids["MOVE-1"], method_ids["Center Pivot"],
            parcel_ids["MOVE-2"], method_ids["Surface Drip"],
        ),
    )
    _sql(
        scratch_db,
        "UPDATE surface_irrigationmethod SET assigned_efficiency = 0.850 "
        "WHERE name = 'Center Pivot'",
    )
    before_methods = sorted(
        _sql(scratch_db, "SELECT id, name, assigned_efficiency FROM surface_irrigationmethod")
    )
    before_links = sorted(
        _sql(scratch_db, "SELECT id, parcel_id, method_id FROM surface_parcelirrigationmethod")
    )
    before_events = sorted(
        _sql(scratch_db, "SELECT pgh_id, pgh_label, pgh_obj_id FROM surface_irrigationmethodevent")
    )
    before_link_events = sorted(
        _sql(scratch_db, "SELECT pgh_id, pgh_label, pgh_obj_id FROM surface_parcelirrigationmethodevent")
    )
    assert len(before_methods) == 18
    # The edit's before and after rows; the two links' insert rows.
    assert [label for _, label, _ in before_events] == ["before_update", "update"]
    assert [label for _, label, _ in before_link_events] == ["insert", "insert"]

    _manage(scratch_db, "migrate")

    tables = _tables(scratch_db)
    assert PARCELS_TABLES <= tables
    assert not SURFACE_TABLES & tables
    assert sorted(
        _sql(scratch_db, "SELECT id, name, assigned_efficiency FROM parcels_irrigationmethod")
    ) == before_methods
    assert sorted(
        _sql(scratch_db, "SELECT id, parcel_id, method_id FROM parcels_parcelirrigationmethod")
    ) == before_links
    assert sorted(
        _sql(scratch_db, "SELECT pgh_id, pgh_label, pgh_obj_id FROM parcels_irrigationmethodevent")
    ) == before_events
    assert sorted(
        _sql(scratch_db, "SELECT pgh_id, pgh_label, pgh_obj_id FROM parcels_parcelirrigationmethodevent")
    ) == before_link_events
    leftover = _sql(
        scratch_db,
        "SELECT proname FROM pg_proc WHERE proname = ANY(%s)",
        (sorted(OLD_TRIGGER_NAMES),),
    )
    assert leftover == []

    # The new triggers write history, the pk sequence continues past the
    # carried rows, and the lookup reads the carried assignment.
    result = _shell(
        scratch_db,
        "import json\n"
        "from parcels.models import IrrigationMethod, Parcel, ParcelIrrigationMethod\n"
        "from parcels.services import field_efficiency\n"
        "p = Parcel.objects.get(parcel_number='MOVE-3')\n"
        "link = ParcelIrrigationMethod.objects.create(parcel=p, method=IrrigationMethod.objects.get(name='Basin'))\n"
        "pivot = Parcel.objects.get(parcel_number='MOVE-1')\n"
        "print(json.dumps({'new_id': link.pk, 'events': link.events.count(),\n"
        "  'pivot': [str(v) for v in field_efficiency(pivot)]}))\n",
    )
    assert result["new_id"] > max(link_id for link_id, _, _ in before_links)
    assert result["events"] == 1
    assert result["pivot"] == ["0.850", "method"]


# ---------------------------------------------------------------------------
# 2. A fresh deployment without `surface`
# ---------------------------------------------------------------------------


def test_fresh_groundwater_only_deployment_has_the_methods(scratch_db):
    modules = _module_list("surface")
    assert "surface" not in modules.split(",")
    assert "parcels" in modules.split(",")
    _create(scratch_db)
    _manage(scratch_db, "migrate", modules=modules)

    tables = _tables(scratch_db)
    assert PARCELS_TABLES <= tables
    assert not SURFACE_TABLES & tables

    result = _shell(
        scratch_db,
        "import json\n"
        "from parcels.models import IrrigationMethod, Parcel, ParcelIrrigationMethod\n"
        "from parcels.services import field_efficiency\n"
        "names = list(IrrigationMethod.objects.values_list('name', flat=True))\n"
        "p = Parcel.objects.create(parcel_number='GW-1')\n"
        "bare = Parcel.objects.create(parcel_number='GW-2')\n"
        "ParcelIrrigationMethod.objects.create(parcel=p, method=IrrigationMethod.objects.get(name='Subsurface Drip'))\n"
        "p = Parcel.objects.get(pk=p.pk)\n"
        "print(json.dumps({'count': len(names), 'first': names[0], 'last': names[-1],\n"
        "  'drip': [str(v) for v in field_efficiency(p)],\n"
        "  'bare': [str(v) for v in field_efficiency(bare)]}))\n",
        modules=modules,
    )
    assert result == {
        "count": 18,
        "first": "LEPA",
        "last": "Subsurface Drip",
        "drip": ["0.950", "method"],
        "bare": ["0.750", "agency"],
    }


# ---------------------------------------------------------------------------
# 3. A fresh deployment with every module (this suite's own database)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_full_install_keeps_one_copy_under_parcels():
    from parcels.models import IrrigationMethod, ParcelIrrigationMethod

    assert IrrigationMethod._meta.db_table == "parcels_irrigationmethod"
    assert ParcelIrrigationMethod._meta.db_table == "parcels_parcelirrigationmethod"
    with connection.cursor() as cursor:
        tables = set(connection.introspection.table_names(cursor))
    assert PARCELS_TABLES <= tables
    assert not SURFACE_TABLES & tables
    assert IrrigationMethod.objects.count() == 18
