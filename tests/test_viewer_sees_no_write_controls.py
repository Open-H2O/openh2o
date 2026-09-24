# SPDX-License-Identifier: AGPL-3.0-or-later
"""A viewer sees every page and no control that changes a record (147-02 Task 2).

Task 1 gave the platform a Viewer role, ``core.access.ReadOnlyMiddleware`` (which
refuses a viewer's POST/PUT/PATCH/DELETE outside a short allowlist) and the
``user_can_write`` template flag. Task 1 stops there: it refuses the write, it
does not hide the button that leads to it. This file is the guard for the other
half: a viewer should never be shown a control whose only purpose is to change
a record, even one the middleware would refuse if pressed.

**Rendered WITH rows, deliberately (ISS-091).** An empty database hides a write
control that only renders beside a row it would act on (an "Edit" link on a
table row, a "Remove" button in an assignment list). 89-03/90-01 found the same
class of gap in the droppability harness for exactly this reason. This file
builds its own fixture with ``tests/factories.py`` rather than reusing
``tests/droppability/fixture.py``, because that fixture is scoped to what a
dropped-module render needs (one row per surviving domain) and this file needs
what a VIEWER walk needs instead: a water account with its parcel actually
assigned, a finalized period sitting next to an open one, a diversion record and
an allocation plan, so the pages that only show a control next to that specific
shape of data get a real chance to show it.

**Run twice, in both ``ACCESS_CONTROL_ENFORCED`` postures.** OFF is the hosted
demo, where ``admin_required`` is a pass-through and a signed-in viewer reaches
admin-only screens (Users, Methodology) that ON would bounce away entirely:
so OFF is the posture where a viewer reaches the most pages, and it is where
this guard has the most to check. ON is checked too because the Viewer role
holds "whichever way the switch is set" (``core/access.py``), and a page that
passes only under one posture would be a gap the other posture never noticed.

**What counts as a write control, resolved rather than guessed at:**
  * any ``<form`` whose method is POST (case-insensitive; a form with no
    ``action`` posts to the page's own path);
  * any ``hx-post``, ``hx-patch``, ``hx-put`` or ``hx-delete`` attribute, on any
    tag;
  * any ``href`` or ``hx-get`` whose target resolves (via ``django.urls.resolve``)
    to a URL name that opens a form which changes a record: a create, add,
    edit, upload, import, assign, remove, finalize or delete control (this is
    where ``edit_field``'s inline-edit trigger lives: the button is a GET that
    opens an edit form, and the PATCH it eventually sends is caught by the rule
    above on the rendered edit form itself, wherever that also renders).

A resolved URL is only allowed when ``core.access.viewer_may_post`` says the
viewer may act on it: logout, password change and the other ``account_*``
allauth views, the feedback widget, the nav-mode switch, the profile page.
Anything else is an offender, and the assertion message names the page, the
attribute that carried it, and the URL name it resolved to, so a failure is
its own fix list.
"""
import re
from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import Resolver404, resolve
from django.utils import timezone

from core.access import viewer_may_post
from drinking.models import SamplingSchedule
from tests.droppability.checks import KEPT_PAGES
from tests.factories import (
    AllocationPlanFactory,
    AnalyteFactory,
    DiversionRecordFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    RechargeEventFactory,
    RechargeSiteFactory,
    ReportingPeriodFactory,
    SampleEventFactory,
    SampleResultFactory,
    SamplingPointFactory,
    SystemFacilityFactory,
    WaterAccountFactory,
    WaterAccountParcelFactory,
    WaterRightFactory,
    WaterRightParcelFactory,
    WaterRightTypeFactory,
    WaterSystemFactory,
    WellFactory,
    WellIrrigatedParcelFactory,
    ZoneFactory,
)

pytestmark = pytest.mark.django_db

User = get_user_model()


# ---------------------------------------------------------------------------
# The rows. Every record type the plan names, at least one of each, and the
# two shapes of ReportingPeriod (open, finalized-with-an-allocation) that make
# the period page's two branches (Finalize / Reopen) both reachable.
# ---------------------------------------------------------------------------


