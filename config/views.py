# SPDX-License-Identifier: AGPL-3.0-or-later
import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from datasync import freshness
from datasync.models import DataSyncLog, MonitoredStation
from geography.models import Zone
from parcels.models import Parcel
from wells.models import Well
from accounting.models import WaterAccount
from core.models import SiteConfig
from core.modules import is_enabled
from core.templatetags.prose import oxford_join


def _greeting(now):
    """Time-of-day greeting in the deployment's local timezone."""
    hour = timezone.localtime(now).hour
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


def index(request):
    """Signed-in users get the task-first home; visitors get the public landing.

    Both share the same entity counts. The home page wraps them in a Command
    Console layout: a status hero (who/where + live data health), the primary
    task cards, and the counts demoted to an at-a-glance stat bar. The public
    landing shows the same counts as the demo's headline numbers.
    """
    context = {}
    # Phase 89 puts `parcels` and `accounting` on the same footing as the four
    # below. They were the last two counts built unconditionally, and they were
    # unconditional only because the modules were pinned `required` — not
    # because a dashboard ought to assert them.
    if is_enabled("parcels"):
        context["parcel_count"] = Parcel.objects.count()
    if is_enabled("accounting"):
        context["water_account_count"] = WaterAccount.objects.count()
    # `wells` and `datasync` are demoted, not removed (Phase 88), so the imports
    # at the top of this file keep working and the tables keep answering — with
    # a truthful zero that reads as a LIE on the page: "0 Wells" says you have
    # no wells, where the honest answer is that this deployment does not track
    # them. Same reason the key is built inside the guard rather than set to
    # zero outside it: absent, so the stat card is simply not rendered.
    if is_enabled("wells"):
        context["well_count"] = Well.objects.count()
    if is_enabled("datasync"):
        context["station_count"] = MonitoredStation.objects.count()
    if is_enabled("surface"):
        # Local import: `surface` is an optional module (Phase 87), so this must
        # not run at module scope — this file was the first casualty of a
        # surface-less boot, dying here before printing a useful error. The count
        # is built inside the guard too: the stat cards that read it are guarded
        # on the same condition, so on a surface-less deployment the key is simply
        # absent rather than a misleading zero.
        from surface.models import PointOfDiversion

        context["diversion_count"] = PointOfDiversion.objects.count()
    if is_enabled("recharge"):
        # Local import: `recharge` is an optional module, so this must not run at
        # module scope (ISS-072). The count is built inside the guard too — the
        # templates that read it are guarded on the same condition, so on a
        # recharge-less deployment the key is simply absent rather than zero.
        from recharge.models import RechargeSite

        context["recharge_site_count"] = RechargeSite.objects.count()
    if not request.user.is_authenticated:
        return render(request, "index.html", context)

    # Status-hero data — every value is real, never decorative.
    now = timezone.now()
    site_config = SiteConfig.objects.first()
    context.update(
        {
            "greeting": _greeting(now),
            "agency_name": site_config.agency_name if site_config else "Your Agency",
        }
    )
    # The hero's whole status line — "N of M stations reporting · synced X ago" —
    # is datasync data. With the module off it would read "0 of 0 stations
    # reporting", which is a monitoring claim about a deployment that does no
    # monitoring. All three keys are built inside the guard, and home.html drops
    # the line when they are absent.
    if is_enabled("datasync"):
        active = list(
            MonitoredStation.objects.filter(is_active=True).select_related("data_source")
        )
        fresh_stations = sum(
            1
            for s in active
            if freshness.classify_freshness(s.data_source.code, s.last_data_at, now)
            == "fresh"
        )
        last_sync = (
            DataSyncLog.objects.filter(status__in=["success", "partial"]).first()
        )
        context.update(
            {
                "active_station_count": len(active),
                "fresh_stations": fresh_stations,
                "last_sync_time": last_sync.started_at if last_sync else None,
            }
        )
    return render(request, "home.html", context)


def set_nav_mode(request):
    """Flip the sidebar between Operations and Admin density, then return.

    A view preference, not a state change, so a plain GET link is fine. The
    value lives in a year-long cookie read by the ``nav_mode`` context
    processor; we bounce back to wherever the click came from.
    """
    mode = request.GET.get("mode", "operations")
    if mode not in ("operations", "admin"):
        mode = "operations"
    destination = request.META.get("HTTP_REFERER") or reverse("index")
    response = redirect(destination)
    response.set_cookie(
        "nav_mode", mode, max_age=60 * 60 * 24 * 365, samesite="Lax"
    )
    return response


