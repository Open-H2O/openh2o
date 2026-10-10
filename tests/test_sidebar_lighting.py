# SPDX-License-Identifier: AGPL-3.0-or-later
"""The sidebar's lighting rule: every signed-in page lights exactly one entry.

Plan 150-03 Task 2, written test-first from the lighting table in
``.planning/phases/150-water-first-screens/page-verdict/READER-TASKS-150-03.md``
(every URL pattern rendered through the product in both sidebar modes, measured
2026-10-09) and from Brent's six sidebar register rows in
``docs/reading-register-2026-09.md``: R-028 (pages that light nothing), R-145
(the lit entry is below the fold), R-012 (crumbs rooted at a word the sidebar
never shows), R-013 (the onboarding entry's name), R-098 (Map and Zones lit at
once) and R-072 (the onboarding points page).

The rule, as settled in the plan:

1. Every signed-in page that renders the sidebar lights exactly ONE entry. Each
   entry owns path prefixes (its own ``active_match`` plus ``also_matches``) and
   may exclude some; the winner is the LONGEST owning prefix, so ``/map/zones/``
   lights Zones and not Map, and ``/`` lights Home only.
2. When the lit entry sits in the Administration section and the stored mode
   is Operations, that page renders the sidebar in Admin mode WITHOUT changing
   the stored ``nav_mode`` cookie; the next request is back in Operations.
3. Pages with no entry by design light none and are on ``NO_ENTRY_BY_DESIGN``
   with a reason. Responses with no sidebar (JSON, GeoJSON, CSV, HTMX
   partials), redirects and non-GET endpoints (405, 400) are outside the rule.
4. The lit entry is scrolled into view on load.
5. A page's crumb root is a word the sidebar shows: the section label of the
   lit entry, or the entry itself for the unlabelled first section (Home,
   Dashboard, Map).
6. "Onboard System" reads "Add a water system" and "Recharge Areas" reads
   "Recharge sites", on the sidebar and on the pages they open.

The expected outcome is literal data (``EXPECTED_LIT``, ``SECTION_OF``,
``NO_ENTRY_BY_DESIGN``): the test never re-derives which entry should win from
the registry, it only reads what the product rendered.

The pure resolver this test expects the product to gain::

    core.modules.lit_entry(path: str, entries: Iterable[NavEntry]) -> NavEntry | None

It returns the entry owning the longest prefix of ``path`` among each entry's
``active_match`` and its new ``also_matches: tuple = ()`` field, skipping an
entry any of whose ``active_excludes`` is a prefix of ``path``; an entry whose
``active_match`` is ``"/"`` owns ``"/"`` exactly and nothing else; ``None``
when no entry owns the path. Its result must not depend on the order of
``entries``.

Representative paths are built the way the Task 1 measurement built them
(``tools/lighting.py``): every pattern from Django's resolver, each converter
filled from one row of the right kind, fetched with the test client as a
signed-in superuser with the ``nav_mode`` cookie at ``operations`` and at
``admin``. Here the rows come from the factories, not the demonstration data.
"""
import re
from html import unescape
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from core.modules import SECTION_WATER_DATA

pytestmark = pytest.mark.django_db

MODES = ("operations", "admin")

# -- The expected outcome, as literal data -------------------------------------

