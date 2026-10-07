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
from core.access import public_in_open_demo

from datasync import freshness
from datasync.models import DataSyncLog, MonitoredStation
from geography.models import Zone
from parcels.models import Parcel
from wells.models import Well
from accounting.models import WaterAccount
from core.models import SiteConfig
from core.modules import is_enabled
from core.templatetags.prose import oxford_join


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
        # 143-09 (R-137, R-138): computed here, before the anonymous return,
        # so the signed-in hero and the anonymous stations card read one
        # pair of numbers rather than two counts that could drift apart.
        now = timezone.now()
        active = list(
            MonitoredStation.objects.filter(is_active=True).select_related("data_source")
        )
        context["active_station_count"] = len(active)
        context["fresh_stations"] = sum(
            1
            for s in active
            if freshness.classify_freshness(s.data_source.code, s.last_data_at, now)
            == "fresh"
        )
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
    site_config = SiteConfig.objects.first()
    context["agency_name"] = site_config.agency_name if site_config else "Your Agency"
    # 143-09 (R-137): the greeting ("Good morning") and the `_greeting`
    # helper that built it are both removed; the greeting named a time of
    # day, not a fact about the district, and the hero's largest words now
    # lead with the station figure instead (built above, before the
    # anonymous return). Only `last_sync_time` is still signed-in-only: the
    # anonymous page has no "synced X ago" line to fill.
    if is_enabled("datasync"):
        last_sync = (
            DataSyncLog.objects.filter(status__in=["success", "partial"]).first()
        )
        context["last_sync_time"] = last_sync.started_at if last_sync else None
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


def demonstration_data(request):
    """Source-by-source account of what is real in this demo and what is not.

    Deliberately reachable with the demonstration flag OFF and on a real agency
    deployment. A page that vanished when the flag flipped would break every
    link anyone had ever shared to it, including one pasted in answer to a
    "this data is fake" accusation — which is the moment it most needs to
    resolve.

    Static prose rather than a registry walked at render time. The honest
    provenance of a seeded row is a judgement about where it came from, not a
    property the row carries, so deriving this page from the database would
    invent a precision the data does not have.
    """
    return render(request, "about_demonstration_data.html")


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

#: The steps the Setup Wizard does, and the steps the accounting sentence cites
#: as a range. Both live beside the step table so a change to one is made
#: looking at the other. 149.1-04 (2026-10-07): wells and surface came OFF the
#: wizard list because the wizard never did them: ``setup/services.py``
#: ``WIZARD_STEPS`` imports basins (as zones), parcels (use areas), flowlines
#: and monitoring stations, and no wells or recharge basins; the page's wizard
#: table says so row by row, and this tuple is what ``wizard_cited_steps`` names.
_WIZARD_CITED_STEPS = ("use_areas", "stations")
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


@public_in_open_demo
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


def _explainer(request, name, template, context=None):
    """Render an explainer page, or 404 if its subject is not in this deployment."""
    if not explainer_is_available(name):
        missing = [m for m in EXPLAINER_MODULES[name] if not is_enabled(m)]
        raise Http404(
            f"This deployment does not run {', '.join(missing)}, and this page "
            f"exists to explain that. It is hidden rather than rewritten: the "
            f"domain is the page's subject, not a mention inside it."
        )
    return render(request, template, context or {})


@public_in_open_demo
def budgets_allocations(request):
    """Explainer: how a zone allocation ceiling becomes each account's allocation."""
    return _explainer(request, "budgets_allocations", "help/budgets_allocations.html")


@public_in_open_demo
def surface_deliveries(request):
    """Explainer: the two agency delivery settings, in plain language."""
    return _explainer(request, "surface_deliveries", "help/surface_deliveries.html")


@public_in_open_demo
def water_balances(request):
    """Conceptual explainer: crop water use as estimated demand, matched against supplies.

    148-03: leads with the picture's own worked field-month
    (``accounting.services.example_field_month``), shared with ``methods``
    below through ``help/partials/_the_subtraction.html`` so the two pages
    can never show two different examples for the same deployment.
    """
    from accounting.services import example_field_month

    context = example_field_month() or {}
    context.setdefault("demonstration", _demonstration_mode())
    return _explainer(request, "water_balances", "help/water_balances.html", context)


