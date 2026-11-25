# SPDX-License-Identifier: AGPL-3.0-or-later
"""What `manage.py check` and verify_clean_install print carries no long dash.

The copy rules keep U+2014 out of every printed sentence; these two commands run
at install and still printed it.
"""
import ast
from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings

from core.checks import check_development_settings_in_use, check_site_identity_is_set

pytestmark = pytest.mark.django_db

DASH = "—"
REPO_ROOT = Path(__file__).resolve().parent.parent


def test_check_messages_carry_no_em_dash():
    from django.contrib.sites.models import Site

    from core.site_identity import PLACEHOLDER

    Site.objects.update_or_create(pk=settings.SITE_ID, defaults={"name": PLACEHOLDER, "domain": PLACEHOLDER})
    with override_settings(DEBUG=True):
        warnings = check_development_settings_in_use(None) + check_site_identity_is_set(None)
    assert len(warnings) == 2
    for warning in warnings:
        assert DASH not in warning.msg, warning.msg
        assert DASH not in (warning.hint or ""), warning.hint


def _printed_strings(path):
    """Every string constant in the module that is not a docstring."""
    tree = ast.parse(path.read_text())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
    ]


def test_verify_clean_install_prints_no_em_dash():
    path = REPO_ROOT / "core" / "management" / "commands" / "verify_clean_install.py"
    with_dash = [text for text in _printed_strings(path) if DASH in text]
    assert not with_dash, with_dash