#: Every URL pattern that renders the sidebar, and the ONE entry it lights.
#: The keys are the resolver's own pattern strings (the first column of the
#: Task 1 table). A pattern that renders the sidebar and is missing here fails
#: ``test_every_route_is_in_the_tables_or_outside_the_rule``.
EXPECTED_LIT = {
    "/": "Home",
    "/about/": "About",
    "/about/demonstration-data/": "About",
    "/accounting/accounts/": "Accounts",
    "/accounting/accounts/<int:pk>/": "Accounts",
    "/accounting/accounts/<int:pk>/edit/": "Accounts",
    "/accounting/accounts/create/": "Accounts",
    "/accounting/allocations/": "Allocations",
    "/accounting/allocations/create/": "Allocations",
    "/accounting/calculation-run/<int:parcel_id>/<str:period>/": "Dashboard",
    "/accounting/dashboard/": "Dashboard",
    "/accounting/delivery-settings/": "Delivery Settings",
    "/accounting/ledger/": "Use Ledger",
    "/accounting/ledger/create/": "Use Ledger",
    "/accounting/ledger/upload/": "Use Ledger",
    "/accounting/methodology/": "Methodology",
    "/accounting/reporting-periods/": "Water Years",
    "/accounting/reporting-periods/<int:pk>/": "Water Years",
    "/accounting/reporting-periods/create/": "Water Years",
    "/datasync/monitoring/": "Monitoring Stations",
    "/datasync/stations/": "Monitoring Stations",
    "/datasync/stations/<int:pk>/": "Monitoring Stations",
    "/datasync/stations/add/": "Monitoring Stations",
    "/drinking/": "Drinking Water",
    "/drinking/facilities/": "Facilities",
    "/drinking/facilities/<int:pk>/": "Facilities",
    "/drinking/facilities/<int:pk>/edit/": "Facilities",
    "/drinking/facilities/add/": "Facilities",
    "/drinking/import/": "Drinking Water",
    "/drinking/onboard/": "Add a water system",
    "/drinking/onboard/<str:pwsid>/points/": "Add a water system",
    "/drinking/production/": "Production",
    "/drinking/production/add/": "Production",
    "/drinking/production/import/": "Production",
    "/drinking/results/": "Sample Results",
    "/drinking/results/<int:pk>/": "Sample Results",
    "/drinking/sampling-points/": "Sampling Points",
    "/drinking/sampling-points/<int:pk>/": "Sampling Points",
    "/drinking/schedule/": "Schedule",
    "/drinking/schedule/<int:pk>/edit/": "Schedule",
    "/drinking/schedule/add/": "Schedule",
    "/health/": "Site Health",
    "/help/budgets-allocations/": "Settings explained",
    "/help/getting-started/": "Getting Started",
    "/help/glossary/": "Glossary",
    "/help/methods/": "Methods behind the numbers",
    "/help/settings/": "Settings explained",
    "/help/surface-deliveries/": "Settings explained",
    "/help/water-balances/": "How water balances work",
    "/infrastructure/add/": "Infrastructure",
    "/infrastructure/import/": "Infrastructure",
    "/map/": "Map",
    "/map/zones/": "Zones",
    "/map/zones/<int:pk>/": "Zones",
    "/map/zones/<int:pk>/edit/": "Zones",
    "/map/zones/create/": "Zones",
    "/parcels/": "Use Areas",
    "/parcels/<int:pk>/": "Use Areas",
    "/recharge/": "Recharge sites",
    "/recharge/<int:pk>/": "Recharge sites",
    "/reporting/reports/": "Reports",
    "/reporting/reports/<int:pk>/": "Reports",
    "/reporting/reports/<int:pk>/calwatrs-worksheet/": "Reports",
    "/reporting/reports/<int:pk>/prefill/": "Reports",
    "/reporting/reports/generate/": "Reports",
    "/reporting/reports/shared-supply-check/": "Reports",
    "/setup/": "Setup Wizard",
    "/surface/": "Surface Diversions",
    "/surface/curtailments/": "Curtailment Orders",
    "/surface/curtailments/<int:pk>/edit/": "Curtailment Orders",
    "/surface/curtailments/add/": "Curtailment Orders",
    "/surface/device/<int:pk>/edit/": "Surface Diversions",
    "/surface/diversion/<int:pk>/": "Surface Diversions",
    "/surface/diversion/<int:pk>/device/add/": "Surface Diversions",
    "/surface/diversion/<int:pk>/edit/": "Surface Diversions",
    "/surface/diversion/import/": "Surface Diversions",
    "/surface/rights/": "Water Rights",
    "/surface/rights/<int:pk>/": "Water Rights",
    "/surface/rights/<int:pk>/edit/": "Water Rights",
    "/surface/rights/add/": "Water Rights",
    "/surface/rights/import/": "Water Rights",
    "/users/": "Users",
    "/users/add/": "Users",
    "/wells/": "Wells",
    "/wells/<int:pk>/": "Wells",
}

#: Pages with no sidebar entry by design: (why, the crumb root they carry).
#: A crumb root of None means the response is outside the rule today (a
#: partial or a redirect); if it ever renders the sidebar it must light none.
NO_ENTRY_BY_DESIGN = {
    "/profile/": (
        "your own account, opened from the account menu, not the sidebar",
        "Home",
    ),
    "/changes/": (
        "reached from the Users page only (147-02, Brent's checkpoint ruling)",
        "Administration",
    ),
    "/search/": ("the search box's results, not a place in the sidebar", None),
    "/id/<slug:kind>/<int:pk>/": (
        "a permanent identifier that redirects to the record's own page",
        None,
    ),
}

