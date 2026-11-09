# SPDX-License-Identifier: AGPL-3.0-or-later
"""
152-03.2: the ``add_sampling_point`` command and ``drinking.onboarding.add_sampling_point``.

All data is INVENTED: water systems CA0000051 and CA0000052 (California) and
XX0000053 (outside California), with invented facilities and names.

Every sentence a person reads is one named constant per row of
``.planning/phases/152-proven-by-strangers/152-03.2-ROWS.md``.
"""

from io import StringIO

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.management import call_command, load_command_class
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse

from drinking.models import SamplingPoint
from tests.factories import SystemFacilityFactory, WaterSystemFactory

# -- the rows (Fixed column) -------------------------------------------------
ROW_4 = (
    "Add a sampling point to one of the water system's facilities. The command adds "
    "a point the same way as the water system's Sampling points page."
)
ROW_5 = "The facility ID, such as 010 or DST."
ROW_6 = (
    "For a California water system, the point number or label, such as 010 or LCR. "
    "OpenH2O builds the PS Code from the PWSID, the facility ID and the point number."
)
ROW_7 = (
    "For a water system outside California, the sampling point code exactly as it "
    "appears in the lab results file."
)
ROW_8 = 'The sampling point\'s name, such as "Lead testing tap".'
ROW_9 = "The point type: source, entry_point, distribution or tap."
ROW_10 = (
    "The water system's PWSID. Give it only when the site has more than one water "
    "system."
)
ROW_31 = "OpenH2O added {name} as sampling point {ps_code}."
ROW_32 = "OpenH2O added sampling point {ps_code}."
ROW_33 = "Sampling point {ps_code} is already on file. OpenH2O changed nothing."
ROW_34 = "This site has no water system. Add the water system first with add_water_system."
ROW_35 = "This site has {n} water systems. Give the system's PWSID with --pwsid."
ROW_36 = "No water system in OpenH2O has the PWSID {pwsid}. Add the water system first."
ROW_37 = "{system} has no facility with the facility ID {id}. Its facility IDs are {list}."
ROW_38 = "Give --point-number for a California water system."
ROW_39 = "Give --ps-code for a water system outside California."
# The PS Code refusal is drinking/ps_codes.py's own sentence, unchanged.
PS_CODE_UNDERSCORE = (
    "The point number '1_2' contains an underscore. A PS Code uses underscores only "
    "between its three parts."
)
# The page's own sentences, which add_sampling_point (the function) raises.
PAGE_NO_CODE = "Enter the sampling point code."
PAGE_BAD_TYPE = "Choose a point type: Source, Entry Point, Distribution or Tap."
PAGE_TOO_LONG = (
    "A sampling point code can have up to 60 characters, and this one has {n}."
)