# Global search ---------------------------------------------------------------
#
# A returning, infrequent user knows a record exists ("parcel MER-APN-014")
# but not which screen owns it. The top-bar search spans the six primary
# entities so they can jump straight there. Each entity is matched on the
# fields a user would actually type — an identifier or a name — and the top
# few hits per type link to that record's detail screen.

SEARCH_MIN_LEN = 2       # below this the dropdown stays closed (too noisy)
SEARCH_GROUP_LIMIT = 6   # max hits shown per entity type, so it stays scannable


def _search_groups(q):
    """Run the per-entity searches and return a list of result groups.

    Each group is ``{"key", "label", "results": [{"label", "sublabel", "url"}]}``;
    ``key`` selects the matching glyph in the template. Empty groups are dropped
    so the dropdown only shows entity types that actually matched.
    """
    limit = SEARCH_GROUP_LIMIT
    groups = []

    # Phase 89: the same crash site as the wells group below, and the last two
    # groups that were still unguarded. Schema-resident means the parcels tables
    # SURVIVE the demotion and keep answering the query, while
    # `reverse("parcels:detail")` raises NoReverseMatch because the routes are
    # gone. On a fresh demoted deployment the tables are empty, `if parcels:` is
    # falsy and nothing reverses — which is why this cannot be left to luck: an
    # agency that switches Use Areas off AFTER using it keeps its rows, and the
    # search box becomes a 500 on the first two characters typed. (88-02 shipped
    # exactly this defect on `wells` and 88-03 caught it on staging.)
    if is_enabled("parcels"):
        parcels = Parcel.objects.filter(
            Q(parcel_number__icontains=q) | Q(owner_name__icontains=q)
        ).order_by("parcel_number")[:limit]
        if parcels:
            groups.append({"key": "parcels", "label": "Use Areas", "results": [
                {"label": p.parcel_number, "sublabel": p.owner_name,
                 "url": reverse("parcels:detail", args=[p.pk])}
                for p in parcels
            ]})

    # Guarded, and this is a crash site rather than a cosmetic one: the tables
    # are still there under demotion and would answer the query, but
    # `reverse("wells:detail")` raises NoReverseMatch because the routes are
    # gone. A populated table plus an unregistered namespace is exactly the pair
    # that turns a search box into a 500.
    if is_enabled("wells"):
        wells = Well.objects.filter(
            Q(name__icontains=q)
            | Q(well_registration_id__icontains=q)
            | Q(wcr_number__icontains=q)
            | Q(state_well_number__icontains=q)
        ).order_by("name")[:limit]
        if wells:
            groups.append({"key": "wells", "label": "Wells", "results": [
                {"label": w.name, "sublabel": w.well_registration_id,
                 "url": reverse("wells:detail", args=[w.pk])}
                for w in wells
            ]})

    if is_enabled("surface"):
        # Local import + guard: `surface` is an optional module (Phase 87). Global
        # search is `config`, which stays enabled, so without the guard this would
        # query a missing model AND reverse a route that never registered.
        from surface.models import PointOfDiversion

        diversions = PointOfDiversion.objects.filter(
            Q(name__icontains=q) | Q(stream_name__icontains=q)
        ).order_by("name")[:limit]
        if diversions:
            groups.append({"key": "surface", "label": "Surface Diversions", "results": [
                {"label": d.name, "sublabel": d.stream_name,
                 "url": reverse("surface:pod_detail", args=[d.pk])}
                for d in diversions
            ]})

    if is_enabled("datasync"):
        # Same NoReverseMatch exposure as the wells group above.
        stations = MonitoredStation.objects.select_related("data_source").filter(
            Q(station_name__icontains=q)
            | Q(external_station_id__icontains=q)
            | Q(usgs_site_id__icontains=q)
        ).order_by("station_name")[:limit]
        if stations:
            groups.append({"key": "stations", "label": "Monitoring Stations", "results": [
                {"label": s.station_name, "sublabel": s.external_station_id,
                 "url": reverse("datasync:station_detail", args=[s.pk])}
                for s in stations
            ]})

    if is_enabled("accounting"):
        accounts = WaterAccount.objects.filter(
            Q(account_number__icontains=q) | Q(name__icontains=q)
        ).order_by("name")[:limit]
        if accounts:
            groups.append({"key": "accounts", "label": "Accounts", "results": [
                {"label": a.name, "sublabel": a.account_number,
                 "url": reverse("accounting:account_detail", args=[a.pk])}
                for a in accounts
            ]})

    zones = Zone.objects.filter(
        Q(name__icontains=q) | Q(basin_code__icontains=q)
    ).order_by("name")[:limit]
    if zones:
        groups.append({"key": "zones", "label": "Zones", "results": [
            {"label": z.name, "sublabel": z.get_zone_type_display(),
             "url": reverse("geography:zone_detail", args=[z.pk])}
            for z in zones
        ]})

    return groups