#: Patterns this walk does not request at all, with the reason.
NOT_REQUESTED = {
    "/feedback/attachment/<int:pk>/": "streams an uploaded screenshot file to staff, never a page",
    "/reporting/reports/<int:pk>/download/": (
        "streams a generated report file, never a page; a draft has no file, so it 404s"
    ),
}

#: Pages with no crumb trail at all.
PAGES_WITHOUT_A_CRUMB = {"/": "the home page is the top of every trail"}

#: Where each entry sits in the sidebar: the section heading it renders under,
#: or "" for the unlabelled first section. ``test_the_sidebar_is_arranged_as_
#: the_table_says`` holds this against the rendered sidebar.
SECTION_OF = {
    "Home": "",
    "Dashboard": "",
    "Map": "",
    "Use Ledger": "Water Data",
    "Use Areas": "Water Data",
    "Wells": "Water Data",
    "Surface Diversions": "Water Data",
    "Recharge sites": "Water Data",
    "Monitoring Stations": "Water Data",
    "Infrastructure": "Water Data",
    "Drinking Water": "Water Data",
    "Facilities": "Water Data",
    "Sampling Points": "Water Data",
    "Sample Results": "Water Data",
    "Production": "Water Data",
    "Schedule": "Water Data",
    "Add a water system": "Water Data",
    "Water Rights": "Administration",
    "Curtailment Orders": "Administration",
    "Accounts": "Administration",
    "Water Years": "Administration",
    "Allocations": "Administration",
    "Zones": "Administration",
    "Users": "Administration",
    "Methodology": "Administration",
    "Delivery Settings": "Administration",
    "Site Health": "Administration",
    "Setup Wizard": "Administration",
    "Reports": "Reporting",
    "Getting Started": "Help",
    "How water balances work": "Help",
    "Methods behind the numbers": "Help",
    "Settings explained": "Help",
    "Glossary": "Help",
    "About": "Help",
}

#: The two retired names (rule 6).
RETIRED_LABELS = ("Onboard System", "Recharge Areas", "Recharge areas")

ADMINISTRATION = "Administration"

#: The sidebar pages whose entry sits in Administration (rule 2).
ADMIN_SECTION_PATTERNS = sorted(
    p for p, label in EXPECTED_LIT.items() if SECTION_OF[label] == ADMINISTRATION
)

#: Statuses a route outside the rule may answer a plain GET with.
OUTSIDE_THE_RULE_STATUSES = (200, 301, 302, 303, 400, 405, 503)


# -- Reading the rendered page -------------------------------------------------

_SIDEBAR = re.compile(r'<aside id="sidebar".*?</aside>', re.S)
_SIDEBAR_TOKEN = re.compile(
    r'class="sidebar-link-text sidebar-section-label">([^<]+)</span>'
    r'|<a\s[^>]*class="sidebar-link( active)?"[^>]*>.*?'
    r'<span class="sidebar-link-text">([^<]+)</span>',
    re.S,
)
_CRUMB_NAV = re.compile(r'<nav class="breadcrumb"[^>]*>(.*?)</nav>', re.S)
_TAG = re.compile(r"<[^>]+>")
_H1 = re.compile(r'<h1 class="page-title">(.*?)</h1>', re.S)
_TITLE = re.compile(r"<title>(.*?)</title>", re.S)
_SCRIPT = re.compile(r"<script[^>]*>(.*?)</script>", re.S)
_WHERE_CELL = re.compile(r'<td class="col-where">(.*?)(?:<br|</td>)', re.S)


def _text(fragment):
    return re.sub(r"\s+", " ", unescape(_TAG.sub("", fragment))).strip()


def sidebar_links(html):
    """Every sidebar link as (section heading, label, lit), top to bottom."""
    aside = _SIDEBAR.search(html)
    assert aside, "the page has no sidebar"
    section, links = "", []
    for token in _SIDEBAR_TOKEN.finditer(aside.group(0)):
        if token.group(1) is not None:
            section = _text(token.group(1))
        else:
            links.append((section, _text(token.group(3)), bool(token.group(2))))
    return links


def lit(html):
    return [(section, label) for section, label, active in sidebar_links(html) if active]


def sections_shown(html):
    return {section for section, _label, _active in sidebar_links(html) if section}


