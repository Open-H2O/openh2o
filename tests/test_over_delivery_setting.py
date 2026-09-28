# SPDX-License-Identifier: AGPL-3.0-or-later
"""148-04 Task 1: the over-delivery treatment setting on Delivery Settings.

Three values Brent ruled (Q1, 2026-09-20): not credited (the default, today's
behaviour), credited to the landowner less a share left in the basin, or shown
as its own named line that is not a credit. ``over_delivery_treatment`` and
``over_delivery_leave_behind`` belong to ``surface`` exactly as
``default_irrigation_efficiency`` does (``core/forms.py::DeliverySettingsForm``)
-- only canal water can be over-delivered.

Follows ``tests/test_delivery_settings_surface_fields.py`` and
``tests/test_groundwater_extraction.py`` for how the form/view, module gating
and change-history mapping are tested. Every assertion here is an exact value,
never a direction and never a re-derivation of the percent-to-fraction
conversion under test.

**Ordering note.** ``config/urls.py`` composes its module-owned routes from
``OPENH2O_MODULES`` in a list comprehension that runs once, the first time
Django imports the URLconf -- which happens lazily, on the first URL
resolution of the whole test session, not at process start. If that first
resolution happens to fall inside an ``override_settings(OPENH2O_MODULES=...)``
block with a module dropped, the reduced route set is what gets imported and
cached for the rest of the session (``sys.modules`` never re-imports it), and
every later request needing that module's namespace fails with
``NoReverseMatch`` even outside the override. The tests below are ordered so a
plain request (full module set) runs before any ``override_settings`` test
touches the client, which keeps this file safe to run first or alone; the
underlying landmine is pre-existing app behaviour, out of this task's scope.
"""
from decimal import Decimal

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client, override_settings
from django.urls import reverse

from core.forms import DeliverySettingsForm
from core.history import LABEL_BEFORE_UPDATE
from core.models import SiteConfig
from core.modules import ALL_MODULE_NAMES

pytestmark = pytest.mark.django_db

#: `recharge` requires `surface` (core/modules.py), so dropping `surface`
#: alone is an invalid configuration -- both go, same closure
#: `tests/test_delivery_settings_surface_fields.py::_WITHOUT_SURFACE` uses.
_WITHOUT_SURFACE = tuple(n for n in ALL_MODULE_NAMES if n not in ("surface", "recharge"))