def _seed_rows():
    parcel = ParcelFactory(
        parcel_number="VWR-000001", owner_name="Viewer Sweep Owner"
    )
    ParcelLedgerFactory(parcel=parcel, source_type="manual_entry")

    well = WellFactory(name="Viewer Sweep Well")
    WellIrrigatedParcelFactory(well=well, parcel=parcel)

    zone = ZoneFactory(name="Viewer Sweep Zone")

    account = WaterAccountFactory(
        name="Viewer Sweep Account", account_number="VWR-ACCT-0001"
    )
    WaterAccountParcelFactory(water_account=account, parcel=parcel)

    open_period = ReportingPeriodFactory(
        name="Viewer Sweep Open WY",
        start_date=date(2024, 10, 1),
        end_date=date(2025, 9, 30),
    )
    finalized_period = ReportingPeriodFactory(
        name="Viewer Sweep Finalized WY",
        start_date=date(2021, 10, 1),
        end_date=date(2022, 9, 30),
    )
    AllocationPlanFactory(zone=zone, reporting_period=finalized_period)
    # Written while open, then closed: a finalized year refuses writes (147-02).
    finalized_period.is_finalized = True
    finalized_period.finalized_at = timezone.now()
    finalized_period.save(update_fields=["is_finalized", "finalized_at"])

    right_type = WaterRightTypeFactory(name="Viewer Sweep Right Type")
    water_right = WaterRightFactory(
        right_id="WR-900002", right_type=right_type, holder_name="Viewer Sweep Holder"
    )
    pod = PointOfDiversionFactory(name="Viewer Sweep POD", water_right=water_right)
    DiversionRecordFactory(point_of_diversion=pod)
    PointOfDiversionParcelFactory(point_of_diversion=pod, parcel=parcel)
    WaterRightParcelFactory(water_right=water_right, parcel=parcel)

    recharge_site = RechargeSiteFactory(name="Viewer Sweep Recharge Site")
    RechargeEventFactory(recharge_site=recharge_site)

    # A drinking-water system with a facility, a sampling point, a sample
    # result and a schedule row. Without these, every drinking page's "no
    # water system yet" branch is the only one this file ever renders (the
    # ISS-091 gap this whole file exists to close, one domain over): the real
    # facility form, the real schedule table and the real onboard-another /
    # point-builder / import step cards only exist behind a WaterSystem row.
    system = WaterSystemFactory(pwsid="CA1900099", name="Viewer Sweep Water System")
    facility = SystemFacilityFactory(
        system=system, facility_id="VWR-F0001", name="Viewer Sweep Facility",
        is_source=True,
    )
    sampling_point = SamplingPointFactory(
        ps_code="CA1900099_VWR-F0001_001",
        name="Viewer Sweep Sampling Point",
        facility=facility,
    )
    event = SampleEventFactory(sampling_point=sampling_point)
    SampleResultFactory(
        event=event, analyte=AnalyteFactory(name="Viewer Sweep Analyte")
    )
    SamplingSchedule.objects.create(
        system=system,
        sampling_point=sampling_point,
        frequency="monthly",
        last_done=date(2026, 1, 1),
        next_due=date(2026, 7, 1),
    )

    # The methodology page's steps. Idempotent (get_or_create/update_or_create),
    # so calling it here never collides with anything else the test run does.
    call_command("seed_calculation_plan")

    # A second, ordinary user. The Users screen's per-row role/status forms
    # only render next to a row that is neither the signed-in viewer itself
    # nor a host administrator (`templates/core/users_list.html`), so without
    # one this file would repeat exactly the ISS-091 gap it exists to close:
    # green because the row those forms need was never on the page.
    User.objects.create_user(
        username="viewer-sweep-other-user",
        email="viewer-sweep-other-user@example.org",
        password="a-good-passw0rd",
        is_active=True,
    )

    return {
        "parcel": parcel,
        "well": well,
        "zone": zone,
        "account": account,
        "open_period": open_period,
        "finalized_period": finalized_period,
        "water_right": water_right,
        "pod": pod,
        "recharge_site": recharge_site,
    }


