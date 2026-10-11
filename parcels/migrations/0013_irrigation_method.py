# 150.2-01: the irrigation-method table and each use area's method move from
# `surface` into `parcels`, so a deployment with no canals records them too
# (Brent, 2026-10-11 11:27 PDT: "we need this software to help groundwater-only
# growers and water managers").
#
# HOW THE ROWS MOVE, AND WHY THIS WAY. The plan preferred keeping the physical
# tables and moving only Django's state. Kept as `surface_*` names, though, a
# groundwater-only deployment would own tables named for a module it does not
# run, and the droppability harness reads `surface`'s migrations to decide
# which tables must be ABSENT without it. So the tables are RENAMED instead,
# which still moves no row: every row keeps its pk, and the history rows move
# with their tables.
#
#   1. `adopt_surface_tables`: where `surface_irrigationmethod` exists (any
#      deployment that has run `surface` 0015), drop the eight old history
#      triggers (their functions write into the old `surface_*` event tables by
#      name) and rename the four tables, and their id sequences, to the
#      `parcels_*` names. Decided by introspection, never by a migration
#      dependency on `surface`: the composition rule forbids that edge
#      (tests/test_composition_rule.py), and a deployment without `surface`
#      must be able to build this graph.
#   2. State only: the four models (two tracked models, two history models)
#      enter `parcels`.
#   3. `create_absent_tables`: on a deployment that never had the tables (a
#      fresh install, with or without `surface`), create them.
#   4. `seed`: East Turlock's 18 rows, written only into an EMPTY table, so an
#      adopted table keeps whatever the agency has done to it. Before the
#      triggers, as `surface` 0016 came before 0018, so the seeded rows carry
#      no history rows of their own.
#   5. The eight history triggers, installed fresh against the `parcels_*`
#      tables in both cases.
#
# On a fresh install WITH `surface`, Django may run `surface` 0015/0016 before
# or after this migration (neither depends on the other). Before: step 1 adopts
# them. After: they build a second, `surface_*` copy holding only the seeded
# rows, and `surface` 0023 (which depends on this migration) drops it.
#
# A migration keeps meaning what it meant on the day it ran (the parcels
# 0009/0011 rule): table names, trigger names and the seeded strings are
# copied in here, never imported from live code.

from decimal import Decimal

import django.db.models.deletion
import pgtrigger.compiler
import pgtrigger.migrations
from django.db import migrations, models

# Old name -> new name, tracked tables before their history tables.
RENAMES = [
    ("surface_irrigationmethod", "parcels_irrigationmethod"),
    ("surface_parcelirrigationmethod", "parcels_parcelirrigationmethod"),
    ("surface_irrigationmethodevent", "parcels_irrigationmethodevent"),
    ("surface_parcelirrigationmethodevent", "parcels_parcelirrigationmethodevent"),
]

# The history triggers `surface` 0018 installed, by table. Each trigger and its
# function share the name.
OLD_TRIGGERS = {
    "surface_irrigationmethod": [
        "pgtrigger_insert_insert_2d181",
        "pgtrigger_before_update_update_4002a",
        "pgtrigger_update_update_67c5f",
        "pgtrigger_delete_delete_1192b",
    ],
    "surface_parcelirrigationmethod": [
        "pgtrigger_insert_insert_a16f6",
        "pgtrigger_before_update_update_799a0",
        "pgtrigger_update_update_7e0a3",
        "pgtrigger_delete_delete_21b22",
    ],
}

MODELS = [
    "IrrigationMethod",
    "ParcelIrrigationMethod",
    "IrrigationMethodEvent",
    "ParcelIrrigationMethodEvent",
]

# Copied from surface/migrations/0016_seed_irrigation_methods.py, which copied
# them off East Turlock Subbasin GSA, Rules and Regulations Phase 2 Final,
# 2025-08-28, Section 4.05, the table on printed pages 20-21 (18 rows, counted
# off the PDF on 2026-09-23).
SOURCE = (
    "East Turlock Subbasin GSA, Rules and Regulations Phase 2 Final "
    "(2025-08-28), §4.05, citing Zaccaria 2018, ANR 8570"
)