@login_required
def global_search(request):
    """Top-bar global search across the six primary entities.

    Returns the ``_search_results`` dropdown partial for the header's HTMX
    input. A query shorter than ``SEARCH_MIN_LEN`` (or empty) returns an empty
    dropdown so it collapses; otherwise it returns the matched groups.
    """
    q = request.GET.get("q", "").strip()
    groups = _search_groups(q) if len(q) >= SEARCH_MIN_LEN else []
    total = sum(len(g["results"]) for g in groups)
    return render(request, "partials/_search_results.html", {
        "q": q,
        "groups": groups,
        "total": total,
        "min_len": SEARCH_MIN_LEN,
    })


def about(request):
    """Public About page with policy timeline and platform purpose."""
    logo_path = os.path.join(settings.BASE_DIR, "static", "img", "logo.png")
    return render(request, "about.html", {"logo_exists": os.path.isfile(logo_path)})


#: The Getting Started cards, in page order, paired with the module each one
#: needs to render at all. ``None`` means the card renders in every valid
#: configuration.
#:
#: **Why the numbering lives here and not in the template.** Plan 89-02 (ISS-088)
#: replaced ten hardcoded ``Step N`` literals with numbers computed from what
#: actually renders — a nine-module drinking-water deployment used to show a
#: single card labelled "Step 5", which is not a gap in a sequence but a number
#: pointing at a sequence the reader cannot see. A template counter cannot do it:
#: the page's *cross-references* ("that's Steps 1, 2, 8, and 9" and "Steps 3
#: through 7") render ABOVE the cards they cite, so the numbers have to exist
#: before the first card is drawn. Declared here, in page order, exactly like
#: ``_PAGES`` in the droppability harness — adding a step means adding a row.
#:
#: **Why ``pwsid`` is FIRST, and why nobody should "fix" the numbering back.**
#: Plan 92-01 (ISS-092) added the drinking-water door this page had never
#: mentioned, and Brent's decision on 2026-07-22 was identity before geography.
#: The Setup Wizard's GeoJSON upload answers *where*: it draws a ``Boundary``
#: polygon, and every step after it is a spatial query filtered to that shape. A
#: PWSID answers *who*: it builds a ``WaterSystem`` out of three EPA Envirofacts
#: tables, and nothing about it is spatial. A groundwater agency needs the first
#: question answered; a drinking-water utility needs the second, and on a
#: nine-module drinking deployment the wizard's own steps are all gated off, so
#: the page used to open on "Step 1 · Define Management Zones" — a map, offered
#: to a utility as its first instruction. The cost of putting this row first is
#: that every step on a full 16-module deployment shifts up by one (1-10 became
#: 1-11, and both cross-reference strings moved with them). That cost was
#: accepted knowingly: it is the price of one page that is honest in both
#: configurations rather than one that is honest in the larger of them.
GETTING_STARTED_STEPS = (
    ("pwsid", "drinking"),
    ("use_areas", "parcels"),
    ("wells", "wells"),
    ("accounts", "accounting"),
    ("water_year", "accounting"),
    ("zones", None),
    ("ceilings", "accounting"),
    ("ledger", "accounting"),
    ("stations", "datasync"),
    ("surface", "surface"),
    ("reports", "reporting"),
)

