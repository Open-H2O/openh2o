# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-03 Task 3: the diversion-record setting on Delivery Settings.

``diversion_report_year_rule`` belongs to ``surface`` exactly as
``default_irrigation_efficiency`` does (``core/forms.py::DeliverySettingsForm``)
-- shown and saved only when ``surface`` is enabled. No existing test
exercised the *content* of this page under a reduced module set (only the
subprocess crawl in ``tests/test_droppability_acceptance.py`` renders it at
all, and only to confirm 200 with an empty database); this file is the
first to assert on the fields themselves, in-process, the same
``is_enabled`` boolean the subprocess harness ultimately reads.

**146-03 Task 6 (Brent's 2026-09-22 checkpoint ruling): the USE-row question
came off this page entirely.** It was a question about one uploaded file,
asked here months before any file exists, of a reader with no reason yet to
hold California's DIVERSION_TYPE vocabulary. ``diversion_use_type_rule``
stays on ``SiteConfig`` as the remembered answer, but the field is no
longer part of ``DeliverySettingsForm`` and this page no longer renders or
saves it (it moved to the import mapping step: ``tests/test_diversion_import.py``).

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
# 1. Surface enabled: the reporting-year field renders and saves; the
#    USE-row question is gone.
# ---------------------------------------------------------------------------


def test_diversion_settings_render_when_surface_is_enabled(admin_client):
    resp = admin_client.get(reverse("accounting:delivery_settings"))
    body = resp.content.decode()
    assert "Diversion records" in body
    assert "Which months does a reporting year cover?" in body
    assert "Used when a file gives a year and a month but no date." in body
    # 146-03 Task 6: the USE-row question moved to the import screen and no
    # longer renders here.
    assert "USE row" not in body


def test_diversion_use_type_rule_is_not_a_form_field(admin_client):
    from core.forms import DeliverySettingsForm

    form = DeliverySettingsForm(instance=SiteConfig.objects.first() or SiteConfig())
    assert "diversion_use_type_rule" not in form.fields
    # And nothing in the rendered page names the field by its POST name.
    resp = admin_client.get(reverse("accounting:delivery_settings"))
    assert "diversion_use_type_rule" not in resp.content.decode()


def test_diversion_settings_save_onto_site_config(admin_client):
    config, _ = SiteConfig.objects.get_or_create(defaults={"agency_name": "Agency"})
    resp = admin_client.post(
        reverse("accounting:delivery_settings"),
        {
            "efficiency_percent": "75",
            # 148-02 Task 4: `wells` is enabled by default here too, so this
            # POST needs groundwater_efficiency_percent the same way it needs
            # efficiency_percent.
            "groundwater_efficiency_percent": "80",
            "recovery_horizon": "carry_forward",
            "diversion_report_year_rule": "season",
            "season_start_month": "3",
        },
    )
    assert resp.status_code == 302
    config.refresh_from_db()
    assert config.diversion_report_year_rule == "season"
    assert config.season_start_month == 3


# ---------------------------------------------------------------------------
# 2. Surface (and recharge) dropped: the field doesn't render, the rest works
# ---------------------------------------------------------------------------


@override_settings(OPENH2O_MODULES=_WITHOUT_SURFACE)
def test_diversion_settings_absent_on_a_drinking_only_configuration(admin_client):
    resp = admin_client.get(reverse("accounting:delivery_settings"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Diversion records" not in body
    assert "Which months does a reporting year cover?" not in body
    # The page's other setting is unaffected by surface being gone.
    assert "unused water" in body.lower() or "allotment" in body.lower()


@override_settings(OPENH2O_MODULES=_WITHOUT_SURFACE)
def test_saving_on_a_drinking_only_configuration_leaves_diversion_fields_untouched(
    admin_client,
):
    config, _ = SiteConfig.objects.get_or_create(defaults={"agency_name": "Agency"})
    assert config.diversion_report_year_rule == "water_year"  # the model default

    resp = admin_client.post(
        reverse("accounting:delivery_settings"),
        # 148-02 Task 4: `_WITHOUT_SURFACE` drops surface (and recharge) but
        # leaves `wells` on, so groundwater_efficiency_percent is still a
        # required field on this POST even though efficiency_percent is not.
        {"recovery_horizon": "same_water_year", "groundwater_efficiency_percent": "80"},
    )
    assert resp.status_code == 302
    config.refresh_from_db()
    assert config.default_recovery_horizon == "same_water_year"
    # Nobody was offered the diversion fields, so they stay at the default.
    assert config.diversion_use_type_rule == "drop"
    assert config.diversion_report_year_rule == "water_year"
