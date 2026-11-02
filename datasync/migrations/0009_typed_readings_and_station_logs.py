# SPDX-License-Identifier: AGPL-3.0-or-later
"""A station on a sync log, and the record of a reading typed by hand.

`DataSyncLog.station` is set when a run fetched one station only (the station
page's Fetch readings now button). `TypedReading` is the change-tracked record
of each reading a person types at a station entered by hand, with its
trigger-written history table.
"""

import django.db.models.deletion
import django.utils.timezone
import pgtrigger.compiler
import pgtrigger.migrations
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('datasync', '0008_datarecordstaging_statistic'),
        ('pghistory', '0007_auto_20250421_0444'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='datasynclog',
            name='station',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sync_logs', to='datasync.monitoredstation'),
        ),
        migrations.CreateModel(
            name='TypedReading',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('typed_by_email', models.CharField(blank=True, max_length=254, verbose_name='typed by (email)')),
                ('typed_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='typed at')),
                ('parameter_code', models.CharField(max_length=50, verbose_name='parameter')),
                ('observation_date', models.DateField(verbose_name='reading date')),
                ('value', models.DecimalField(decimal_places=4, max_digits=14, verbose_name='value')),
                ('notes', models.TextField(blank=True, verbose_name='notes')),
                ('reading', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='typed_record', to='datasync.datarecordstaging', verbose_name='station reading')),
                ('station', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='typed_readings', to='datasync.monitoredstation', verbose_name='monitoring station')),
                ('typed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='typed by')),
            ],
            options={
                'ordering': ['-typed_at'],
            },
        ),
        migrations.CreateModel(
            name='TypedReadingEvent',
            fields=[
                ('pgh_id', models.AutoField(primary_key=True, serialize=False)),
                ('pgh_created_at', models.DateTimeField(auto_now_add=True)),
                ('pgh_label', models.TextField(help_text='The event label.')),
                ('station', models.BigIntegerField(blank=True, db_column='station_id', null=True, verbose_name='monitoring station')),
                ('reading', models.BigIntegerField(blank=True, db_column='reading_id', null=True, verbose_name='station reading')),
                ('typed_by', models.BigIntegerField(blank=True, db_column='typed_by_id', null=True, verbose_name='typed by')),
                ('id', models.BigIntegerField()),
                ('typed_by_email', models.CharField(blank=True, max_length=254, verbose_name='typed by (email)')),
                ('typed_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='typed at')),
                ('parameter_code', models.CharField(max_length=50, verbose_name='parameter')),
                ('observation_date', models.DateField(verbose_name='reading date')),
                ('value', models.DecimalField(decimal_places=4, max_digits=14, verbose_name='value')),
                ('notes', models.TextField(blank=True, verbose_name='notes')),
                ('pgh_context', models.ForeignKey(db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='pghistory.context')),
                ('pgh_obj', models.ForeignKey(db_constraint=False, on_delete=django.db.models.deletion.DO_NOTHING, related_name='events', to='datasync.typedreading')),
            ],
            options={
                'abstract': False,
            },
        ),
        pgtrigger.migrations.AddTrigger(
            model_name='typedreading',
            trigger=pgtrigger.compiler.Trigger(name='insert_insert', sql=pgtrigger.compiler.UpsertTriggerSql(func='INSERT INTO "datasync_typedreadingevent" ("id", "notes", "observation_date", "parameter_code", "pgh_context_id", "pgh_created_at", "pgh_label", "pgh_obj_id", "reading_id", "station_id", "typed_at", "typed_by_email", "typed_by_id", "value") VALUES (NEW."id", NEW."notes", NEW."observation_date", NEW."parameter_code", _pgh_attach_context(), NOW(), \'insert\', NEW."id", NEW."reading_id", NEW."station_id", NEW."typed_at", NEW."typed_by_email", NEW."typed_by_id", NEW."value"); RETURN NULL;', hash='78602e6f57fecb96aa8d992aaeed90672c3902a0', operation='INSERT', pgid='pgtrigger_insert_insert_f86b8', table='datasync_typedreading', when='AFTER')),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name='typedreading',
            trigger=pgtrigger.compiler.Trigger(name='before_update_update', sql=pgtrigger.compiler.UpsertTriggerSql(condition='WHEN (OLD.* IS DISTINCT FROM NEW.*)', func='INSERT INTO "datasync_typedreadingevent" ("id", "notes", "observation_date", "parameter_code", "pgh_context_id", "pgh_created_at", "pgh_label", "pgh_obj_id", "reading_id", "station_id", "typed_at", "typed_by_email", "typed_by_id", "value") VALUES (OLD."id", OLD."notes", OLD."observation_date", OLD."parameter_code", _pgh_attach_context(), NOW(), \'before_update\', OLD."id", OLD."reading_id", OLD."station_id", OLD."typed_at", OLD."typed_by_email", OLD."typed_by_id", OLD."value"); RETURN NULL;', hash='44e9242b5655e49ab36370cb17701607f952022d', operation='UPDATE', pgid='pgtrigger_before_update_update_683a0', table='datasync_typedreading', when='AFTER')),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name='typedreading',
            trigger=pgtrigger.compiler.Trigger(name='update_update', sql=pgtrigger.compiler.UpsertTriggerSql(condition='WHEN (OLD.* IS DISTINCT FROM NEW.*)', func='INSERT INTO "datasync_typedreadingevent" ("id", "notes", "observation_date", "parameter_code", "pgh_context_id", "pgh_created_at", "pgh_label", "pgh_obj_id", "reading_id", "station_id", "typed_at", "typed_by_email", "typed_by_id", "value") VALUES (NEW."id", NEW."notes", NEW."observation_date", NEW."parameter_code", _pgh_attach_context(), NOW(), \'update\', NEW."id", NEW."reading_id", NEW."station_id", NEW."typed_at", NEW."typed_by_email", NEW."typed_by_id", NEW."value"); RETURN NULL;', hash='40f72d9db285899b2fe0a9f07726866a22b5da48', operation='UPDATE', pgid='pgtrigger_update_update_c56c8', table='datasync_typedreading', when='AFTER')),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name='typedreading',
            trigger=pgtrigger.compiler.Trigger(name='delete_delete', sql=pgtrigger.compiler.UpsertTriggerSql(func='INSERT INTO "datasync_typedreadingevent" ("id", "notes", "observation_date", "parameter_code", "pgh_context_id", "pgh_created_at", "pgh_label", "pgh_obj_id", "reading_id", "station_id", "typed_at", "typed_by_email", "typed_by_id", "value") VALUES (OLD."id", OLD."notes", OLD."observation_date", OLD."parameter_code", _pgh_attach_context(), NOW(), \'delete\', OLD."id", OLD."reading_id", OLD."station_id", OLD."typed_at", OLD."typed_by_email", OLD."typed_by_id", OLD."value"); RETURN NULL;', hash='1af68d3333f7a011f23c5f21368261ac7ed21d06', operation='DELETE', pgid='pgtrigger_delete_delete_59673', table='datasync_typedreading', when='AFTER')),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name='typedreadingevent',
            trigger=pgtrigger.compiler.Trigger(name='append_only', sql=pgtrigger.compiler.UpsertTriggerSql(func="RAISE EXCEPTION 'pgtrigger: Cannot update or delete rows from % table', TG_TABLE_NAME;", hash='095d7a0263bf3def4a2f72cbfd7e981dc47b6d08', operation='UPDATE OR DELETE', pgid='pgtrigger_append_only_d0c66', table='datasync_typedreadingevent', when='BEFORE')),
        ),
    ]