#: The steps the Setup Wizard sentence cites, and the steps the accounting
#: sentence cites as a range. Both live beside the step table so a change to one
#: is made looking at the other.
_WIZARD_CITED_STEPS = ("use_areas", "wells", "stations", "surface")
_ACCOUNTING_CITED_STEPS = ("accounts", "water_year", "ceilings", "ledger")


def _getting_started_numbering():
    """``{step key: rendered number}`` plus the two cross-reference strings.

    The Step 10 card carries a second condition beyond its module — ``reporting``
    can be installed while neither family it files (GEARS/CalWATRS) has a module
    — so it is special-cased here rather than given a second column that only one
    row would ever use.

    The accounting range is emitted as "N through M" rather than a list because
    the cards it names are always contiguous: Step 5 (zones) is ``geography`` and
    renders in every configuration, and it sits between the accounting cards, so
    the run cannot break in the middle.
    """
    numbers = {}
    n = 0
    for key, module in GETTING_STARTED_STEPS:
        if key == "reports":
            shown = is_enabled("reporting") and (
                is_enabled("wells") or is_enabled("surface")
            )
        else:
            shown = module is None or is_enabled(module)
        if shown:
            n += 1
            numbers[key] = n

    cited = [str(numbers[k]) for k in _WIZARD_CITED_STEPS if k in numbers]
    accounting = [numbers[k] for k in _ACCOUNTING_CITED_STEPS if k in numbers]
    return {
        "steps": numbers,
        "wizard_cited_steps": oxford_join(cited),
        "accounting_step_range": (
            f"{min(accounting)} through {max(accounting)}" if accounting else ""
        ),
    }


@login_required
def getting_started(request):
    """Getting Started walkthrough for new GSA administrators."""
    return render(request, "help/getting_started.html", _getting_started_numbering())


#: The five explainer pages, paired with every module whose domain they explain.
#:
#: **This is the Plan 89-02 Help-page decision, and it is a hide, not a rewrite.**
#: These pages do not merely mention accounting — accounting IS their subject.
#: "How Water Balances Work" answers one question: how do you reconcile estimated
#: crop use against surface deliveries, groundwater and rain? Take those domains
#: away and there is no question left to answer, and a module-neutral rewrite
#: would be a page about nothing. A drinking-water utility has no crops, no
#: canals, no wells, no allocation ceilings and no ledger; the honest Help
#: section for them has three entries that are all true rather than five where
#: three describe somebody else's agency.
#:
#: **The sets are per page and measured**, not a blanket "accounting is off"
#: rule, so a district running Accounting and Surface but no Wells keeps
#: everything that is still true for it. Each set was derived by scanning the
#: template for the forbidden vocabulary in
#: ``tests/droppability/checks.py::_FORBIDDEN_VOCABULARY`` — a page disappears
#: exactly when one of the domains it actually names is gone.
#:
#: 404, not a redirect and not a page that loads and lies — the same answer a
#: dropped module's own routes give, and the same mechanism
#: ``infrastructure/views.py`` already uses when no module owns an
#: infrastructure type.
EXPLAINER_MODULES = {
    "water_balances": ("accounting", "parcels", "surface", "wells"),
    "methods": ("accounting", "parcels", "surface", "wells"),
    "settings_explained": ("accounting", "surface"),
    "surface_deliveries": ("accounting", "surface", "recharge"),
    "budgets_allocations": ("accounting", "parcels", "surface", "recharge"),
}


def explainer_is_available(name):
    """Whether this deployment runs every domain the named explainer explains.

    Read by the views below and by ``templates/partials/_sidebar.html`` (through
    the ``nav`` tag library) so the link and the page can never disagree.
    """
    return all(is_enabled(module) for module in EXPLAINER_MODULES[name])


def _explainer(request, name, template):
    """Render an explainer page, or 404 if its subject is not in this deployment."""
    if not explainer_is_available(name):
        missing = [m for m in EXPLAINER_MODULES[name] if not is_enabled(m)]
        raise Http404(
            f"This deployment does not run {', '.join(missing)}, and this page "
            f"exists to explain that. It is hidden rather than rewritten: the "
            f"domain is the page's subject, not a mention inside it."
        )
    return render(request, template)


@login_required
def budgets_allocations(request):
    """Explainer: how a zone allocation ceiling becomes each account's allocation."""
    return _explainer(request, "budgets_allocations", "help/budgets_allocations.html")


