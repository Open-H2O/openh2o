# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-05 Task 3 (Q8): the account's unit kind and delivery system.

Proven here, each RED against the unfixed tree (quotes in 146-05-EVIDENCE.md):

  1. The data migration (`accounting/migrations/0019_default_unit_kind_farm_unit.py`)
     sets every EXISTING account to `unit_kind="farm_unit"`, with the plan's own
     note carried in its docstring.
  2. Creating or editing an account without `unit_kind` is a form error.
  3. Setting both `delivery_well` and the point-of-diversion select is refused
     -- a form/model `clean()` rule, not a DB check constraint, because the
     two live in different tables (`accounting.WaterAccount` and
     `surface.WaterAccountDeliveryPoint`) and Postgres cannot check across
     them. `test_both_delivery_options_together_is_refused` is that proof.
  4. On the shape-1 module list (surface on, wells off) the account form
     shows the point-of-diversion select and not the well select; on shape 2
     (accounting off entirely) the routes do not exist at all -- that half is
     the existing `make test-droppable` subprocess harness's job (a disabled
     schema-resident module's routes are never registered at URLconf import
     time, which `override_settings` cannot rebuild mid-process; the same
     limit `tests/test_irrigation_method.py` and `tests/test_well_dwr_method.py`
     already document for `surface`/`wells`), not a case an in-process
     `override_settings` test can exercise here.
  5. The identity-card sentence: "A farm unit", "A place of use · delivered
     through <point>", or "A farm unit · delivered through <well>".