def crumb_trail(html):
    """The breadcrumb's items, separators dropped; [] when the page has none."""
    nav = _CRUMB_NAV.search(html)
    if not nav:
        return []
    items = re.findall(r">([^<>]+)<", ">" + nav.group(1) + "<")
    return [t for t in (_text(i) for i in items) if t and t != "/"]


def page_head(html):
    match = _H1.search(html)
    return _text(match.group(1)) if match else ""


def page_title(html):
    match = _TITLE.search(html)
    return _text(match.group(1)) if match else ""


def is_sidebar_page(response):
    return (
        response.status_code == 200
        and "text/html" in response.get("Content-Type", "")
        and 'id="sidebar"' in response.content.decode("utf-8", "replace")
    )


# -- One row of each kind a URL converter needs ----------------------------------


@pytest.fixture
def walk():
    """The fixture the walk renders against: one row per converter, a superuser."""
    from accounting.models import CalculationPlan, CalculationRun, CalculationStep
    from drinking.models import SamplingSchedule
    from surface.models import CurtailmentOrder, MeasuringDevice, PointOfDiversionDevice
    from tests.factories import (
        DiversionRecordFactory,
        MonitoredStationFactory,
        ParcelFactory,
        ParcelZoneFactory,
        PointOfDiversionFactory,
        PointOfDiversionParcelFactory,
        RechargeSiteFactory,
        ReportingPeriodFactory,
        ReportSubmissionFactory,
        SampleResultFactory,
        SamplingPointFactory,
        SystemFacilityFactory,
        WaterAccountFactory,
        WaterAccountParcelFactory,
        WaterRightFactory,
        WaterRightParcelFactory,
        WaterSystemFactory,
        WellFactory,
        WellIrrigatedParcelFactory,
        ZoneFactory,
    )
    from datetime import date
    from decimal import Decimal

    rows = SimpleNamespace()
    rows.parcel = ParcelFactory(parcel_number="LIGHT-APN-001")
    rows.zone = ZoneFactory()
    rows.parcel_zone = ParcelZoneFactory(parcel=rows.parcel, zone=rows.zone)
    rows.well = WellFactory()
    rows.well_parcel = WellIrrigatedParcelFactory(well=rows.well, parcel=rows.parcel)
    rows.account = WaterAccountFactory()
    rows.account_parcel = WaterAccountParcelFactory(
        water_account=rows.account, parcel=rows.parcel
    )
    rows.period = ReportingPeriodFactory()
    plan = CalculationPlan.objects.create(name="Lighting walk", is_active=False)
    rows.step = CalculationStep.objects.create(
        plan=plan, order=1, step_type="et_gross", enabled=True,
        config={"model": "Ensemble", "variable": "ET"}, label="gross",
    )
    # The calculation receipt, in the shape tests/test_calculation_receipt.py
    # builds: a well month charged to groundwater.
    rows.run = CalculationRun.objects.create(
        parcel=rows.parcel,
        period="2024-06",
        gross_et_af=Decimal("10.0000"),
        net_consumptive_use_af=Decimal("9.0000"),
        effective_precip_af=Decimal("1.0000"),
        surface_delivered_af=Decimal("5.3333"),
        surface_efficiency=Decimal("0.750"),
        surface_water_af=Decimal("4.0000"),
        final_af=Decimal("5.0000"),
        gw_extracted_af=Decimal("6.2500"),
        over_delivery_af=Decimal("0.0000"),
        residual_disposition="groundwater",
        breakdown=[{
            "step_type": "subtract_surface_water",
            "label": "Subtract canal water the crop could use",
            "detail": {
                "delivered_af": "5.3333",
                "efficiency": "0.750",
                "efficiency_source": "agency",
                "consumed_af": "4.0000",
                "surface_water_af": "4.0000",
            },
            "input_af": "9.0000",
            "output_af": "5.0000",
        }],
        methodology_plan_name="Lighting walk",
    )
    rows.station = MonitoredStationFactory()
    rows.right = WaterRightFactory()
    rows.right_parcel = WaterRightParcelFactory(water_right=rows.right, parcel=rows.parcel)
    rows.pod = PointOfDiversionFactory(water_right=rows.right)
    rows.pod_parcel = PointOfDiversionParcelFactory(
        point_of_diversion=rows.pod, parcel=rows.parcel
    )
    rows.record = DiversionRecordFactory(point_of_diversion=rows.pod)
    rows.device = MeasuringDevice.objects.create(
        nickname="Lighting gate meter", device_type="inline_flow_meter"
    )
    PointOfDiversionDevice.objects.create(
        point_of_diversion=rows.pod, device=rows.device, is_current=True
    )
    rows.curtailment = CurtailmentOrder.objects.create(
        order_id="LIGHT-2026-01",
        title="A lighting walk order",
        effective_date=date(2026, 1, 1),
        watershed="MERCED RIVER",
        priority_date_cutoff=date(1930, 1, 1),
        status="active",
    )
    rows.recharge_site = RechargeSiteFactory()
    rows.report = ReportSubmissionFactory(reporting_period=rows.period)
    rows.system = WaterSystemFactory()
    rows.facility = SystemFacilityFactory(system=rows.system)
    rows.sampling_point = SamplingPointFactory(facility=rows.facility)
    rows.result = SampleResultFactory(event__sampling_point=rows.sampling_point)
    rows.schedule = SamplingSchedule.objects.create(
        system=rows.system, frequency="monthly", group_label="Coliform"
    )
    rows.user = get_user_model().objects.create_user(
        username="lighting-walk",
        email="lighting-walk@example.org",
        password="a-good-passw0rd",
        is_active=True,
        is_staff=True,
        is_superuser=True,
    )
    return rows


