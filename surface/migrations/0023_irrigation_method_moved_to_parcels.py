# 150.2-01: the irrigation-method table and each use area's method now belong
# to `parcels` (parcels/0013_irrigation_method, which this depends on: `surface`
# requires `parcels`, so the edge points the allowed way). This removes the
# four models from `surface`'s state.
#
# The database side has two cases, told apart by introspection:
#   - parcels 0013 found `surface`'s tables and renamed them to `parcels_*`, so
#     there is nothing here to drop (every existing deployment).
#   - parcels 0013 ran first on a fresh install and built its own tables, and
#     `surface` 0015/0016/0018 then built a second copy holding only the seeded
#     method rows. That copy is dropped, with its history trigger functions.
#     A copy that holds any use area's method is NOT dropped: that would mean
#     someone recorded data in a table this migration believed was spare, and
#     it stops with the reason instead.
#
# Table and trigger names are copied in, never imported (a migration keeps
# meaning what it meant on the day it ran).

from django.db import migrations

# Tracked tables after their history tables, so nothing drops out from under
# a foreign key.
TABLES = [
    "surface_irrigationmethodevent",
    "surface_parcelirrigationmethodevent",
    "surface_parcelirrigationmethod",
    "surface_irrigationmethod",
]

# The history triggers `surface` 0018 installed; each function shares its
# trigger's name, and DROP TABLE leaves the functions behind.
OLD_TRIGGER_FUNCTIONS = [
    "pgtrigger_insert_insert_2d181",
    "pgtrigger_before_update_update_4002a",
    "pgtrigger_update_update_67c5f",
    "pgtrigger_delete_delete_1192b",
    "pgtrigger_insert_insert_a16f6",
    "pgtrigger_before_update_update_799a0",
    "pgtrigger_update_update_7e0a3",
    "pgtrigger_delete_delete_21b22",
]


def drop_spare_copy(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        tables = set(connection.introspection.table_names(cursor))
        if "surface_parcelirrigationmethod" in tables:
            cursor.execute('SELECT COUNT(*) FROM "surface_parcelirrigationmethod"')
            (assigned,) = cursor.fetchone()
            if assigned:
                raise RuntimeError(
                    f"surface_parcelirrigationmethod holds {assigned} use area "
                    "method(s) after parcels 0013 built its own table. Nothing "
                    "was dropped. Copy those rows into "
                    "parcels_parcelirrigationmethod, then run migrate again."
                )
    quote = schema_editor.quote_name
    for table in TABLES:
        if table in tables:
            schema_editor.execute(f"DROP TABLE {quote(table)} CASCADE")
    for name in OLD_TRIGGER_FUNCTIONS:
        schema_editor.execute(f"DROP FUNCTION IF EXISTS {quote(name)}()")


class Migration(migrations.Migration):
    """Irreversible, like parcels 0013 that it follows."""

    dependencies = [
        ('parcels', '0013_irrigation_method'),
        ('surface', '0022_field_labels_calwatrs_pin_max_rate'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name='irrigationmethodevent',
                    name='pgh_obj',
                ),
                migrations.RemoveField(
                    model_name='parcelirrigationmethod',
                    name='method',
                ),
                migrations.RemoveField(
                    model_name='irrigationmethodevent',
                    name='pgh_context',
                ),
                migrations.RemoveField(
                    model_name='parcelirrigationmethod',
                    name='parcel',
                ),
                migrations.RemoveField(
                    model_name='parcelirrigationmethodevent',
                    name='pgh_obj',
                ),
                migrations.RemoveField(
                    model_name='parcelirrigationmethodevent',
                    name='pgh_context',
                ),
                migrations.DeleteModel(
                    name='IrrigationMethod',
                ),
                migrations.DeleteModel(
                    name='IrrigationMethodEvent',
                ),
                migrations.DeleteModel(
                    name='ParcelIrrigationMethod',
                ),
                migrations.DeleteModel(
                    name='ParcelIrrigationMethodEvent',
                ),
            ],
            database_operations=[
                migrations.RunPython(drop_spare_copy),
            ],
        ),
    ]
