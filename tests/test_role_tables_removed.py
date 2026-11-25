# SPDX-License-Identifier: AGPL-3.0-or-later
"""A site upgraded past the removal of the role tables keeps no content type or permission for them.

Django creates content types after ``migrate`` for the models that exist, so a site installed after the
removal never has them; a site installed before it kept two content types and their eight permissions.
"""
import importlib

import pytest
from django.apps import apps
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

pytestmark = pytest.mark.django_db

MIGRATION = importlib.import_module("core.migrations.0033_remove_role_content_types")


def test_no_content_type_left_for_the_removed_role_tables():
    for model in ("role", "userrole"):
        kind = ContentType.objects.create(app_label="core", model=model)
        for action in ("add", "change", "delete", "view"):
            Permission.objects.create(content_type=kind, codename=f"{action}_{model}", name=f"Can {action} {model}")
    kept = ContentType.objects.get_for_model(apps.get_model("core", "User"))

    MIGRATION.forget_the_role_tables(apps, None)

    assert not ContentType.objects.filter(app_label="core", model__in=["role", "userrole"]).exists()
    assert not Permission.objects.filter(content_type__model__in=["role", "userrole"], content_type__app_label="core").exists()
    assert not Permission.objects.filter(codename__in=["view_role", "view_userrole"]).exists()
    assert ContentType.objects.filter(pk=kept.pk).exists()
