# SPDX-License-Identifier: AGPL-3.0-or-later
"""seed_merced_base must own the single-tenant agency identity (Phase 53-01 fix).

The platform is single-tenant: one SiteConfig names the deployed agency. Only the
retired seeds ever created one, so the Merced base seed has to ensure the right
identity exists — create it on a bare install and leave a custom name alone.

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
    assert SiteConfig.objects.get().agency_name == "Halvern Valley GSA"


@pytest.mark.django_db
def test_keeps_custom_agency_name():
    SiteConfig.objects.create(agency_name="Mariposa County Water Agency")
    call_command("seed_merced_base")
    assert SiteConfig.objects.count() == 1
    assert SiteConfig.objects.get().agency_name == "Mariposa County Water Agency"


@pytest.mark.django_db
def test_leaves_custom_agency_demonstration_mode_untouched():
    """A genuinely custom agency name is never stamped as a demonstration."""
    SiteConfig.objects.create(
        agency_name="Mariposa County Water Agency", demonstration_mode=False)
    call_command("seed_merced_base")
    assert SiteConfig.objects.get().demonstration_mode is False


@pytest.mark.django_db
def test_keeps_custom_contact_email_on_merced_identity():
    """A real operator's own contact email is never overwritten by a re-seed."""
    SiteConfig.objects.create(
        agency_name="Halvern Valley GSA",
        contact_email="ops@realagency.gov")
    call_command("seed_merced_base")
    assert SiteConfig.objects.get().contact_email == "ops@realagency.gov"