class _StaffUserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"overdeliveryadmin{n}")
    email = factory.Sequence(lambda n: f"overdeliveryadmin{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True
    is_staff = True


@pytest.fixture
def admin_client(db):
    c = Client()
    c.force_login(_StaffUserFactory())
    return c


_BASE_POST = {
    # Every field DeliverySettingsForm requires on a `surface` + `wells`
    # deployment, so these POSTs are valid apart from what each test varies.
    "efficiency_percent": "75",
    "groundwater_efficiency_percent": "80",
    "recovery_horizon": "carry_forward",
    "diversion_report_year_rule": "water_year",
}


# ---------------------------------------------------------------------------
# 1. Defaults
# ---------------------------------------------------------------------------


def test_defaults_are_not_credited_and_ten_percent():
    config = SiteConfig(agency_name="Agency")
    assert config.over_delivery_treatment == "not_credited"
    assert config.over_delivery_leave_behind == Decimal("0.100")


# ---------------------------------------------------------------------------
# 2. Validation: "credited" requires the percent
#
# Deliberately the first test in this file that renders a page through the
# client, and it does so with the full module set (no override_settings) --
# see the ordering note in the module docstring.
# ---------------------------------------------------------------------------


def test_credited_without_a_percent_is_a_form_error(admin_client):
    config, _ = SiteConfig.objects.get_or_create(defaults={"agency_name": "Agency"})
    resp = admin_client.post(
        reverse("accounting:delivery_settings"),
        {**_BASE_POST, "over_delivery_treatment": "credited"},
    )
    # Invalid form: re-renders the page (200), never redirects.
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Enter the share left in the basin" in body
    config.refresh_from_db()
    assert config.over_delivery_treatment == "not_credited"
    assert config.over_delivery_leave_behind == Decimal("0.100")


# ---------------------------------------------------------------------------
# 3. 90 -> Decimal("0.900") stored
# ---------------------------------------------------------------------------


def test_ninety_percent_credited_is_stored_as_point_nine(admin_client):
    config, _ = SiteConfig.objects.get_or_create(defaults={"agency_name": "Agency"})
    resp = admin_client.post(
        reverse("accounting:delivery_settings"),
        {
            **_BASE_POST,
            "over_delivery_treatment": "credited",
            "over_delivery_leave_behind_percent": "90",
        },
    )
    assert resp.status_code == 302
    config.refresh_from_db()
    assert config.over_delivery_treatment == "credited"
    assert config.over_delivery_leave_behind == Decimal("0.900")


def test_named_line_does_not_require_or_store_a_percent(admin_client):
    config, _ = SiteConfig.objects.get_or_create(defaults={"agency_name": "Agency"})
    SiteConfig.objects.filter(pk=config.pk).update(
        over_delivery_leave_behind=Decimal("0.250")
    )
    resp = admin_client.post(
        reverse("accounting:delivery_settings"),
        {**_BASE_POST, "over_delivery_treatment": "named_line"},
    )
    assert resp.status_code == 302
    config.refresh_from_db()
    assert config.over_delivery_treatment == "named_line"
    # Not "credited", so the stored leave-behind share is left alone.
    assert config.over_delivery_leave_behind == Decimal("0.250")


# ---------------------------------------------------------------------------
# 4. Change history: the save writes an event carrying the new value
# ---------------------------------------------------------------------------


def test_save_writes_a_site_config_event_carrying_the_new_value(admin_client):
    config, _ = SiteConfig.objects.get_or_create(defaults={"agency_name": "Agency"})
    SiteConfig.objects.filter(pk=config.pk).update(
        over_delivery_treatment="not_credited",
        over_delivery_leave_behind=Decimal("0.100"),
    )

    resp = admin_client.post(
        reverse("accounting:delivery_settings"),
        {
            **_BASE_POST,
            "over_delivery_treatment": "credited",
            "over_delivery_leave_behind_percent": "90",
            "note": "Board-approved over-delivery policy",
        },
    )
    assert resp.status_code == 302

    events = config.events.filter(pgh_context__isnull=False)
    before = events.get(pgh_label=LABEL_BEFORE_UPDATE)
    after = events.get(pgh_label="update")
    assert before.over_delivery_treatment == "not_credited"
    assert str(before.over_delivery_leave_behind) == "0.100"
    assert after.over_delivery_treatment == "credited"
    assert str(after.over_delivery_leave_behind) == "0.900"
    assert after.pgh_context.metadata["note"] == "Board-approved over-delivery policy"


# ---------------------------------------------------------------------------
# 5. Module gating: hidden and untouched with `surface` off
# ---------------------------------------------------------------------------


@override_settings(OPENH2O_MODULES=_WITHOUT_SURFACE)
def test_fields_absent_when_surface_is_disabled(admin_client):
    resp = admin_client.get(reverse("accounting:delivery_settings"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Canal water beyond what the crop could use" not in body
    assert 'name="over_delivery_treatment"' not in body
    assert 'name="over_delivery_leave_behind_percent"' not in body


@override_settings(OPENH2O_MODULES=_WITHOUT_SURFACE)
def test_saving_with_surface_disabled_leaves_stored_values_untouched(admin_client):
    config, _ = SiteConfig.objects.get_or_create(defaults={"agency_name": "Agency"})
    assert config.over_delivery_treatment == "not_credited"
    assert config.over_delivery_leave_behind == Decimal("0.100")

    # `_WITHOUT_SURFACE` drops `surface` (and `recharge`) but leaves `wells`
    # on, so only the surface-gated fields are absent from this POST.
    resp = admin_client.post(
        reverse("accounting:delivery_settings"),
        {
            "recovery_horizon": "same_water_year",
            "groundwater_efficiency_percent": "80",
        },
    )
    assert resp.status_code == 302
    config.refresh_from_db()
    assert config.over_delivery_treatment == "not_credited"
    assert config.over_delivery_leave_behind == Decimal("0.100")


def test_form_hides_both_fields_with_surface_off_directly():
    with override_settings(OPENH2O_MODULES=_WITHOUT_SURFACE):
        form = DeliverySettingsForm(instance=SiteConfig.objects.first() or SiteConfig())
    assert "over_delivery_treatment" not in form.fields
    assert "over_delivery_leave_behind_percent" not in form.fields


# ---------------------------------------------------------------------------
# 6. The change record maps both fields to `surface`
# ---------------------------------------------------------------------------


def test_change_history_maps_over_delivery_fields_to_surface():
    from core.changes import FIELD_MODULES

    assert FIELD_MODULES["core.SiteConfig.over_delivery_treatment"] == "surface"
    assert FIELD_MODULES["core.SiteConfig.over_delivery_leave_behind"] == "surface"


def test_change_history_shows_over_delivery_fields_when_surface_is_on():
    from core.changes import tracked_fields
    from core.models import SiteConfigEvent

    names = [f.name for f in tracked_fields(SiteConfigEvent)]
    assert "over_delivery_treatment" in names
    assert "over_delivery_leave_behind" in names


@override_settings(OPENH2O_MODULES=_WITHOUT_SURFACE)
def test_change_history_drops_over_delivery_fields_when_surface_is_off():
    from core.changes import tracked_fields
    from core.models import SiteConfigEvent

    names = [f.name for f in tracked_fields(SiteConfigEvent)]
    assert "over_delivery_treatment" not in names
    assert "over_delivery_leave_behind" not in names