# (name as printed, range low %, range high %, assigned %)
EAST_TURLOCK_4_05 = [
    ("LEPA", 80, 90, 88),
    ("Linear Move", 75, 85, 83),
    ("Center Pivot", 75, 90, 87),
    ("Traveling Gun", 65, 75, 73),
    ("Side-Roll", 65, 85, 80),
    ("Hand-Move", 65, 85, 80),
    ("Solid-Set", 70, 85, 82),
    ("Furrow (Conventional)", 45, 65, 60),
    ("Furrow (Surge)", 55, 75, 70),
    ("Furrow (with Tailwater Reuse)", 60, 80, 75),
    ("Basin", 60, 75, 72),
    ("Precision Level Basin", 65, 80, 77),
    ("Bubbler (Low Head)", 80, 90, 88),
    ("Microspray", 85, 90, 90),
    ("Micropoint Source", 85, 90, 90),
    ("Microline Source", 85, 90, 90),
    ("Surface Drip", 85, 95, 93),
    ("Subsurface Drip", 90, 95, 95),
]


def _tables(schema_editor):
    with schema_editor.connection.cursor() as cursor:
        return set(schema_editor.connection.introspection.table_names(cursor))


def adopt_surface_tables(apps, schema_editor):
    """Rename `surface`'s four tables to `parcels`' names, where they exist."""
    tables = _tables(schema_editor)
    if "surface_irrigationmethod" not in tables:
        return
    quote = schema_editor.quote_name
    for table, names in OLD_TRIGGERS.items():
        for name in names:
            schema_editor.execute(f"DROP TRIGGER IF EXISTS {quote(name)} ON {quote(table)}")
            schema_editor.execute(f"DROP FUNCTION IF EXISTS {quote(name)}()")
    for old, new in RENAMES:
        schema_editor.execute(f"ALTER TABLE {quote(old)} RENAME TO {quote(new)}")
        schema_editor.execute(
            f"ALTER SEQUENCE IF EXISTS {quote(old + '_id_seq')} "
            f"RENAME TO {quote(new + '_id_seq')}"
        )
        schema_editor.execute(
            f"ALTER SEQUENCE IF EXISTS {quote(old + '_pgh_id_seq')} "
            f"RENAME TO {quote(new + '_pgh_id_seq')}"
        )


def create_absent_tables(apps, schema_editor):
    """Create the four tables on a deployment that never had them."""
    tables = _tables(schema_editor)
    for name in MODELS:
        model = apps.get_model("parcels", name)
        if model._meta.db_table not in tables:
            schema_editor.create_model(model)


def _fraction(percent):
    return (Decimal(percent) / 100).quantize(Decimal("0.001"))


def seed(apps, schema_editor):
    """Write the 18 rows into an empty table; leave an adopted one alone."""
    IrrigationMethod = apps.get_model("parcels", "IrrigationMethod")
    if IrrigationMethod.objects.exists():
        return
    for position, (name, low, high, assigned) in enumerate(EAST_TURLOCK_4_05, start=1):
        IrrigationMethod.objects.create(
            name=name,
            assigned_efficiency=_fraction(assigned),
            range_low=_fraction(low),
            range_high=_fraction(high),
            source=SOURCE,
            sort_order=position * 10,
        )