#: Which row fills ``<int:pk>``, by the pattern's prefix.
PK_ROW_BY_PREFIX = (
    ("/accounting/accounts/", "account"),
    ("/accounting/reporting-periods/", "period"),
    ("/datasync/stations/", "station"),
    ("/drinking/facilities/", "facility"),
    ("/drinking/results/", "result"),
    ("/drinking/sampling-points/", "sampling_point"),
    ("/drinking/schedule/", "schedule"),
    ("/id/", "parcel"),
    ("/map/zones/", "zone"),
    ("/parcels/", "parcel"),
    ("/recharge/", "recharge_site"),
    ("/reporting/reports/", "report"),
    ("/surface/curtailments/", "curtailment"),
    ("/surface/device/", "device"),
    ("/surface/diversion/", "pod"),
    ("/surface/rights/", "right"),
    ("/users/", "user"),
    ("/wells/", "well"),
)


def concrete(pattern, rows):
    """The representative path for a resolver pattern, from the fixture's rows."""
    values = {
        "parcel_id": rows.run.parcel_id,
        "period": rows.run.period,
        "step_id": rows.step.pk,
        "direction": "down",
        "pwsid": rows.system.pwsid,
        "kind": "use-area",
        "wap_pk": rows.account_parcel.pk,
        "pz_pk": rows.parcel_zone.pk,
        "pp_pk": rows.pod_parcel.pk,
        "rpk": rows.record.pk,
        "wrp_pk": rows.right_parcel.pk,
        "wip_pk": rows.well_parcel.pk,
    }
    pk_rows = [attr for prefix, attr in PK_ROW_BY_PREFIX if pattern.startswith(prefix)]
    if pk_rows:
        values["pk"] = getattr(rows, pk_rows[0]).pk

    def fill(match):
        name = match.group(1)
        if name not in values:
            pytest.fail(f"no fixture row fills <{name}> in {pattern}; add one to `walk`")
        return str(values[name])

    return re.sub(r"<(?:\w+:)?(\w+)>", fill, pattern)


def live_patterns():
    """Every route outside the admin, sign-in and static trees, as the resolver
    spells it (the same walk as ``tools/lighting.py``)."""
    from django.urls import URLPattern, URLResolver, get_resolver

    found = []

    def walk_resolver(resolver, prefix=""):
        for p in resolver.url_patterns:
            if isinstance(p, URLResolver):
                walk_resolver(p, prefix + str(p.pattern))
            elif isinstance(p, URLPattern):
                found.append(prefix + str(p.pattern))

    walk_resolver(get_resolver())
    patterns = {"/" + p.lstrip("^").replace("\\Z", "").replace("$", "") for p in found}
    return sorted(
        p for p in patterns
        if not p.startswith(("/admin", "/static", "/media", "/__debug__", "/accounts/"))
    )


def client_in(user, mode):
    client = Client()
    client.force_login(user)
    client.cookies["nav_mode"] = mode
    return client


