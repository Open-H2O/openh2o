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
    assert SiteConfig.objects.get().agency_name == "Halvern Valley GSA"


@pytest.mark.django_db
def test_renames_retired_basin_identity():
    SiteConfig.objects.create(agency_name="Demo Valley GSA")
    call_command("seed_merced_base")
    assert SiteConfig.objects.count() == 1
    assert SiteConfig.objects.get().agency_name == "Halvern Valley GSA"


@pytest.mark.django_db
def test_keeps_custom_agency_name():
    SiteConfig.objects.create(agency_name="Mariposa County Water Agency")
    call_command("seed_merced_base")
    assert SiteConfig.objects.count() == 1
    assert SiteConfig.objects.get().agency_name == "Mariposa County Water Agency"


# ---------------------------------------------------------------------------
# The ownership gate (Phase 97-02)
#
# The demo's agency identity used to be a real agency's name, and both live
# deployments were already carrying it. A rename alone would have left it there
# forever: the row matched no branch and fell through to "kept (custom agency
# name)". The fix keys the forward rename on demonstration_mode — the flag only
# this seed ever writes — so a seed-owned row renames and a real agency's row
# does not.
#
# The next two tests are one controlled experiment: the SAME agency name, the
# flag flipped, opposite outcomes. That pairing is the whole guarantee, and
# without the second one the guard's entire point is unproven.
# ---------------------------------------------------------------------------

REAL_AGENCY = "Mariposa County Water Agency"


@pytest.mark.django_db
def test_renames_a_seed_owned_identity_forward_whatever_it_is_called():
    """demonstration_mode=True means the seed owns this row, so it renames.

    This is the deployed-instance case: staging and production both carried the
    demo's previous agency name with the flag on, and this is what moves them
    onto the current identity instead of stranding them on the old one.
    """
    SiteConfig.objects.create(
        agency_name=REAL_AGENCY,
        contact_email="info@mercedsubbasingsa.example.com",
        demonstration_mode=True,
    )
    call_command("seed_merced_base")
    sc = SiteConfig.objects.get()
    assert sc.agency_name == "Halvern Valley GSA"
    assert sc.demonstration_mode is True
    # The outgoing demo contact address heals alongside the name — leaving it
    # behind is exactly how ISS-067 happened the first time.
    assert sc.contact_email == "info@halvernvalleygsa.example.com"


@pytest.mark.django_db
def test_never_renames_a_real_agency_that_chose_that_name():
    """demonstration_mode=False means a real deployment. Hands off.

    Same name as the test above, flag off: untouched. This is why the guard
    keys on ownership instead of on a list of retired names — a name list is
    matched against whatever an operator typed, so a real agency that
    legitimately chose the demo's former name would be silently renamed out
    from under them.
    """
    SiteConfig.objects.create(
        agency_name=REAL_AGENCY,
        contact_email="ops@realagency.gov",
        demonstration_mode=False,
    )
    call_command("seed_merced_base")
    sc = SiteConfig.objects.get()
    assert sc.agency_name == REAL_AGENCY
    assert sc.demonstration_mode is False
    assert sc.contact_email == "ops@realagency.gov"


@pytest.mark.django_db
def test_enables_demonstration_mode_on_existing_merced_identity():
    """An existing Merced demo whose SiteConfig predates the demonstration_mode
    field (migrated in as False) gets it flipped on by a re-seed — the name
    already matches, so neither the create nor the rename branch fires (53-02)."""
    SiteConfig.objects.create(
        agency_name="Halvern Valley GSA", demonstration_mode=False)
    call_command("seed_merced_base")
    sc = SiteConfig.objects.get()
    assert sc.agency_name == "Halvern Valley GSA"
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
    assert sc.agency_name == "Halvern Valley GSA"
    assert sc.contact_email == "info@halvernvalleygsa.example.com"


@pytest.mark.django_db
def test_heals_retired_basin_email_on_existing_merced_identity():
    """The exact ISS-067 production state: name already says Merced, but the
    contact email is still the retired Kaweah demo address. A re-seed must
    correct the stale email even though the name already matches."""
    SiteConfig.objects.create(
        agency_name="Halvern Valley GSA",
        contact_email="info@kaweahgsa.example.com")
    call_command("seed_merced_base")
    assert SiteConfig.objects.get().contact_email == (
        "info@halvernvalleygsa.example.com")


@pytest.mark.django_db
def test_keeps_custom_contact_email_on_merced_identity():
    """A real operator's own contact email is never overwritten — only the
    known retired demo emails are healed, so a deployment that set a real
    address keeps it across a re-seed."""
    SiteConfig.objects.create(
        agency_name="Halvern Valley GSA",
        contact_email="ops@realagency.gov")
    call_command("seed_merced_base")
    assert SiteConfig.objects.get().contact_email == "ops@realagency.gov"