@public_in_open_demo
def methods(request):
    """Explainer: the five-step calculation chain and how one canal total is shared.

    148-03: leads with the same worked field-month as ``water_balances``
    above; see that view's docstring.
    """
    from accounting.services import example_field_month

    context = example_field_month() or {}
    context.setdefault("demonstration", _demonstration_mode())
    return _explainer(request, "methods", "help/methods.html", context)


def _demonstration_mode():
    """The live ``SiteConfig.demonstration_mode`` flag, false with no config row.

    ``example_field_month()`` already stamps ``demonstration`` onto its own
    context dict when it returns one; this covers the words-only variant
    (``example_field_month()`` returned ``None``), where the honesty panel on
    ``water_balances`` still needs to know whether this deployment is a
    demonstration.
    """
    return bool(
        SiteConfig.objects.filter(demonstration_mode=True).exists()
    )


@public_in_open_demo
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


#: The entries that are the state's and the programs' names rather than this
#: platform's own words: the page marks each row with which it is, because a
#: fresh reader (149.1-04, round 1) could not tell them apart without reading
#: every definition. Membership is still ISS-085's 40; this only labels them.
_GLOSSARY_OUTSIDE_NAMES = frozenset({
    "CalWATRS", "CDEC", "CIMIS", "GEARS", "GSA", "GSP", "OpenET", "SGMA", "USGS",
})


def _split_help_pointer(definition):
    """Split a trailing " See Help > X." off a definition, for the Read more column.

    Returns ``(text, page, url_name)``: the definition without its pointer, the
    page's name as the pointer spells it, and the explainer's url name from
    ``_GLOSSARY_HELP_POINTERS``. A definition that ends with no pointer, or whose
    pointer ``_without_unavailable_help_pointers`` has already dropped, comes back
    whole with ``(definition, None, None)``, and its Read more cell stays empty.
    """
    for page, key in _GLOSSARY_HELP_POINTERS.items():
        pointer = f" See Help > {page}."
        if definition.endswith(pointer):
            return definition[: -len(pointer)], page, key
    return definition, None, None