def sidebar_page(rows, pattern, mode):
    """GET the pattern's representative path; return (client, response, html),
    failing unless it is a 200 HTML page carrying the sidebar."""
    client = client_in(rows.user, mode)
    path = concrete(pattern, rows)
    response = client.get(path)
    assert is_sidebar_page(response), (
        f"{pattern} ({path}, {mode}) answered {response.status_code} "
        f"{response.get('Content-Type', '')!r} without the sidebar; it is a "
        f"sidebar page in the Task 1 table"
    )
    return client, response, response.content.decode("utf-8", "replace")


# -- Rule 1 and 3: exactly one entry, the right one ---------------------------------


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("pattern", sorted(EXPECTED_LIT))
def test_a_sidebar_page_lights_exactly_one_entry(walk, pattern, mode):
    """R-028 (nothing lit in Operations), R-098 (two lit at once), R-072."""
    _client, _response, html = sidebar_page(walk, pattern, mode)
    expected = EXPECTED_LIT[pattern]
    labels = [label for _section, label in lit(html)]
    assert labels == [expected], (
        f"{pattern} in {mode} mode lights {labels or 'nothing'}; "
        f"it must light exactly {expected!r}"
    )
    # The section the sidebar shows it under, and Administration only when
    # the lit entry lives there (rule 2 is per page, never sticky).
    (section, _label), = lit(html)
    assert section == SECTION_OF[expected], (
        f"{pattern}: {expected!r} renders under {section or 'no heading'!r}, "
        f"the table says {SECTION_OF[expected] or 'no heading'!r}"
    )
    if mode == "operations":
        shown = ADMINISTRATION in sections_shown(html)
        assert shown == (SECTION_OF[expected] == ADMINISTRATION), (
            f"{pattern} in Operations mode "
            f"{'shows' if shown else 'hides'} the Administration section"
        )


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("pattern", sorted(NO_ENTRY_BY_DESIGN))
def test_a_page_with_no_entry_by_design_lights_none(walk, pattern, mode):
    client = client_in(walk.user, mode)
    response = client.get(concrete(pattern, walk))
    if not is_sidebar_page(response):
        assert response.status_code in OUTSIDE_THE_RULE_STATUSES, (
            f"{pattern} answered {response.status_code}"
        )
        return
    html = response.content.decode("utf-8", "replace")
    assert lit(html) == [], f"{pattern} is on the no-entry list and lights {lit(html)}"
    _reason, root = NO_ENTRY_BY_DESIGN[pattern]
    assert root is not None, f"{pattern} now renders the sidebar; give it a crumb root here"
    trail = crumb_trail(html)
    assert trail and trail[0] == root, (
        f"{pattern}'s crumb starts {trail[:1]}; it is reached from {root!r}"
    )


def test_every_route_is_in_the_tables_or_outside_the_rule(walk):
    """No route renders the sidebar without a row in the tables, no row in the
    tables names a route that no longer exists, and no route the fixture
    should fill answers 404 or 500."""
    live = live_patterns()
    listed = set(EXPECTED_LIT) | set(NO_ENTRY_BY_DESIGN) | set(NOT_REQUESTED)
    stale = sorted(listed - set(live))
    assert not stale, f"rows for routes that no longer exist: {stale}"

    unlisted_pages, broken = [], []
    for pattern in live:
        if pattern in listed:
            continue
        response = client_in(walk.user, "admin").get(concrete(pattern, walk))
        if is_sidebar_page(response):
            unlisted_pages.append(pattern)
        elif response.status_code not in OUTSIDE_THE_RULE_STATUSES:
            broken.append(f"{pattern} -> {response.status_code}")
    assert not unlisted_pages, (
        f"these render the sidebar and have no row in EXPECTED_LIT or "
        f"NO_ENTRY_BY_DESIGN: {unlisted_pages}"
    )
    assert not broken, f"these answered an unexpected status: {broken}"


# -- Rule 2: an Administration page shows Administration, once ------------------------


