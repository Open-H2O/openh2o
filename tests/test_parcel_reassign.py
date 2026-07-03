# SPDX-License-Identifier: AGPL-3.0-or-later
"""P1-1: re-assigning a previously-removed parcel must un-tombstone the row.

remove_parcel soft-deletes by setting removed_date; the (account, parcel,
period) unique key means a later assign hits the tombstoned row. Without
clearing removed_date the assign is a silent no-op the operator can't recover.
"""
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounting.models import WaterAccountParcel
from tests.factories import ParcelFactory, WaterAccountFactory

User = get_user_model()


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(
        User.objects.create_user(username="op", email="op@example.com", password="x")
    )
    return c


@pytest.mark.django_db
def test_reassigning_removed_parcel_reactivates_it(auth_client):
    account = WaterAccountFactory()
    parcel = ParcelFactory()
    assign_url = reverse("accounting:assign_parcel", args=[account.pk])

    auth_client.post(assign_url, {"parcel_id": parcel.pk})
    wap = WaterAccountParcel.objects.get(water_account=account, parcel=parcel)
    assert wap.removed_date is None

    auth_client.post(
        reverse("accounting:remove_parcel", args=[account.pk, wap.pk])
    )
    wap.refresh_from_db()
    assert wap.removed_date is not None  # soft-deleted

    # Re-assign the same parcel — must clear the tombstone, not silently no-op.
    auth_client.post(assign_url, {"parcel_id": parcel.pk})
    wap.refresh_from_db()
    assert wap.removed_date is None, "re-assign must reactivate the removed row"

    active = WaterAccountParcel.objects.filter(
        water_account=account, removed_date__isnull=True
    )
    assert active.count() == 1
    assert active.first().parcel_id == parcel.pk