@public_in_open_demo
def glossary(request):
    """Glossary of the terms this platform uses, for the operator running it.

    **This is a software glossary, not a hydrology one (DESIGN.md copy rule 11).**
    The reader is a water district engineer or operator, so an entry answers
    *what does this platform mean by X and what does it hold against one* — never
    *what is X*. Rewritten on that axis 2026-08-06 (ISS-129): "Well" used to read
    "A borehole used to draw groundwater", which told a thirty-year groundwater
    professional what a well is. It now names the record and its fields.

    Three things stay explainable forever and are the legitimate half of the
    boundary: agency and program names with their expansions (CalWATRS, CDEC,
    CIMIS, GEARS, GSA, GSP, OpenET, SGMA, USGS), codes inside data this platform
    did not author, and this platform's own coined concepts (Allocation Ceiling,
    Use Area, Ledger Entry).

    **Membership never changes, only wording (ISS-085, decided).** 36 entries in
    and 40 entries out (148-03 Task 2 added Canal Water the Crop Could Use,
    Groundwater Consumed, Groundwater Extracted and Canal Water Beyond What the
    Crop Could Use); a reduced deployment narrows the *pointers*, not the
    dictionary. And the ``See Help > X.`` sentences are matched byte-for-byte by
    ``_without_unavailable_help_pointers`` above — reword one and it stops being
    stripped, which sends a reduced-deployment reader at a 404 (the defect Plan
    89-02 fixed; ``tests/test_help_explainers.py`` guards it).

    **The page is one table (149.1-04, 2026-10-07).** Each entry is a row: the
    term, the definition with its pointer split off by ``_split_help_pointer``,
    and the pointer as a link in the Read more column, empty where there is none.
    The letter headings that a script used to insert into a ``<dl>`` are rows the
    template renders where the first letter changes, so the jump nav's anchors
    exist without JavaScript. The definitions were reworded to rule 12's names in
    the same plan, membership unchanged: an old name says first which name the
    screens use, and an entry says what the platform holds or does and stops.
    """
    terms = {
        "Allocation Ceiling": "This platform's total for one zone, one water type and one reporting period, in acre-feet, set on the Allocations page; the platform divides it into each account's allocation. See Help > Allocations & Ceilings.",
        "Allocation": "One account's share of a zone's Allocation Ceiling, pro-rated by the count of use areas the account holds in the zone; charged at groundwater extracted (a surface allocation at water delivered). Remaining is the allocation plus any carry-over less what was charged; a negative remaining is an overdraft. See Help > Allocations & Ceilings.",
        "Apportionment": "Another name for ET-Demand Allocation, the split of a headgate's recorded monthly total among the fields it serves in proportion to each field's crop water use after rain; a field's ledger row says divided up from the canal total. See Help > Methods Behind the Numbers.",
        "Usage": "The ledger's word for a row that spends water, stored as a negative amount; a meter reading, the month's calculated row (groundwater consumed) or water delivered; a groundwater allocation is charged at groundwater extracted.",
        "Canal Water the Crop Could Use": "One month's canal delivery to a field times the field's irrigation efficiency, from its irrigation method on file, else the share of delivered water the crop consumes on Delivery Settings, 75% unless changed. Subtracted from crop water use; the rest of the delivery is neither crop water use nor a credit. See Help > Methods Behind the Numbers.",
        "Groundwater Consumed": "On a field with a well and no meter reading, what is left of the month's crop water use once rain the crop could use and canal water the crop could use are subtracted. The platform's estimate, written as the month's calculated ledger row. See Help > Methods Behind the Numbers.",
        "Groundwater Extracted": "Groundwater consumed divided by the share of pumped groundwater the crop consumes (Delivery Settings, 80% unless changed), stamped on the month's calculation; with a meter reading, the reading as recorded. What a groundwater allocation is charged. See Help > Methods Behind the Numbers.",
        "Canal Water Beyond What the Crop Could Use": "Canal water the crop could use beyond what was left of the month's crop water use after rain, recorded on the month's calculation. Delivery Settings decides what else happens to it: not credited (the default), credited to the landowner less the share left in the basin, or shown on the field's page as its own line. See Help > Methods Behind the Numbers.",
        "CalWATRS": "California Water Accounting, Tracking, and Reporting System: the State Water Board's surface-diversion reporting system (replaced eWRIMS).",
        "CDEC": "California Data Exchange Center, real-time hydrologic data from DWR.",
        "CFS (Cubic Feet per Second)": "Rates on a point of diversion, a water right and a monthly diversion record, shown as \"50.00 cfs\".",
        "CIMIS": "California Irrigation Management Information System, weather station data for agriculture.",
        "Closing Balance": "This platform's water balance for one use area and period: supplies (water delivered, groundwater extracted, rain the crop could use) set against uses, and the difference is the residual. A small residual is normal. See Help > How Water Balances Work.",
        "Consumptive Use": "Crop water use, under the dashboard's name; the satellite estimate from OpenET, gross. Net consumptive use subtracts rain the crop could use. See Help > How Water Balances Work.",
        "Curtailment": "One record per State Water Board order, holding its order ID, title, effective and end dates, watershed and priority-date cutoff; each right it affects shows its status on its own detail card.",
        "Delivery Settings": "The administrator's page for the agency-wide shares, canal water beyond what the crop could use, the year-end choice for unused allotment, the reporting year and record addresses. See Help > Surface Delivery Settings.",
        "Data Source": "One record per outside agency or service the platform reads data from, holding its name, code, address, how often it is read and when it was last read.",
        "ET (Evapotranspiration)": "Crop water use, as the screens call it; the quantity OpenET estimates from satellite data for every field. See Help > How Water Balances Work.",
        "Effective Precipitation": "Rain the crop could use, as the screens call it; the share of rainfall the calculation subtracts from crop water use, by the rain method on Methodology Settings (all of it, a fixed fraction, or USDA-SCS soil storage, the default). See Help > Methods Behind the Numbers.",
        "ET-Demand Allocation": "On the screens, a delivery divided up from the canal total; how this platform divides a headgate's recorded monthly total among the fields it serves, in proportion to each field's crop water use after rain and up to what each field could use. Anything left over is recorded against the headgate. See Help > Methods Behind the Numbers.",
        "GEARS": "Groundwater Extraction Annual Reporting System, the State Water Board reporting format for per-well extraction.",
        "GSA": "Groundwater Sustainability Agency, the local agency responsible for managing groundwater under SGMA.",
        "GSP": "Groundwater Sustainability Plan, the 20-year plan each GSA must adopt.",
        "Health Check": "This platform's own diagnostics, each graded green, yellow or red with a message; they cover data freshness, ledger integrity, the calculation, the database and the server.",
        "Ledger Entry": "One row on a use area's ledger, in acre-feet, with its date, water type and source. Water added to the allocation is positive and water taken against it is negative; an entered row or an adjustment carries the sign it is given.",
        "Managed Aquifer Recharge (MAR)": "One record per site, holding its capacity in acre-feet, its zone, its location and outline on the map, the points of diversion feeding it, and its events, each with its dates, a volume in acre-feet and a water type.",
        "Methodology / Calculation Plan": "Methodology, as the screens call it, under Administration > Methodology; this platform's monthly chain of steps for each use area, reordered and switched on or off there (crop water use, less rain the crop could use, less canal water the crop could use, a field with no crop set to zero, floored at 0 acre-feet unless changed). What is left becomes groundwater consumed on a field with a well and no meter reading; water use recorded, no supply reported on a field with no well; a comparison figure only on a month with a meter reading. See Help > Methods Behind the Numbers.",
        "Monitoring Station": "One record per outside station (a stream gauge, a weather station, a groundwater level well), holding its name, its ID at the data source, its location and the parameters it reports.",
        "OpenET": "OpenET's satellite evapotranspiration data is the source of this platform's crop water use estimate, read for every field each month.",
        "Use Area": "This platform's record of one field: its Assessor Parcel Number (APN), owner, area in acres and outline on the map. Every monthly figure is calculated per use area; all are listed on the Use Areas page.",
        "Point of Diversion (POD)": "One record per POD: its location, the right it draws under, its stream or flowline, its maximum rate in CFS, and the parcels it serves, with its monthly diversion records.",
        "Sampling Schedule": "The operator's own checklist on a drinking-water deployment, one row per thing sampled on a cycle, with its frequency, the date last done and the date next due. Both dates are typed in; the platform never works a due date out from the frequency.",
        "Recovery Horizon": "Year-end unused water on a district's page under Zones, and \"When a district doesn't use its full allotment by the end of the water year\" on Delivery Settings, the agency default a district can differ from. The unused amount carries forward as a credit or expires; an overdraw always carries as a debt. See Help > Configs & Settings, explained.",
        "Water Year": "One reporting period, held on the Water Years page with its name and its start and end dates.",
        "SGMA": "Sustainable Groundwater Management Act (2014), the California law requiring groundwater management.",
        "USGS": "United States Geological Survey, a federal source of stream gauge and groundwater level data.",
        "Water Account": "This platform's record of one account: its name, account number, contact and status, and the use areas it holds. Its allocation and remaining water are worked out across those use areas.",
        "Water Right": "One record per right, holding its state ID, type, holder, priority date, face value in acre-feet, CalWATRS PIN and status, plus its places of use, the use areas it serves. Issued by the State Water Board; the platform only keeps the record.",
        "Zone / Management Zone": "Zone, as the screens call it; this platform's record of one area that carries its own Allocation Ceiling, holding its name, its outline on the map, its type and the use areas assigned to it on its page under Administration > Zones. A surface district is its own zone, with its own year-end unused water choice. See Help > Allocations & Ceilings.",
        "Well": "One record per well, holding its state well number, WCR number and local ID, its meters, the parcels it irrigates, and its depth, casing and screen intervals.",
    }
    entries = []
    for term, definition in sorted(terms.items(), key=lambda item: item[0].casefold()):
        text, pointer_page, pointer_url = _split_help_pointer(
            _without_unavailable_help_pointers(definition)
        )
        entries.append({
            "term": term,
            "letter": term[0].upper(),
            "outside_name": term in _GLOSSARY_OUTSIDE_NAMES,
            "text": text,
            "pointer_page": pointer_page,
            "pointer_url": pointer_url,
        })
    # The jump nav's letters, in the order their group rows appear in the table.
    letters = list(dict.fromkeys(entry["letter"] for entry in entries))
    return render(request, "help/glossary.html", {"entries": entries, "letters": letters})


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
