# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dormant role tables are gone, and no help text on a form cites a memo.

Two things are checked here:

- ``core.Role``, ``core.UserRole`` and the ``seed_roles`` command no longer
  exist: not in the app registry, not in the admin, not in the command list,
  not in the seed lists, not in the demonstration's table lists, and the two
  tables are not in the database.
- A help text on a core model field (shown on a form) cites no memo.
"""

import pytest
from django.apps import apps
from django.contrib import admin
from django.core.management import CommandError, call_command, get_commands
from django.db import connection

from core import demonstration
from core.management.commands import seed_data
from core.modules import MODULE_REGISTRY


@pytest.mark.parametrize("name", ["Role", "UserRole"])
def test_the_role_models_are_not_registered(name):
    with pytest.raises(LookupError):
        apps.get_model("core", name)


def test_the_role_models_are_not_in_the_admin():
    registered = {model.__name__ for model in admin.site._registry}
    assert not registered & {"Role", "UserRole"}


def test_the_role_tables_are_not_in_the_database():
    tables = set(connection.introspection.table_names())
    assert not tables & {"core_role", "core_userrole"}


def test_seed_roles_is_not_a_command():
    assert "seed_roles" not in get_commands()
    with pytest.raises(CommandError):
        call_command("seed_roles")


def test_no_seed_list_names_seed_roles():
    assert "seed_roles" not in seed_data.SEED_COMMANDS
    assert "seed_roles" not in seed_data.OPTIONAL_SEED_COMMANDS
    for name, spec in MODULE_REGISTRY.items():
        assert "seed_roles" not in spec.seed_commands, name


def test_the_demonstration_lists_name_no_role_table():
    named = (
        demonstration.CONTENT_LABELS
        + demonstration.REFERENCE_LABELS
        + demonstration.KEPT_LABELS
    )
    assert not {"core.Role", "core.UserRole"} & set(named)
    for label in named:
        apps.get_model(label)  # every listed table still exists


def test_no_core_help_text_cites_a_memo():
    cited = []
    for model in apps.get_app_config("core").get_models():
        for field in model._meta.get_fields():
            text = str(getattr(field, "help_text", "") or "")
            if "memo" in text.lower():
                cited.append(f"{model.__name__}.{field.name}: {text}")
    assert cited == []