def _detail_pages(rows):
    """Detail pages of the rows above, reached off the ``_PAGES`` list pages.

    Named explicitly rather than derived, same discipline as ``checks.py``'s own
    ``_PAGES`` table: a wrong guess about which detail routes exist is a wrong
    guess this file would otherwise never notice. Diversion records and
    allocation plans have no detail route of their own: a diversion record
    shows on the POD's own page and an allocation shows on the period's own
    page, both already covered by the two rows below.
    """
    return (
        ("/parcels/%d/" % rows["parcel"].pk, "use area detail"),
        ("/wells/%d/" % rows["well"].pk, "well detail"),
        ("/accounting/accounts/%d/" % rows["account"].pk, "water account detail"),
        (
            "/accounting/reporting-periods/%d/" % rows["open_period"].pk,
            "reporting period detail (open)",
        ),
        (
            "/accounting/reporting-periods/%d/" % rows["finalized_period"].pk,
            "reporting period detail (finalized)",
        ),
        ("/surface/diversion/%d/" % rows["pod"].pk, "point of diversion detail"),
        ("/surface/rights/%d/" % rows["water_right"].pk, "water right detail"),
        ("/recharge/%d/" % rows["recharge_site"].pk, "recharge site detail"),
    )


# ---------------------------------------------------------------------------
# The scan. A small hand-rolled tag/attribute reader rather than a full HTML
# parser dependency: it only ever needs to find tag names and attribute
# key/value pairs, and the markup it reads is this project's own templates,
# not arbitrary third-party HTML.
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<([a-zA-Z][a-zA-Z0-9]*)\b((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>")
_ATTR_RE = re.compile(
    r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)')"""
)

#: URL names that open a form which changes a record, matched as a substring
#: of the resolved ``view_name`` (app namespace included, e.g.
#: ``accounting:ledger_create``). Deliberately a plain-English word list rather
#: than a per-app enumeration, same reasoning as ``checks.py``'s own vocabulary
#: table: one declared pattern per verb, checked against the URL name a link
#: actually resolves to, rather than trusted-by-assumption.
_WRITE_URL_NAME_HINTS = re.compile(
    r"(create|add|_edit$|edit_|upload|import|assign|remove|finalize|delete"
    r"|_toggle$|_move$|_config$|onboard|link_right|mark_removed|share$)",
    re.IGNORECASE,
)

#: Attributes that unconditionally carry an unsafe request. Present on any tag,
#: not just ``<form>`` (a plain button can carry ``hx-post`` directly).
_HX_UNSAFE_ATTRS = ("hx-post", "hx-patch", "hx-put", "hx-delete")

#: Attributes whose value is a navigation target, checked against the write
#: URL-name hints above rather than treated as unsafe on their own (a GET to a
#: list or a detail page is not a write).
_LINK_ATTRS = ("href", "hx-get")


def _parse_attrs(raw):
    attrs = {}
    for match in _ATTR_RE.finditer(raw):
        name = match.group(1).lower()
        value = match.group(2) if match.group(2) is not None else match.group(3)
        attrs[name] = value
    return attrs


def _resolve_view_name(target, page_path):
    """Resolve a form action / href / hx-* target to a URL name, or None.

    A blank form action posts to the page's own path. Anything not shaped like
    an internal path (``#foo``, ``javascript:...``, ``mailto:``, an external
    ``http(s)://``) resolves to nothing, same as a target Django itself cannot
    match.
    """
    target = (target or "").strip()
    if not target:
        target = page_path
    if not target.startswith("/"):
        return None
    path = target.split("?", 1)[0].split("#", 1)[0]
    try:
        return resolve(path).view_name
    except Resolver404:
        return None


def find_write_controls(html, page_path):
    """Every write control in ``html``, as ``(attr, view_name)`` tuples.

    ``view_name`` is ``None`` when the target could not be resolved (an
    external link, an anchor, a target no URLconf matches): those never carry
    a write, so they are never offenders, and are dropped by the caller instead
    of being returned as unresolvable findings.
    """
    findings = []
    for tag_match in _TAG_RE.finditer(html):
        tag = tag_match.group(1).lower()
        attrs = _parse_attrs(tag_match.group(2))

        if tag == "form":
            method = (attrs.get("method") or "get").strip().lower()
            if method == "post":
                view_name = _resolve_view_name(attrs.get("action"), page_path)
                findings.append(("form method=post", view_name))

        for hx_attr in _HX_UNSAFE_ATTRS:
            if hx_attr in attrs:
                view_name = _resolve_view_name(attrs[hx_attr], page_path)
                findings.append((hx_attr, view_name))

        for link_attr in _LINK_ATTRS:
            if link_attr in attrs:
                view_name = _resolve_view_name(attrs[link_attr], page_path)
                if view_name and _WRITE_URL_NAME_HINTS.search(view_name):
                    findings.append((link_attr, view_name))

    return findings


def _offenders(html, page_path):
    offenders = []
    for attr, view_name in find_write_controls(html, page_path):
        if view_name is None:
            # A form/hx-* target that resolved to nothing is not analyzable:
            # record it too, rather than silently letting an unresolvable
            # action hide a real write (a typo'd action attribute, a target
            # this test's own settings do not route, is a defect either way).
            offenders.append((attr, "<unresolved: check the target by hand>"))
            continue
        if not viewer_may_post(view_name):
            offenders.append((attr, view_name))
    return offenders


# ---------------------------------------------------------------------------
# The walk.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("access_control_enforced", [False, True])
def test_viewer_sees_no_write_control_on_any_page(access_control_enforced):
    rows = _seed_rows()
    viewer = User.objects.create_user(
        username="write-control-viewer",
        email="write-control-viewer@example.org",
        password="a-good-passw0rd",
        is_active=True,
        read_only=True,
    )
    client = Client()
    client.force_login(viewer)

    pages = list(KEPT_PAGES) + [path for path, _label in _detail_pages(rows)]

    failures = []
    with override_settings(ACCESS_CONTROL_ENFORCED=access_control_enforced):
        for page_path in pages:
            response = client.get(page_path)
            if response.status_code != 200:
                # A redirect (302, an admin-only screen under enforcement) or a
                # not-found leaves nothing to scan; the middleware and
                # admin_required tests already cover those refusals.
                continue
            html = response.content.decode("utf-8", errors="replace")
            for attr, view_name in _offenders(html, page_path):
                failures.append(
                    f"{page_path}: <{attr}> -> {view_name} "
                    f"(ACCESS_CONTROL_ENFORCED={access_control_enforced})"
                )

    assert not failures, (
        "Viewer sees a write control on the following pages "
        "(page: attribute -> resolved URL name):\n" + "\n".join(sorted(failures))
    )


def test_an_administrator_sees_the_finalize_control_and_an_operator_does_not():
    """The guard hides controls from a viewer; it must not hide them from an
    administrator. 147-02 Task 3 narrowed the finalize/reopen control from
    "anyone who can write" to administrators only (``user_is_admin``), so an
    operator -- who could see it before that task -- no longer does. This is
    the same page ``test_viewer_sees_no_write_control_on_any_page`` proves is
    also clear of the control for a viewer.
    """
    rows = _seed_rows()
    administrator = User.objects.create_user(
        username="write-control-administrator",
        email="write-control-administrator@example.org",
        password="a-good-passw0rd",
        is_active=True,
        agency_admin=True,
    )
    operator = User.objects.create_user(
        username="write-control-operator",
        email="write-control-operator@example.org",
        password="a-good-passw0rd",
        is_active=True,
    )
    period_url = "/accounting/reporting-periods/%d/" % rows["open_period"].pk

    admin_client = Client()
    admin_client.force_login(administrator)
    admin_response = admin_client.get(period_url)
    assert admin_response.status_code == 200
    assert "Finalize period" in admin_response.content.decode()

    operator_client = Client()
    operator_client.force_login(operator)
    operator_response = operator_client.get(period_url)
    assert operator_response.status_code == 200
    assert "Finalize period" not in operator_response.content.decode()