@login_required
def surface_deliveries(request):
    """Explainer: the two agency delivery settings, in plain language."""
    return _explainer(request, "surface_deliveries", "help/surface_deliveries.html")


@login_required
def water_balances(request):
    """Conceptual explainer: ET as estimated use, supplies reconciled against it."""
    return _explainer(request, "water_balances", "help/water_balances.html")


@login_required
def methods(request):
    """Explainer: the calculation chain and the two ET-demand allocation services."""
    return _explainer(request, "methods", "help/methods.html")


@login_required
def settings_explained(request):
    """Explainer: every agency-wide configuration knob, what it does and when to change it."""
    return _explainer(request, "settings_explained", "help/settings_explained.html")


#: Glossary definitions that end with a "See Help > <page>." pointer, mapped to
#: the explainer that pointer opens.
#:
#: **ISS-085 is NOT decided by this table.** Whether an operator's glossary should
#: narrow to the terms their deployment uses is a live product question and Plan
#: 89-02 deliberately left it open (see the summary). What 89-02 could not leave
#: alone is the consequence of its OWN change: those five Help pages are now
#: hidden when the deployment does not run the domains they explain, so a
#: definition telling the reader to "See Help > Allocations & Ceilings" was
#: sending them at a 404. A cross-reference to a page that is not there is a
#: wrong instruction, not a gap — 88-03 drew that line for the Setup Wizard's
#: step numbers, and it applies identically here.
#:
#: The pointer is dropped, never rewritten. The definition before it stands on
#: its own; a dictionary entry does not need a "read more" to be a definition.
_GLOSSARY_HELP_POINTERS = {
    "Allocations & Ceilings": "budgets_allocations",
    "Methods Behind the Numbers": "methods",
    "How Water Balances Work": "water_balances",
    "Surface Delivery Settings": "surface_deliveries",
    "Configs & Settings, explained": "settings_explained",
}


def _without_unavailable_help_pointers(definition):
    """Drop " See Help > X." where X is not served in this configuration.

    A no-op on a full deployment, which is what keeps the byte-identity promise —
    every explainer is available there, so no replacement runs.
    """
    for page, key in _GLOSSARY_HELP_POINTERS.items():
        if not explainer_is_available(key):
            definition = definition.replace(f" See Help > {page}.", "")
    return definition