CA = "CA0000051"
OTHER_STATE = "XX0000053"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"addpoint{n}")
    email = factory.Sequence(lambda n: f"addpoint{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(UserFactory())
    return client


@pytest.fixture
def ca_system(db):
    system = WaterSystemFactory(pwsid=CA, name="Demonstration Point District")
    facility = SystemFacilityFactory(system=system, facility_id="010", name="Well ten")
    return system, facility


def run(*args):
    out = StringIO()
    call_command("add_sampling_point", *args, stdout=out, stderr=StringIO())
    return [line.strip() for line in out.getvalue().splitlines() if line.strip()]


def stored():
    return sorted(
        (p.ps_code, p.facility.facility_id, p.name, p.point_type)
        for p in SamplingPoint.objects.select_related("facility")
    )


def test_help_lines_are_the_rows():
    command = load_command_class("drinking", "add_sampling_point")
    text = " ".join(
        command.create_parser("manage.py", "add_sampling_point").format_help().split()
    )
    for row in (ROW_4, ROW_5, ROW_6, ROW_7, ROW_8, ROW_9, ROW_10):
        assert row in text


def test_the_page_and_the_command_write_the_same_point(client_in, ca_system):
    system, facility = ca_system
    client_in.post(
        reverse("drinking:onboard_points_add", args=[CA]),
        {
            "facility": facility.pk,
            "point_number": "001",
            "name": "Well ten raw",
            "point_type": "source",
        },
    )
    from_page = stored()
    assert from_page == [(f"{CA}_010_001", "010", "Well ten raw", "source")]
    SamplingPoint.objects.all().delete()

    run("--facility", "010", "--point-number", "001", "--name", "Well ten raw",
        "--type", "source")

    assert stored() == from_page


def test_a_point_with_a_name_prints_row_31(ca_system):
    lines = run("--facility", "010", "--point-number", "001", "--name", "Lead testing tap")
    assert ROW_31.format(name="Lead testing tap", ps_code=f"{CA}_010_001") in lines


def test_a_point_without_a_name_prints_row_32(ca_system):
    lines = run("--facility", "010", "--point-number", "002")
    assert ROW_32.format(ps_code=f"{CA}_010_002") in lines


def test_a_second_identical_call_prints_row_33_and_changes_nothing(ca_system):
    args = ("--facility", "010", "--point-number", "001", "--name", "First name")
    run(*args)
    before = stored()
    lines = run("--facility", "010", "--point-number", "001", "--name", "Other name")
    assert ROW_33.format(ps_code=f"{CA}_010_001") in lines
    assert stored() == before


def test_outside_california_the_code_is_stored_exactly_as_given(db):
    system = WaterSystemFactory(pwsid=OTHER_STATE, name="Demonstration Other District")
    SystemFacilityFactory(system=system, facility_id="010")
    lines = run("--facility", "010", "--ps-code", "LAB-POINT-7")
    assert [p.ps_code for p in SamplingPoint.objects.all()] == ["LAB-POINT-7"]
    assert ROW_32.format(ps_code="LAB-POINT-7") in lines


def test_outside_california_without_a_ps_code_is_row_39(db):
    system = WaterSystemFactory(pwsid=OTHER_STATE)
    SystemFacilityFactory(system=system, facility_id="010")
    with pytest.raises(CommandError) as raised:
        run("--facility", "010")
    assert str(raised.value) == ROW_39
    assert SamplingPoint.objects.count() == 0


def test_a_california_system_without_a_point_number_is_row_38(ca_system):
    with pytest.raises(CommandError) as raised:
        run("--facility", "010")
    assert str(raised.value) == ROW_38
    assert SamplingPoint.objects.count() == 0


def test_a_site_with_no_system_is_row_34(db):
    with pytest.raises(CommandError) as raised:
        run("--facility", "010", "--point-number", "001")
    assert str(raised.value) == ROW_34


def test_two_systems_and_no_pwsid_is_row_35(ca_system):
    WaterSystemFactory(pwsid="CA0000052")
    with pytest.raises(CommandError) as raised:
        run("--facility", "010", "--point-number", "001")
    assert str(raised.value) == ROW_35.format(n=2)
    assert SamplingPoint.objects.count() == 0


def test_a_pwsid_the_site_does_not_hold_is_row_36(ca_system):
    with pytest.raises(CommandError) as raised:
        run("--pwsid", "CA0000099", "--facility", "010", "--point-number", "001")
    assert str(raised.value) == ROW_36.format(pwsid="CA0000099")


def test_pwsid_picks_the_system_when_there_are_two(ca_system):
    other = WaterSystemFactory(pwsid="CA0000052")
    SystemFacilityFactory(system=other, facility_id="010")
    run("--pwsid", "CA0000052", "--facility", "010", "--point-number", "001")
    assert [p.ps_code for p in SamplingPoint.objects.all()] == ["CA0000052_010_001"]


def test_an_unknown_facility_lists_the_systems_facility_ids_row_37(ca_system):
    system, _ = ca_system
    SystemFacilityFactory(system=system, facility_id="DST")
    SystemFacilityFactory(system=system, facility_id="020")
    with pytest.raises(CommandError) as raised:
        run("--facility", "999", "--point-number", "001")
    assert str(raised.value) == ROW_37.format(
        system=system.name, id="999", list="010, 020, DST"
    )
    assert SamplingPoint.objects.count() == 0


def test_a_point_number_with_an_underscore_gets_the_ps_code_sentence(ca_system):
    with pytest.raises(CommandError) as raised:
        run("--facility", "010", "--point-number", "1_2")
    assert str(raised.value) == PS_CODE_UNDERSCORE
    assert SamplingPoint.objects.count() == 0


# -- drinking.onboarding.add_sampling_point -----------------------------------


def test_the_function_returns_the_point_and_whether_it_was_created(ca_system):
    from drinking import onboarding

    system, facility = ca_system
    point, created = onboarding.add_sampling_point(
        system, facility, point_number="001", name="Well ten raw", point_type="source"
    )
    assert created is True
    assert (point.ps_code, point.facility, point.name, point.point_type) == (
        f"{CA}_010_001", facility, "Well ten raw", "source",
    )
    again, created = onboarding.add_sampling_point(system, facility, point_number="001")
    assert created is False and again.pk == point.pk


def test_the_function_refuses_with_the_pages_sentences(ca_system, db):
    from drinking import onboarding

    system, facility = ca_system
    with pytest.raises(ValueError, match="contains an underscore"):
        onboarding.add_sampling_point(system, facility, point_number="1_2")
    with pytest.raises(ValueError, match="Enter the point number."):
        onboarding.add_sampling_point(system, facility, point_number="")
    with pytest.raises(ValueError) as bad_type:
        onboarding.add_sampling_point(
            system, facility, point_number="001", point_type="sink"
        )
    assert str(bad_type.value) == PAGE_BAD_TYPE

    other = WaterSystemFactory(pwsid=OTHER_STATE)
    other_facility = SystemFacilityFactory(system=other, facility_id="010")
    with pytest.raises(ValueError) as empty:
        onboarding.add_sampling_point(other, other_facility, ps_code="")
    assert str(empty.value) == PAGE_NO_CODE
    with pytest.raises(ValueError) as long_code:
        onboarding.add_sampling_point(other, other_facility, ps_code="X" * 61)
    assert str(long_code.value) == PAGE_TOO_LONG.format(n=61)
    assert SamplingPoint.objects.count() == 0


def test_the_page_calls_the_function(client_in, ca_system, monkeypatch):
    """The view must reach it as ``onboarding.add_sampling_point`` (or patch both names)."""
    from drinking import onboarding
    from drinking.views import onboard

    system, facility = ca_system

    def refuse(*args, **kwargs):
        raise ValueError("An invented refusal sentence.")

    monkeypatch.setattr(onboarding, "add_sampling_point", refuse)
    if hasattr(onboard, "add_sampling_point"):
        monkeypatch.setattr(onboard, "add_sampling_point", refuse)
    response = client_in.post(
        reverse("drinking:onboard_points_add", args=[CA]),
        {"facility": facility.pk, "point_number": "001", "point_type": "source"},
    )
    assert "An invented refusal sentence." in response.content.decode()
    assert SamplingPoint.objects.count() == 0
