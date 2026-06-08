# SPDX-License-Identifier: AGPL-3.0-or-later
"""seed_merced_base must own the single-tenant agency identity (Phase 53-01 fix).

The platform is single-tenant: one SiteConfig names the deployed agency. Only the
retired seeds ever created one, so the Merced base seed has to ensure the right
identity exists — create it on a bare install, rename it off a retired-basin
name, and leave a custom name alone. These three cases are the contract.

The base seed loads a committed GeoJSON boundary; these tests only assert the
SiteConfig side effect, so they call the helper through the command and tolerate
the boundary load (the fixture file ships in the repo).
"""
import pytest
from django.core.management import call_command

from core.models import SiteConfig


@pytest.mark.django_db
def test_creates_site_config_when_absent():
    assert not SiteConfig.objects.exists()
    call_command("seed_merced_base")
    assert SiteConfig.objects.count() == 1
    assert SiteConfig.objects.get().agency_name == "Merced Subbasin GSA"


@pytest.mark.django_db
def test_renames_retired_basin_identity():
    SiteConfig.objects.create(agency_name="Demo Valley GSA")
    call_command("seed_merced_base")
    assert SiteConfig.objects.count() == 1
    assert SiteConfig.objects.get().agency_name == "Merced Subbasin GSA"


@pytest.mark.django_db
def test_keeps_custom_agency_name():
    SiteConfig.objects.create(agency_name="Mariposa County Water Agency")
    call_command("seed_merced_base")
    assert SiteConfig.objects.count() == 1
    assert SiteConfig.objects.get().agency_name == "Mariposa County Water Agency"


@pytest.mark.django_db
def test_enables_demonstration_mode_on_existing_merced_identity():
    """An existing Merced demo whose SiteConfig predates the demonstration_mode
    field (migrated in as False) gets it flipped on by a re-seed — the name
    already matches, so neither the create nor the rename branch fires (53-02)."""
    SiteConfig.objects.create(
        agency_name="Merced Subbasin GSA", demonstration_mode=False)
    call_command("seed_merced_base")
    sc = SiteConfig.objects.get()
    assert sc.agency_name == "Merced Subbasin GSA"
    assert sc.demonstration_mode is True


@pytest.mark.django_db
def test_leaves_custom_agency_demonstration_mode_untouched():
    """A genuinely custom agency name is never stamped as a demonstration."""
    SiteConfig.objects.create(
        agency_name="Mariposa County Water Agency", demonstration_mode=False)
    call_command("seed_merced_base")
    assert SiteConfig.objects.get().demonstration_mode is False


@pytest.mark.django_db
def test_heals_retired_basin_email_on_renamed_identity():
    """A demo renamed off a retired basin still carrying that basin's contact
    email gets the email healed too (ISS-067): the in-place rename moved the
    name but left ``info@kaweahgsa.example.com`` behind for the demo's lifetime."""
    SiteConfig.objects.create(
        agency_name="Demo Valley GSA",
        contact_email="info@kaweahgsa.example.com")
    call_command("seed_merced_base")
    sc = SiteConfig.objects.get()
    assert sc.agency_name == "Merced Subbasin GSA"
    assert sc.contact_email == "info@mercedsubbasingsa.example.com"


@pytest.mark.django_db
def test_heals_retired_basin_email_on_existing_merced_identity():
    """The exact ISS-067 production state: name already says Merced, but the
    contact email is still the retired Kaweah demo address. A re-seed must
    correct the stale email even though the name already matches."""
    SiteConfig.objects.create(
        agency_name="Merced Subbasin GSA",
        contact_email="info@kaweahgsa.example.com")
    call_command("seed_merced_base")
    assert SiteConfig.objects.get().contact_email == (
        "info@mercedsubbasingsa.example.com")


@pytest.mark.django_db
def test_keeps_custom_contact_email_on_merced_identity():
    """A real operator's own contact email is never overwritten — only the
    known retired demo emails are healed, so a deployment that set a real
    address keeps it across a re-seed."""
    SiteConfig.objects.create(
        agency_name="Merced Subbasin GSA",
        contact_email="ops@realagency.gov")
    call_command("seed_merced_base")
    assert SiteConfig.objects.get().contact_email == "ops@realagency.gov"