`delivery_well` is a real field on `WaterAccount` (`wells` is schema-resident,
so `core.modules.SCHEMA_EXCEPTIONS` excuses the arrow). `delivery_pod` is NOT
a model field -- `surface.WaterAccountDeliveryPoint` holds it instead, one row
per account, pointing `surface` -> `accounting` (a direction `surface.requires`
already declares), the same shape Task 1's `ParcelIrrigationMethod` uses for
the same reason (`core/modules.py` rule 1: `accounting` is schema-resident,
`surface` is truly removable).
"""
import importlib

import factory
import pytest
from django.apps import apps as live_apps
from django.contrib.auth.hashers import make_password
from django.test import Client, override_settings
from django.urls import reverse

from accounting.models import WaterAccount
from tests.factories import PointOfDiversionFactory, WaterAccountFactory, WellFactory

pytestmark = pytest.mark.django_db

#: The shape-1 module list (146-01's context block): use areas, accounts and
#: surface water, no wells at all.
_SHAPE_1 = (
    "core", "geography", "measurements", "standards", "parcels", "accounting",
    "surface", "reporting", "setup", "infrastructure", "health", "feedback",
)

_default_unit_kind = importlib.import_module(
    "accounting.migrations.0019_default_unit_kind_farm_unit"
)


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"unitkinduser{n}")
    email = factory.Sequence(lambda n: f"unitkinduser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client():
    c = Client()
    c.force_login(_UserFactory())
    return c


def _account_form_data(account, **overrides):
    data = {
        "account_number": account.account_number,
        "name": account.name,
        "status": account.status,
        "unit_kind": "",
        "delivery_well": "",
        "delivery_pod": "",
        "contact_name": "",
        "contact_email": "",
        "notes": "",
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# 1. The data migration: every existing account defaults to farm_unit
# ---------------------------------------------------------------------------


def test_the_migration_sets_every_existing_account_to_farm_unit():
    untouched = WaterAccountFactory(unit_kind=None)
    already_set = WaterAccountFactory(unit_kind="water_right")

    _default_unit_kind.set_unit_kind_farm_unit(live_apps, None)

    untouched.refresh_from_db()
    already_set.refresh_from_db()
    assert untouched.unit_kind == "farm_unit"
    assert already_set.unit_kind == "water_right"  # never overwritten


def test_the_reverse_clears_only_farm_unit_accounts():
    migrated = WaterAccountFactory(unit_kind=None)
    manually_set = WaterAccountFactory(unit_kind="farm_unit")
    other = WaterAccountFactory(unit_kind="place_of_use")
    _default_unit_kind.set_unit_kind_farm_unit(live_apps, None)

    _default_unit_kind.clear_unit_kind(live_apps, None)

    migrated.refresh_from_db()
    manually_set.refresh_from_db()
    other.refresh_from_db()
    assert migrated.unit_kind is None
    assert manually_set.unit_kind is None
    assert other.unit_kind == "place_of_use"


# ---------------------------------------------------------------------------
# 2. unit_kind is required on the form
# ---------------------------------------------------------------------------


def test_create_without_unit_kind_is_a_form_error(auth_client):
    resp = auth_client.post(
        reverse("accounting:account_create"),
        {
            "account_number": "ACCT-TEST-001",
            "name": "Test Account",
            "status": "active",
            "unit_kind": "",
            "contact_name": "",
            "contact_email": "",
            "notes": "",
        },
    )
    assert resp.status_code == 200
    assert not WaterAccount.objects.filter(account_number="ACCT-TEST-001").exists()


def test_create_with_unit_kind_saves(auth_client):
    resp = auth_client.post(
        reverse("accounting:account_create"),
        {
            "account_number": "ACCT-TEST-002",
            "name": "Test Account",
            "status": "active",
            "unit_kind": "place_of_use",
            "contact_name": "",
            "contact_email": "",
            "notes": "",
        },
    )
    assert resp.status_code == 302
    account = WaterAccount.objects.get(account_number="ACCT-TEST-002")
    assert account.unit_kind == "place_of_use"


def test_edit_without_unit_kind_is_a_form_error(auth_client):
    account = WaterAccountFactory(unit_kind="farm_unit")
    resp = auth_client.post(
        reverse("accounting:account_edit", args=[account.pk]),
        _account_form_data(account, unit_kind=""),
    )
    assert resp.status_code == 200
    account.refresh_from_db()
    assert account.unit_kind == "farm_unit"  # unchanged


def test_edit_changes_unit_kind(auth_client):
    account = WaterAccountFactory(unit_kind="farm_unit")
    resp = auth_client.post(
        reverse("accounting:account_edit", args=[account.pk]),
        _account_form_data(account, unit_kind="water_right"),
    )
    assert resp.status_code == 302
    account.refresh_from_db()
    assert account.unit_kind == "water_right"


# ---------------------------------------------------------------------------
# 3. Both delivery options at once is refused
# ---------------------------------------------------------------------------


def test_both_delivery_options_together_is_refused(auth_client):
    from surface.models import WaterAccountDeliveryPoint

    account = WaterAccountFactory(unit_kind="farm_unit")
    well = WellFactory()
    pod = PointOfDiversionFactory()

    resp = auth_client.post(
        reverse("accounting:account_edit", args=[account.pk]),
        _account_form_data(
            account,
            unit_kind="farm_unit",
            delivery_well=str(well.pk),
            delivery_pod=str(pod.pk),
        ),
    )

    assert resp.status_code == 200
    assert "not both" in resp.content.decode().lower()
    account.refresh_from_db()
    assert account.delivery_well is None
    assert not WaterAccountDeliveryPoint.objects.filter(account=account).exists()


def test_delivery_well_alone_saves(auth_client):
    account = WaterAccountFactory(unit_kind="farm_unit")
    well = WellFactory()

    resp = auth_client.post(
        reverse("accounting:account_edit", args=[account.pk]),
        _account_form_data(account, unit_kind="farm_unit", delivery_well=str(well.pk)),
    )

    assert resp.status_code == 302
    account.refresh_from_db()
    assert account.delivery_well == well


def test_delivery_pod_alone_saves():
    from surface.models import WaterAccountDeliveryPoint

    c = Client()
    c.force_login(_UserFactory())
    account = WaterAccountFactory(unit_kind="farm_unit")
    pod = PointOfDiversionFactory()

    resp = c.post(
        reverse("accounting:account_edit", args=[account.pk]),
        _account_form_data(account, unit_kind="farm_unit", delivery_pod=str(pod.pk)),
    )

    assert resp.status_code == 302
    link = WaterAccountDeliveryPoint.objects.get(account=account)
    assert link.point_of_diversion == pod


def test_delivery_pod_can_be_cleared():
    from surface.models import WaterAccountDeliveryPoint

    c = Client()
    c.force_login(_UserFactory())
    account = WaterAccountFactory(unit_kind="farm_unit")
    pod = PointOfDiversionFactory()
    c.post(
        reverse("accounting:account_edit", args=[account.pk]),
        _account_form_data(account, unit_kind="farm_unit", delivery_pod=str(pod.pk)),
    )
    assert WaterAccountDeliveryPoint.objects.filter(account=account).exists()

    resp = c.post(
        reverse("accounting:account_edit", args=[account.pk]),
        _account_form_data(account, unit_kind="farm_unit", delivery_pod=""),
    )

    assert resp.status_code == 302
    assert not WaterAccountDeliveryPoint.objects.filter(account=account).exists()


# ---------------------------------------------------------------------------
# 4. Shape 1: the point select shows, the well select does not
# ---------------------------------------------------------------------------


@override_settings(OPENH2O_MODULES=_SHAPE_1)
def test_shape_1_create_form_shows_point_select_not_well_select(auth_client):
    resp = auth_client.get(reverse("accounting:account_create"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'name="delivery_pod"' in body
    assert 'name="delivery_well"' not in body


# ---------------------------------------------------------------------------
# 5. The identity-card sentence
# ---------------------------------------------------------------------------


def test_identity_sentence_farm_unit_no_delivery(auth_client):
    account = WaterAccountFactory(unit_kind="farm_unit")
    body = auth_client.get(reverse("accounting:account_detail", args=[account.pk])).content.decode()
    assert "A farm unit" in body
    assert "delivered through" not in body


def test_identity_sentence_place_of_use_delivered_through_a_point(auth_client):
    """The plan's own verify example: a place-of-use account delivered
    through A001885_01 (the shape-1 checkpoint scenario, proven here against
    a matching fixture rather than a standing stack)."""
    pod = PointOfDiversionFactory(name="A001885_01")
    account = WaterAccountFactory(unit_kind="place_of_use")
    from surface.models import WaterAccountDeliveryPoint

    WaterAccountDeliveryPoint.objects.create(account=account, point_of_diversion=pod)

    body = auth_client.get(reverse("accounting:account_detail", args=[account.pk])).content.decode()

    assert "A place of use" in body
    assert "delivered through A001885_01" in body


def test_identity_sentence_delivered_through_a_well(auth_client):
    well = WellFactory(name="Test Well 7")
    account = WaterAccountFactory(unit_kind="farm_unit", delivery_well=well)

    body = auth_client.get(reverse("accounting:account_detail", args=[account.pk])).content.decode()

    assert "A farm unit" in body
    assert "delivered through Test Well 7" in body


def test_identity_sentence_not_stated_when_unit_kind_blank(auth_client):
    account = WaterAccountFactory(unit_kind=None)
    body = auth_client.get(reverse("accounting:account_detail", args=[account.pk])).content.decode()
    assert "Not stated" in body