@pytest.mark.parametrize("pattern", ADMIN_SECTION_PATTERNS)
def test_an_administration_page_shows_its_section_without_changing_the_mode(walk, pattern):
    """R-028 and ISS-182's half: in Operations mode, Water Rights, Accounts,
    Water Years and the rest render the Administration section with their
    entry lit, the stored cookie is left alone, and the next page is back in
    Operations."""
    client, response, html = sidebar_page(walk, pattern, "operations")
    assert ADMINISTRATION in sections_shown(html), (
        f"{pattern} in Operations mode hides the Administration section its "
        f"entry ({EXPECTED_LIT[pattern]!r}) lives in"
    )
    assert "nav_mode" not in response.cookies, (
        f"{pattern} rewrote the stored nav_mode cookie; the override is per request"
    )
    after = client.get("/")
    assert client.cookies["nav_mode"].value == "operations"
    assert ADMINISTRATION not in sections_shown(after.content.decode()), (
        f"the page after {pattern} is still in Admin mode"
    )


# -- Rule 5: the crumb root is a word the sidebar shows ------------------------------


@pytest.mark.parametrize("pattern", sorted(EXPECTED_LIT))
def test_the_crumb_starts_with_the_sidebar_word_for_the_page(walk, pattern):
    """R-012: "Accounting", "Compliance", "Home" on Administration pages,
    "Wells" on the infrastructure pages, "Setup Wizard" on /setup/, and the
    calculation receipt rooted apart from the Dashboard it belongs to."""
    _client, _response, html = sidebar_page(walk, pattern, "admin")
    trail = crumb_trail(html)
    if pattern in PAGES_WITHOUT_A_CRUMB:
        assert trail == [], f"{pattern} grew a crumb trail: {trail}"
        return
    entry = EXPECTED_LIT[pattern]
    root = SECTION_OF[entry] or entry
    assert trail, f"{pattern} has no crumb trail"
    assert trail[0] == root, (
        f"{pattern}'s crumb starts {trail[0]!r}; the sidebar shows this page "
        f"as {entry!r} under {SECTION_OF[entry] or 'the unlabelled first section'}, "
        f"so the crumb starts {root!r}"
    )


# -- Rule 4: the lit entry is scrolled into view ----------------------------------------


def test_the_lit_entry_is_scrolled_into_view_on_load(walk):
    """R-145: on Getting Started, Settings explained, Glossary and About the lit
    entry sat below the sidebar's visible box at 1,440 x 900 and nothing
    scrolled it up."""
    _client, _response, html = sidebar_page(walk, "/help/glossary/", "admin")
    nearest = re.compile(r"scrollIntoView\(\s*\{\s*block:\s*['\"]nearest['\"]\s*\}\s*\)")
    scripts = [s for s in _SCRIPT.findall(html) if "sidebar" in s and "active" in s]
    assert any(nearest.search(s) for s in scripts), (
        "no sidebar script scrolls the active link into view "
        "(scrollIntoView({block: 'nearest'}))"
    )


# -- Rule 6: the names --------------------------------------------------------------------


def test_the_sidebar_is_arranged_as_the_table_says(walk):
    """Every rendered entry sits under the section SECTION_OF names, every
    entry in the table is rendered, and the two retired names are gone (R-013,
    and "Recharge Areas" against "recharge site" everywhere else)."""
    _client, _response, html = sidebar_page(walk, "/", "admin")
    rendered = [(section, label) for section, label, _active in sidebar_links(html)]
    labels = [label for _section, label in rendered]
    for retired in RETIRED_LABELS:
        assert retired not in labels, f"the sidebar still says {retired!r}"
    unknown = [label for label in labels if label not in SECTION_OF]
    assert not unknown, f"entries with no row in SECTION_OF: {unknown}"
    misplaced = [
        (label, section) for section, label in rendered if SECTION_OF[label] != section
    ]
    assert not misplaced, f"entries under a different heading than the table says: {misplaced}"
    missing = sorted(set(SECTION_OF) - set(labels))
    assert not missing, f"entries the table names that the sidebar does not render: {missing}"


def test_the_onboarding_pages_say_add_a_water_system(walk):
    """R-013 and R-072: the entry, the page head, the tab title and the crumb
    say the same thing, and the points page's crumb leads back to it by name."""
    _client, _response, html = sidebar_page(walk, "/drinking/onboard/", "admin")
    assert page_head(html) == "Add a water system"
    assert page_title(html).startswith("Add a water system")
    assert crumb_trail(html)[-1] == "Add a water system"

    _client, _response, points = sidebar_page(
        walk, "/drinking/onboard/<str:pwsid>/points/", "admin"
    )
    assert "Add a water system" in crumb_trail(points), crumb_trail(points)
    assert "Onboard" not in crumb_trail(points), crumb_trail(points)