class Migration(migrations.Migration):
    """Irreversible: undoing it would need `surface` installed to take the
    tables back, which this migration may not assume."""

    dependencies = [
        ('parcels', '0012_parcelledger_etaw_words'),
        ('pghistory', '0007_auto_20250421_0444'),
    ]

    operations = [
        migrations.RunPython(adopt_surface_tables),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='IrrigationMethod',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('name', models.CharField(max_length=100, unique=True)),
                        ('assigned_efficiency', models.DecimalField(decimal_places=3, help_text='The share of applied water the table assigns this method, as a fraction (0.600 is 60%).', max_digits=4)),
                        ('range_low', models.DecimalField(decimal_places=3, help_text="Low end of the table's published range, as a fraction.", max_digits=4)),
                        ('range_high', models.DecimalField(decimal_places=3, help_text="High end of the table's published range, as a fraction.", max_digits=4)),
                        ('source', models.CharField(help_text='The published table this row is copied from.', max_length=300)),
                        ('sort_order', models.PositiveIntegerField(default=0)),
                    ],
                    options={
                        'ordering': ['sort_order', 'name'],
                    },
                ),
                migrations.CreateModel(
                    name='IrrigationMethodEvent',
                    fields=[
                        ('pgh_id', models.AutoField(primary_key=True, serialize=False)),
                        ('pgh_created_at', models.DateTimeField(auto_now_add=True)),
                        ('pgh_label', models.TextField(help_text='The event label.')),
                        ('id', models.BigIntegerField()),
                        ('name', models.CharField(max_length=100)),
                        ('assigned_efficiency', models.DecimalField(decimal_places=3, help_text='The share of applied water the table assigns this method, as a fraction (0.600 is 60%).', max_digits=4)),
                        ('range_low', models.DecimalField(decimal_places=3, help_text="Low end of the table's published range, as a fraction.", max_digits=4)),
                        ('range_high', models.DecimalField(decimal_places=3, help_text="High end of the table's published range, as a fraction.", max_digits=4)),
                        ('source', models.CharField(help_text='The published table this row is copied from.', max_length=300)),
                        ('sort_order', models.PositiveIntegerField(default=0)),
                    ],
                    options={
                        'abstract': False,
                    },
                ),
                migrations.CreateModel(
                    name='ParcelIrrigationMethod',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                    ],
                ),
                migrations.CreateModel(
                    name='ParcelIrrigationMethodEvent',
                    fields=[
                        ('pgh_id', models.AutoField(primary_key=True, serialize=False)),
                        ('pgh_created_at', models.DateTimeField(auto_now_add=True)),
                        ('pgh_label', models.TextField(help_text='The event label.')),
                        ('parcel', models.BigIntegerField(blank=True, db_column='parcel_id', null=True, verbose_name='parcel')),
                        ('method', models.BigIntegerField(blank=True, db_column='method_id', null=True, verbose_name='method')),
                        ('id', models.BigIntegerField()),
                    ],
                    options={
                        'abstract': False,
                    },
                ),
                migrations.AddField(
                    model_name='irrigationmethodevent',
                    name='pgh_context',
                    field=models.ForeignKey(db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='pghistory.context'),
                ),
                migrations.AddField(
                    model_name='irrigationmethodevent',
                    name='pgh_obj',
                    field=models.ForeignKey(db_constraint=False, on_delete=django.db.models.deletion.DO_NOTHING, related_name='events', to='parcels.irrigationmethod'),
                ),
                migrations.AddField(
                    model_name='parcelirrigationmethod',
                    name='method',
                    field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='use_areas', to='parcels.irrigationmethod'),
                ),
                migrations.AddField(
                    model_name='parcelirrigationmethod',
                    name='parcel',
                    field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='irrigation', to='parcels.parcel'),
                ),
                migrations.AddField(
                    model_name='parcelirrigationmethodevent',
                    name='pgh_context',
                    field=models.ForeignKey(db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='pghistory.context'),
                ),
                migrations.AddField(
                    model_name='parcelirrigationmethodevent',
                    name='pgh_obj',
                    field=models.ForeignKey(db_constraint=False, on_delete=django.db.models.deletion.DO_NOTHING, related_name='events', to='parcels.parcelirrigationmethod'),
                ),
            ],
        ),
        migrations.RunPython(create_absent_tables),
        migrations.RunPython(seed),
        pgtrigger.migrations.AddTrigger(
            model_name='irrigationmethod',
            trigger=pgtrigger.compiler.Trigger(name='insert_insert', sql=pgtrigger.compiler.UpsertTriggerSql(func='INSERT INTO "parcels_irrigationmethodevent" ("assigned_efficiency", "id", "name", "pgh_context_id", "pgh_created_at", "pgh_label", "pgh_obj_id", "range_high", "range_low", "sort_order", "source") VALUES (NEW."assigned_efficiency", NEW."id", NEW."name", _pgh_attach_context(), NOW(), \'insert\', NEW."id", NEW."range_high", NEW."range_low", NEW."sort_order", NEW."source"); RETURN NULL;', hash='fd17ceb642d20b88de6f29e7f9e02d67d7b894fb', operation='INSERT', pgid='pgtrigger_insert_insert_582c4', table='parcels_irrigationmethod', when='AFTER')),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name='irrigationmethod',
            trigger=pgtrigger.compiler.Trigger(name='before_update_update', sql=pgtrigger.compiler.UpsertTriggerSql(condition='WHEN (OLD.* IS DISTINCT FROM NEW.*)', func='INSERT INTO "parcels_irrigationmethodevent" ("assigned_efficiency", "id", "name", "pgh_context_id", "pgh_created_at", "pgh_label", "pgh_obj_id", "range_high", "range_low", "sort_order", "source") VALUES (OLD."assigned_efficiency", OLD."id", OLD."name", _pgh_attach_context(), NOW(), \'before_update\', OLD."id", OLD."range_high", OLD."range_low", OLD."sort_order", OLD."source"); RETURN NULL;', hash='f272acb7a2d022dfa19f6ee18588c6909ee05541', operation='UPDATE', pgid='pgtrigger_before_update_update_22061', table='parcels_irrigationmethod', when='AFTER')),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name='irrigationmethod',
            trigger=pgtrigger.compiler.Trigger(name='update_update', sql=pgtrigger.compiler.UpsertTriggerSql(condition='WHEN (OLD.* IS DISTINCT FROM NEW.*)', func='INSERT INTO "parcels_irrigationmethodevent" ("assigned_efficiency", "id", "name", "pgh_context_id", "pgh_created_at", "pgh_label", "pgh_obj_id", "range_high", "range_low", "sort_order", "source") VALUES (NEW."assigned_efficiency", NEW."id", NEW."name", _pgh_attach_context(), NOW(), \'update\', NEW."id", NEW."range_high", NEW."range_low", NEW."sort_order", NEW."source"); RETURN NULL;', hash='b9b2c84d9c7274269a46fb09e2956773720be925', operation='UPDATE', pgid='pgtrigger_update_update_70d56', table='parcels_irrigationmethod', when='AFTER')),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name='irrigationmethod',
            trigger=pgtrigger.compiler.Trigger(name='delete_delete', sql=pgtrigger.compiler.UpsertTriggerSql(func='INSERT INTO "parcels_irrigationmethodevent" ("assigned_efficiency", "id", "name", "pgh_context_id", "pgh_created_at", "pgh_label", "pgh_obj_id", "range_high", "range_low", "sort_order", "source") VALUES (OLD."assigned_efficiency", OLD."id", OLD."name", _pgh_attach_context(), NOW(), \'delete\', OLD."id", OLD."range_high", OLD."range_low", OLD."sort_order", OLD."source"); RETURN NULL;', hash='8027ed411745d3c64be01878543d05cf539c755d', operation='DELETE', pgid='pgtrigger_delete_delete_d8703', table='parcels_irrigationmethod', when='AFTER')),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name='parcelirrigationmethod',
            trigger=pgtrigger.compiler.Trigger(name='insert_insert', sql=pgtrigger.compiler.UpsertTriggerSql(func='INSERT INTO "parcels_parcelirrigationmethodevent" ("id", "method_id", "parcel_id", "pgh_context_id", "pgh_created_at", "pgh_label", "pgh_obj_id") VALUES (NEW."id", NEW."method_id", NEW."parcel_id", _pgh_attach_context(), NOW(), \'insert\', NEW."id"); RETURN NULL;', hash='e5b724c0b5fca6f2fc9df93090ffadd2dbd475e1', operation='INSERT', pgid='pgtrigger_insert_insert_1e6d9', table='parcels_parcelirrigationmethod', when='AFTER')),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name='parcelirrigationmethod',
            trigger=pgtrigger.compiler.Trigger(name='before_update_update', sql=pgtrigger.compiler.UpsertTriggerSql(condition='WHEN (OLD.* IS DISTINCT FROM NEW.*)', func='INSERT INTO "parcels_parcelirrigationmethodevent" ("id", "method_id", "parcel_id", "pgh_context_id", "pgh_created_at", "pgh_label", "pgh_obj_id") VALUES (OLD."id", OLD."method_id", OLD."parcel_id", _pgh_attach_context(), NOW(), \'before_update\', OLD."id"); RETURN NULL;', hash='9cc8a68b3fb03d84f5221013043c645b138cc16d', operation='UPDATE', pgid='pgtrigger_before_update_update_22586', table='parcels_parcelirrigationmethod', when='AFTER')),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name='parcelirrigationmethod',
            trigger=pgtrigger.compiler.Trigger(name='update_update', sql=pgtrigger.compiler.UpsertTriggerSql(condition='WHEN (OLD.* IS DISTINCT FROM NEW.*)', func='INSERT INTO "parcels_parcelirrigationmethodevent" ("id", "method_id", "parcel_id", "pgh_context_id", "pgh_created_at", "pgh_label", "pgh_obj_id") VALUES (NEW."id", NEW."method_id", NEW."parcel_id", _pgh_attach_context(), NOW(), \'update\', NEW."id"); RETURN NULL;', hash='bf304cfef1fa773a176a5f83b0916951cbce4a7f', operation='UPDATE', pgid='pgtrigger_update_update_c32a6', table='parcels_parcelirrigationmethod', when='AFTER')),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name='parcelirrigationmethod',
            trigger=pgtrigger.compiler.Trigger(name='delete_delete', sql=pgtrigger.compiler.UpsertTriggerSql(func='INSERT INTO "parcels_parcelirrigationmethodevent" ("id", "method_id", "parcel_id", "pgh_context_id", "pgh_created_at", "pgh_label", "pgh_obj_id") VALUES (OLD."id", OLD."method_id", OLD."parcel_id", _pgh_attach_context(), NOW(), \'delete\', OLD."id"); RETURN NULL;', hash='281d486ce82654b9870431bc1a00c32034aa922b', operation='DELETE', pgid='pgtrigger_delete_delete_cd04a', table='parcels_parcelirrigationmethod', when='AFTER')),
        ),
    ]
