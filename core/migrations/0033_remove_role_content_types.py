# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forget the two role tables 0022 removed.

Django writes a content type, and four permissions on it, for each model after ``migrate``. A site
installed before 0022 kept the ones for ``Role`` and ``UserRole`` after the tables went, and the
administrator pages could list those permissions. A site installed later never had them.
"""
from django.db import migrations

REMOVED = ("role", "userrole")


def forget_the_role_tables(apps, schema_editor):
    content_type = apps.get_model("contenttypes", "ContentType")
    permission = apps.get_model("auth", "Permission")
    gone = content_type.objects.filter(app_label="core", model__in=REMOVED)
    permission.objects.filter(content_type__in=gone).delete()
    gone.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0032_pending_import_finalize_and_setup_steps"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(forget_the_role_tables, migrations.RunPython.noop),
    ]