def test_the_recharge_list_says_recharge_sites(walk):
    _client, _response, html = sidebar_page(walk, "/recharge/", "admin")
    assert page_head(html) == "Recharge sites"
    assert page_title(html).startswith("Recharge sites")
    assert crumb_trail(html)[-1] == "Recharge sites"


def test_getting_started_points_at_entries_the_sidebar_shows(walk):
    """Each Where cell reads "<section> > <entry>[ and <entry>]"; every name in
    it must be an entry the sidebar renders under that heading, so the cell
    follows a rename instead of pointing at a word that is gone."""
    _client, _response, html = sidebar_page(walk, "/help/getting-started/", "admin")
    shown = {(section, label) for section, label, _active in sidebar_links(html)}
    cells = [_text(cell) for cell in _WHERE_CELL.findall(html)]
    assert cells, "Getting Started has no Where cells"
    wrong = []
    for cell in cells:
        section, _sep, names = cell.partition(" > ")
        for name in names.split(" and "):
            if (section, name.strip()) not in shown:
                wrong.append(cell)
    assert not wrong, f"Where cells naming no entry the sidebar shows: {wrong}"
    assert any("Recharge sites" in cell for cell in cells), cells


# -- The resolver the product gains -----------------------------------------------------


def _entry(label, match, also=(), excludes=()):
    from core.modules import NavEntry

    return NavEntry(
        url_name=f"x:{label}", label=label, icon=label.lower(),
        section=SECTION_WATER_DATA, order=10, active_match=match,
        also_matches=also, active_excludes=excludes,
    )


def test_lit_entry_picks_the_longest_owning_prefix():
    from core.modules import lit_entry

    home = _entry("Home", "/")
    map_ = _entry("Map", "/map/")
    zones = _entry("Zones", "/map/zones/")
    dashboard = _entry(
        "Dashboard", "/accounting/dashboard/", also=("/accounting/calculation-run/",)
    )
    surface = _entry("Surface Diversions", "/surface/")
    rights = _entry("Water Rights", "/surface/rights/")
    onboard = _entry("Add a water system", "/drinking/onboard/")
    points = _entry("Sampling Points", "/drinking/sampling-points/")
    entries = [home, map_, zones, dashboard, surface, rights, onboard, points]

    assert lit_entry("/map/", entries) is map_
    assert lit_entry("/map/zones/", entries) is zones
    assert lit_entry("/map/zones/4/edit/", entries) is zones
    assert lit_entry("/accounting/calculation-run/7/2024-06/", entries) is dashboard
    assert lit_entry("/surface/diversion/3/", entries) is surface
    assert lit_entry("/surface/rights/3/", entries) is rights
    assert lit_entry("/drinking/onboard/CA1900001/points/", entries) is onboard
    # The order the entries arrive in never decides the winner.
    assert lit_entry("/map/zones/", list(reversed(entries))) is zones
    assert lit_entry("/surface/rights/", list(reversed(entries))) is rights


def test_lit_entry_matches_home_exactly_and_owns_nothing_else():
    from core.modules import lit_entry

    home = _entry("Home", "/")
    wells = _entry("Wells", "/wells/")
    assert lit_entry("/", [home, wells]) is home
    assert lit_entry("/wells/", [home, wells]) is wells
    assert lit_entry("/profile/", [home, wells]) is None
    assert lit_entry("/changes/", [home, wells]) is None


def test_lit_entry_honours_excludes():
    from core.modules import lit_entry

    overview = _entry("Drinking Water", "/drinking/", excludes=("/drinking/import/",))
    production = _entry("Production", "/drinking/production/")
    assert lit_entry("/drinking/", [overview, production]) is overview
    assert lit_entry("/drinking/production/add/", [overview, production]) is production
    # An excluded path is not owned; with no other owner, nothing lights.
    assert lit_entry("/drinking/import/", [overview, production]) is None


def test_no_two_registry_entries_own_the_same_prefix():
    """Longest-prefix-wins is only a rule if no two entries tie."""
    from core.modules import enabled_modules

    owners = {}
    for spec in enabled_modules():
        for entry in spec.nav:
            for prefix in (entry.active_match, *getattr(entry, "also_matches", ())):
                owners.setdefault(prefix, []).append(entry.label)
    ties = {prefix: labels for prefix, labels in owners.items() if len(labels) > 1}
    assert not ties, f"prefixes owned by more than one entry: {ties}"