@login_required
def glossary(request):
    """Glossary of water accounting terms used throughout the platform."""
    terms = {
        "Allocation Ceiling": "The total volume of water assigned to a zone for a reporting period, set per zone, water type, and period. It is the policy ceiling for a whole area. The platform divides it into per-account Allocations. See Help > Allocations & Ceilings.",
        "Allocation": "A single account's share of a zone's Allocation Ceiling, pro-rated by how many parcels the account holds in the zone. Allocation minus usage gives the account's remaining water; a negative remaining is an overdraft. See Help > Allocations & Ceilings.",
        "Apportionment": "Dividing a shared supply — a well or headgate that serves several fields — among those fields by their estimated ET demand rather than by headcount, so the total always reconciles back to what the source actually produced. See Help > Methods Behind the Numbers.",
        "Usage": "Water consumed via extraction (well meters) or evapotranspiration (ET estimates), recorded as negative ledger entries.",
        "CalWATRS": "California Water Accounting, Tracking, and Reporting System: the State Water Board's surface-diversion reporting system (replaced eWRIMS).",
        "CDEC": "California Data Exchange Center, real-time hydrologic data from DWR.",
        "CFS (Cubic Feet per Second)": "A rate of flow used for surface water diversions; a point of diversion popup shows a rate like \"50.00 cfs.\" One CFS is about 1.9835 acre-feet per day.",
        "CIMIS": "California Irrigation Management Information System, weather station data for agriculture.",
        "Closing Balance": "The reconciliation of a use area's supplies (surface, precipitation, recovered groundwater) against its uses (ET, recharge, runoff, and net banked/drawn credits) for a period. A small leftover residual is normal — real books rarely close to exactly zero. See Help > How Water Balances Work.",
        "Consumptive Use": "The water a crop actually consumes, estimated from satellite evapotranspiration (ET), regardless of whether it came from a canal, a well, or rain. It is one input among many; district measurements are the primary record. Gross consumptive use is total ET; net consumptive use subtracts effective precipitation. See Help > How Water Balances Work.",
        "Curtailment": "A State Water Board order to reduce or stop diverting under a water right, usually during drought. A right's curtailment status appears on its water-right detail card.",
        "Delivery Settings": "Two agency-wide settings that shape how surface-water deliveries are counted: how much of a delivery the crop actually uses (the rest recharges the aquifer), and what happens to a district's unused water at year-end (carry it forward or let it expire). Set by the analyst on the Delivery Settings page. See Help > Surface Delivery Settings.",
        "Data Source": "An external agency or API that provides hydrologic measurements.",
        "ET (Evapotranspiration)": "The water consumed by crops — evaporation from the soil plus transpiration through the plants. Where meters are sparse, the methodology can use ET as one optional way to estimate groundwater use. (OpenET is the satellite data source; ET is the quantity it measures.)",
        "Effective Precipitation": "The portion of rainfall that crops actually use, rather than running off or percolating away. The methodology subtracts it from gross ET to find the net consumptive demand that supplies must meet. See Help > Methods Behind the Numbers.",
        "ET-Demand Allocation": "How a single recorded district delivery is split across the many fields one headgate serves — weighted by each field's estimated ET demand, not divided evenly, and capped at each field's demand divided by irrigation efficiency. See Help > Methods Behind the Numbers.",
        "GEARS": "Groundwater Extraction Annual Reporting System, the State Water Board reporting format for per-well extraction.",
        "GSA": "Groundwater Sustainability Agency, the local agency responsible for managing groundwater under SGMA.",
        "GSP": "Groundwater Sustainability Plan, the 20-year plan each GSA must adopt.",
        "Health Check": "Automated system diagnostic covering data freshness, connectivity, and configuration.",
        "Ledger Entry": "A double-entry record: supply amounts are positive, usage amounts are negative.",
        "Managed Aquifer Recharge (MAR)": "Intentionally adding water to an aquifer through spreading basins or injection wells.",
        "Methodology / Calculation Plan": "The ordered, configurable chain of steps — gross ET, minus effective precipitation, minus surface water deliveries, minus edge cases — that the platform applies to turn measurements into a defensible billable groundwater figure for each use area. Tune it on the Methodology Settings page.",
        "Monitoring Station": "A curated external sensor (stream gauge, weather station, groundwater well) linked to a data source.",
        "OpenET": "Satellite-based evapotranspiration estimates, used to calculate crop water use.",
        "Use Area": "A plot of land identified by an Assessor Parcel Number (APN), the basic unit of water accounting.",
        "Point of Diversion (POD)": "The physical location where water is diverted from a stream or river.",
        "Recovery Horizon": "A per-district setting for what happens to a district's unused surface water at year-end: carry it forward to next year, or let it expire. A debt (an overdraw) always carries regardless. Set on the Delivery Settings page. See Help > Configs & Settings, explained.",
        "Water Year": "A time window (usually October 1 through September 30) for water accounting and reporting.",
        "SGMA": "Sustainable Groundwater Management Act (2014), the California law requiring groundwater management.",
        "USGS": "United States Geological Survey, provides stream gauge and groundwater level data.",
        "Water Account": "Groups use areas for accounting purposes, tracks supply and usage.",
        "Water Right": "A legal entitlement to divert surface water, issued by the State Water Board.",
        "Zone / Management Zone": "A sub-area of the district that carries its own Allocation Ceiling. Each use area belongs to a zone, and a zone must exist before an Allocation Ceiling can be set for it. See Help > Allocations & Ceilings.",
        "Well": "A borehole used to draw groundwater, identified by state well number or local ID.",
    }
    sorted_terms = sorted(
        (term, _without_unavailable_help_pointers(definition))
        for term, definition in terms.items()
    )
    # Build list of unique first letters for the jump nav
    seen = set()
    letters = []
    for term, _ in sorted_terms:
        first = term[0].upper()
        if first not in seen:
            seen.add(first)
            letters.append(first)
    return render(request, "help/glossary.html", {"terms": sorted_terms, "letters": letters})


@login_required
def profile(request):
    """View and edit the signed-in user's own contact details."""
    from core.forms import ProfileForm

    if request.method == "POST":
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect("profile")
    else:
        form = ProfileForm(instance=request.user)
    return render(request, "core/profile.html", {"form": form})
