# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-03 Task 3: the two diversion-record settings on Delivery Settings.

``diversion_use_type_rule`` and ``diversion_report_year_rule`` belong to
``surface`` exactly as ``default_irrigation_efficiency`` does
(``core/forms.py::DeliverySettingsForm``) -- shown and saved only when
``surface`` is enabled. No existing test exercised the *content* of this
page under a reduced module set (only the subprocess crawl in
``tests/test_droppability_acceptance.py`` renders it at all, and only to
confirm 200 with an empty database); this file is the first to assert on
the fields themselves, in-process, the same ``is_enabled`` boolean the
subprocess harness ultimately reads.

``OPENH2O_MODULES`` composes ``INSTALLED_APPS`` at settings-IMPORT time
(``tests/test_droppability_acceptance.py``'s own docstring), so
``override_settings`` cannot actually uninstall ``surface`` mid-test-run --
routes stay registered and the table stays in the schema. What it CAN change
is what ``core.modules.is_enabled`` returns, since that resolver reads
``settings.OPENH2O_MODULES`` fresh on every call with no caching. That is
exactly the boolean ``DeliverySettingsForm.shows_diversion_settings`` (and
the template's ``{% if %}``) branch on, so overriding it proves the real
gating logic without the cost of a subprocess boot per test. Two doors
proven here, RED against the unfixed tree (quotes in 146-03-EVIDENCE.md):

  1. On a `surface`-enabled deployment, the two fields render under
     "Diversion records" and a POST saves them onto SiteConfig.
  2. On a deployment with `surface` (and its dependent, `recharge`) dropped,
     Delivery Settings renders with neither field, and the page's other
     setting (recovery horizon) still works.
"""
import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client, override_settings
from django.urls import reverse

from core.models import SiteConfig
from core.modules import ALL_MODULE_NAMES

pytestmark = pytest.mark.django_db

#: `recharge` is the one module that requires `surface` (core/modules.py) --
#: dropping `surface` alone is an invalid configuration
#: (`validate_module_names` raises), so both go, the same closure
#: `tests/test_droppability_acceptance.py::drop_closure('surface')` computes.
_WITHOUT_SURFACE = tuple(n for n in ALL_MODULE_NAMES if n not in ("surface", "recharge"))


class _StaffUserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"deliveryadmin{n}")
    email = factory.Sequence(lambda n: f"deliveryadmin{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True
    is_staff = True


@pytest.fixture
def admin_client(db):
    c = Client()
    c.force_login(_StaffUserFactory())
    return c


# ---------------------------------------------------------------------------
# 1. Surface enabled: the two fields render and save
# ---------------------------------------------------------------------------


def test_diversion_settings_render_when_surface_is_enabled(admin_client):
    resp = admin_client.get(reverse("accounting:delivery_settings"))
    body = resp.content.decode()
    assert "Diversion records" in body
    assert "USE row" in body
    assert "reporting year" in body


def test_diversion_settings_save_onto_site_config(admin_client):
    config, _ = SiteConfig.objects.get_or_create(defaults={"agency_name": "Agency"})
    resp = admin_client.post(
        reverse("accounting:delivery_settings"),
        {
            "efficiency_percent": "75",
            "recovery_horizon": "carry_forward",
            "diversion_use_type_rule": "returned",
            "diversion_report_year_rule": "season",
            "season_start_month": "3",
        },
    )
    assert resp.status_code == 302
    config.refresh_from_db()
    assert config.diversion_use_type_rule == "returned"
    assert config.diversion_report_year_rule == "season"
    assert config.season_start_month == 3


# ---------------------------------------------------------------------------
# 2. Surface (and recharge) dropped: neither field renders, the rest works
# ---------------------------------------------------------------------------


@override_settings(OPENH2O_MODULES=_WITHOUT_SURFACE)
def test_diversion_settings_absent_on_a_drinking_only_configuration(admin_client):
    resp = admin_client.get(reverse("accounting:delivery_settings"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Diversion records" not in body
    assert "USE row" not in body
    # The page's other setting is unaffected by surface being gone.
    assert "unused water" in body.lower() or "allotment" in body.lower()


@override_settings(OPENH2O_MODULES=_WITHOUT_SURFACE)
def test_saving_on_a_drinking_only_configuration_leaves_diversion_fields_untouched(
    admin_client,
):
    config, _ = SiteConfig.objects.get_or_create(defaults={"agency_name": "Agency"})
    assert config.diversion_use_type_rule == "drop"  # the model default

    resp = admin_client.post(
        reverse("accounting:delivery_settings"),
        {"recovery_horizon": "same_water_year"},
    )
    assert resp.status_code == 302
    config.refresh_from_db()
    assert config.default_recovery_horizon == "same_water_year"
    # Nobody was offered the diversion fields, so they stay at the default.
    assert config.diversion_use_type_rule == "drop"
    assert config.diversion_report_year_rule == "water_year"
