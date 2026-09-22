# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-03 Task 2: method, device and data state on every diversion record, and
the rule version derived from the month.

23 CCR 934(b)(1) is the device vocabulary; 931(s) and 931(j)(3) are the three
data states (raw, provisional, non-provisional); the 2016 rule (23 CCR 937)
governs Water Year 2026 and earlier, the 2026 rewrite (23 CCR 934) governs
from Water Year 2027, October 1, 2026. Four doors proven here, each RED
against the unfixed tree (the exact quotes live in 146-03-EVIDENCE.md):

  1. ``DiversionRecord.rule_version`` at a September 2026 month and an
     October 2026 month.
  2. The record create form defaults to method='device' / device=<current>
     when the point has a current device, and to a blank method otherwise.
  3. The records table's "How known" column: "device . <nickname> .
     provisional" for a record entered with the device; "not stated" for a
     record saved with no method.
"""
from datetime import date

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from surface.forms import DiversionRecordForm
from surface.models import DiversionRecord, MeasuringDevice, PointOfDiversionDevice
from tests.factories import DiversionRecordFactory, PointOfDiversionFactory

pytestmark = pytest.mark.django_db


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"methoduser{n}")
    email = factory.Sequence(lambda n: f"methoduser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


# ---------------------------------------------------------------------------
# 1. rule_version, derived from the month, never stored
# ---------------------------------------------------------------------------


def test_rule_version_2016_rule_before_water_year_2027():
    record = DiversionRecordFactory(month=date(2026, 9, 1))
    assert record.rule_version == "2016 rule (23 CCR 937)"


def test_rule_version_2026_rewrite_from_water_year_2027():
    record = DiversionRecordFactory(month=date(2026, 10, 1))
    assert record.rule_version == "2026 rewrite (23 CCR 934)"


def test_rule_version_is_never_a_stored_column():
    assert "rule_version" not in [f.name for f in DiversionRecord._meta.get_fields()]


# ---------------------------------------------------------------------------
# 2. Form defaults: with and without a current device
# ---------------------------------------------------------------------------


def test_form_defaults_to_device_method_when_point_has_current_device():
    pod = PointOfDiversionFactory()
    device = MeasuringDevice.objects.create(
        nickname="Atwater flow meter", device_type="inline_flow_meter",
    )
    PointOfDiversionDevice.objects.create(
        point_of_diversion=pod, device=device, is_current=True,
    )

    form = DiversionRecordForm(pod=pod)
    assert form.initial.get("method") == "device"
    assert form.initial.get("device") == device.pk


def test_form_defaults_to_blank_method_with_no_current_device():
    pod = PointOfDiversionFactory()
    form = DiversionRecordForm(pod=pod)
    assert not form.initial.get("method")
    assert not form.initial.get("device")


def test_form_device_queryset_limited_to_this_points_devices_current_first():
    pod = PointOfDiversionFactory()
    other_pod = PointOfDiversionFactory()
    current = MeasuringDevice.objects.create(
        nickname="Current device", device_type="inline_flow_meter",
    )
    removed = MeasuringDevice.objects.create(
        nickname="Removed device", device_type="v_notch_weir",
    )
    other_points_device = MeasuringDevice.objects.create(
        nickname="Other point's device", device_type="rated_gate",
    )
    PointOfDiversionDevice.objects.create(
        point_of_diversion=pod, device=current, is_current=True,
    )
    PointOfDiversionDevice.objects.create(
        point_of_diversion=pod, device=removed, is_current=False,
        removed_on=date(2024, 1, 1),
    )
    PointOfDiversionDevice.objects.create(
        point_of_diversion=other_pod, device=other_points_device, is_current=True,
    )

    form = DiversionRecordForm(pod=pod)
    device_qs = list(form.fields["device"].queryset)
    assert device_qs[0] == current
    assert other_points_device not in device_qs
    assert removed in device_qs


def test_data_state_defaults_to_provisional_on_the_form():
    pod = PointOfDiversionFactory()
    form = DiversionRecordForm(pod=pod)
    assert form.fields["data_state"].initial == "provisional" or (
        DiversionRecord._meta.get_field("data_state").default == "provisional"
    )


# ---------------------------------------------------------------------------
# 3. The records table's "How known" column
# ---------------------------------------------------------------------------


def test_table_shows_device_nickname_and_provisional_for_a_device_record(auth_client):
    pod = PointOfDiversionFactory()
    device = MeasuringDevice.objects.create(
        nickname="Atwater flow meter", device_type="inline_flow_meter",
    )
    PointOfDiversionDevice.objects.create(
        point_of_diversion=pod, device=device, is_current=True,
    )
    DiversionRecordFactory(
        point_of_diversion=pod, month=date(2024, 3, 1),
        method="device", device=device, data_state="provisional",
    )

    resp = auth_client.get(reverse("surface:pod_detail", args=[pod.pk]))
    body = resp.content.decode()
    assert "Atwater flow meter" in body
    assert "provisional" in body.lower()
    assert "A measuring device" in body


def test_table_shows_not_stated_for_a_record_with_no_method(auth_client):
    pod = PointOfDiversionFactory()
    DiversionRecordFactory(
        point_of_diversion=pod, month=date(2024, 4, 1), method="", device=None,
    )

    resp = auth_client.get(reverse("surface:pod_detail", args=[pod.pk]))
    body = resp.content.decode()
    assert "not stated" in body.lower()


def test_table_carries_rule_version_in_the_row_title_not_a_column(auth_client):
    pod = PointOfDiversionFactory()
    record = DiversionRecordFactory(point_of_diversion=pod, month=date(2026, 10, 1))

    resp = auth_client.get(reverse("surface:pod_detail", args=[pod.pk]))
    body = resp.content.decode()
    assert "2026 rewrite (23 CCR 934)" in body
    # Not a header naming the rule version as its own column.
    assert "Rule version</th>" not in body
