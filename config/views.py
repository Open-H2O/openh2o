# SPDX-License-Identifier: AGPL-3.0-or-later
import os

from django.conf import settings
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
from accounting.models import ReportingPeriod, WaterAccount
from core.models import SiteConfig
from core.modules import is_enabled


def _public_counts() -> dict:
    """The entity counts both the public landing and the signed-in home show."""
    context = {}
    # `parcels` and `accounting` are guarded the same way as the four
    # below: both are optional modules, so a count is built only when the
    # module is on.
    if is_enabled("parcels"):
        context["parcel_count"] = Parcel.objects.count()
    if is_enabled("accounting"):
        context["water_account_count"] = WaterAccount.objects.count()
    # `wells` and `datasync` are demoted, not removed, so the imports
    # at the top of this file keep working and the tables keep answering — with
    # a truthful zero that reads as a LIE on the page: "0 Wells" says you have
    # no wells, where the honest answer is that this deployment does not track
    # them. Same reason the key is built inside the guard rather than set to
    # zero outside it: absent, so the stat card is simply not rendered.
    if is_enabled("wells"):
        context["well_count"] = Well.objects.count()
    if is_enabled("datasync"):
        context["station_count"] = MonitoredStation.objects.count()
        # Computed here, before the anonymous return,
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
        # Local import: `surface` is an optional module, so this must
        # not run at module scope: this file was the first casualty of a
        # surface-less boot, dying here before printing a useful error. The count
        # is built inside the guard too: the stat cards that read it are guarded
        # on the same condition, so on a surface-less deployment the key is simply
        # absent rather than a misleading zero.
        from surface.models import PointOfDiversion

        context["diversion_count"] = PointOfDiversion.objects.count()
    if is_enabled("recharge"):
        # Local import: `recharge` is an optional module, so this must not run at
        # module scope: a deployment without the app would fail to import it. The count is built inside the guard too — the
        # templates that read it are guarded on the same condition, so on a
        # recharge-less deployment the key is simply absent rather than zero.
        from recharge.models import RechargeSite

        context["recharge_site_count"] = RechargeSite.objects.count()
    return context


def _add_signed_in_context(context: dict) -> None:
    """Add what only the signed-in home page shows (hero data and counters) to ``context``."""
    # Status-hero data — every value is real, never decorative.
    site_config = SiteConfig.objects.first()
    context["agency_name"] = site_config.agency_name if site_config else "OpenH2O"
    # The greeting ("Good morning") and the `_greeting`
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
    # Records decide what the home page offers.
    # Module flags cannot: `surface` and `datasync` both pull the
    # parcels/accounting pair on, so accounting can be running with no use
    # area to log against and no water year to balance. "Log water use" reads
    # `parcel_count`, built above; "Water balance" reads this.
    if is_enabled("accounting"):
        context["has_water_year"] = ReportingPeriod.objects.exists()
    # The counters only the signed-in page shows. Monitoring stations reuse
    # `station_count`, built above for the public landing, rather than count
    # the same table twice. `surface` and `drinking` are truly removable, so
    # their models are imported here, inside the guard, never at module scope
    # (a module-scope import of an absent app kills the boot); the key
    # is absent, not zero, when the module is off.
    if is_enabled("surface"):
        from surface.models import WaterRight

        context["water_right_count"] = WaterRight.objects.count()
    if is_enabled("drinking"):
        from drinking.models import SampleResult, WaterSystem

        context["water_system_count"] = WaterSystem.objects.count()
        context["sample_result_count"] = SampleResult.objects.count()


def index(request):
    """Signed-in users get the task-first home; visitors get the public landing.

    Both share the same entity counts. The home page wraps them in a Command
    Console layout: a status hero (who/where + live data health), the primary
    task cards, and the counts demoted to an at-a-glance stat bar. The public
    landing shows the same counts as the demo's headline numbers.

    The signed-in page also counts water rights, water systems and
    sample results, and asks whether a water year exists. Those are built
    after the anonymous return, so the public landing's queries do not grow.
    """
    context = _public_counts()
    if not request.user.is_authenticated:
        return render(request, "index.html", context)

    _add_signed_in_context(context)
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


def _parcel_search_group(q: str, limit: int) -> dict | None:
    """The "Use Areas" result group, or None when off or nothing matched."""
    # The same crash site as the wells group below. Schema-resident means the parcels tables
    # SURVIVE the demotion and keep answering the query, while
    # `reverse("parcels:detail")` raises NoReverseMatch because the routes are
    # gone. On a fresh demoted deployment the tables are empty, `if parcels:` is
    # falsy and nothing reverses — which is why this cannot be left to luck: an
    # agency that switches Use Areas off AFTER using it keeps its rows, and the
    # search box becomes a 500 on the first two characters typed.
    if is_enabled("parcels"):
        parcels = Parcel.objects.filter(
            Q(parcel_number__icontains=q) | Q(owner_name__icontains=q)
        ).order_by("parcel_number")[:limit]
        if parcels:
            return {"key": "parcels", "label": "Use Areas", "results": [
                {"label": p.parcel_number, "sublabel": p.owner_name,
                 "url": reverse("parcels:detail", args=[p.pk])}
                for p in parcels
            ]}
    return None


def _well_search_group(q: str, limit: int) -> dict | None:
    """The "Wells" result group, or None when off or nothing matched."""
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
            return {"key": "wells", "label": "Wells", "results": [
                {"label": w.name, "sublabel": w.well_registration_id,
                 "url": reverse("wells:detail", args=[w.pk])}
                for w in wells
            ]}
    return None


def _diversion_search_group(q: str, limit: int) -> dict | None:
    """The "Surface Diversions" result group, or None when off or nothing matched."""
    if is_enabled("surface"):
        # Local import + guard: `surface` is an optional module. Global
        # search is `config`, which stays enabled, so without the guard this would
        # query a missing model AND reverse a route that never registered.
        from surface.models import PointOfDiversion

        diversions = PointOfDiversion.objects.filter(
            Q(name__icontains=q) | Q(stream_name__icontains=q)
        ).order_by("name")[:limit]
        if diversions:
            return {"key": "surface", "label": "Surface Diversions", "results": [
                {"label": d.name, "sublabel": d.stream_name,
                 "url": reverse("surface:pod_detail", args=[d.pk])}
                for d in diversions
            ]}
    return None


def _station_search_group(q: str, limit: int) -> dict | None:
    """The "Monitoring Stations" result group, or None when off or nothing matched."""
    if is_enabled("datasync"):
        # Same NoReverseMatch exposure as the wells group above.
        stations = MonitoredStation.objects.select_related("data_source").filter(
            Q(station_name__icontains=q)
            | Q(external_station_id__icontains=q)
            | Q(usgs_site_id__icontains=q)
        ).order_by("station_name")[:limit]
        if stations:
            return {"key": "stations", "label": "Monitoring Stations", "results": [
                {"label": s.station_name, "sublabel": s.external_station_id,
                 "url": reverse("datasync:station_detail", args=[s.pk])}
                for s in stations
            ]}
    return None


def _account_search_group(q: str, limit: int) -> dict | None:
    """The "Accounts" result group, or None when off or nothing matched."""
    if is_enabled("accounting"):
        accounts = WaterAccount.objects.filter(
            Q(account_number__icontains=q) | Q(name__icontains=q)
        ).order_by("name")[:limit]
        if accounts:
            return {"key": "accounts", "label": "Accounts", "results": [
                {"label": a.name, "sublabel": a.account_number,
                 "url": reverse("accounting:account_detail", args=[a.pk])}
                for a in accounts
            ]}
    return None


def _zone_search_group(q: str, limit: int) -> dict | None:
    """The "Zones" result group, or None when nothing matched."""
    zones = Zone.objects.filter(
        Q(name__icontains=q) | Q(basin_code__icontains=q)
    ).order_by("name")[:limit]
    if zones:
        return {"key": "zones", "label": "Zones", "results": [
            {"label": z.name, "sublabel": z.get_zone_type_display(),
             "url": reverse("geography:zone_detail", args=[z.pk])}
            for z in zones
        ]}
    return None


def _search_groups(q):
    """Run the per-entity searches and return a list of result groups.

    Each group is ``{"key", "label", "results": [{"label", "sublabel", "url"}]}``;
    ``key`` selects the matching glyph in the template. Empty groups are dropped
    so the dropdown only shows entity types that actually matched.
    """
    limit = SEARCH_GROUP_LIMIT
    groups = []
    for search in (
        _parcel_search_group,
        _well_search_group,
        _diversion_search_group,
        _station_search_group,
        _account_search_group,
        _zone_search_group,
    ):
        group = search(q, limit)
        if group is not None:
            groups.append(group)
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
    """The demonstration data sources page: the publisher of each public record and the sample data.

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
#: **Why the numbering lives here and not in the template.** The step numbers
#: are computed from what
#: actually renders — a nine-module drinking-water deployment used to show a
#: single card labelled "Step 5", which is not a gap in a sequence but a number
#: pointing at a sequence the reader cannot see. A template counter cannot do it:
#: the page's *cross-references* ("that's Steps 1, 2, 8, and 9" and "Steps 3
#: through 7") render ABOVE the cards they cite, so the numbers have to exist
#: before the first card is drawn. Declared here, in page order, exactly like
#: ``_PAGES`` in the droppability harness — adding a step means adding a row.
#:
#: **Why ``pwsid`` is FIRST, and why nobody should "fix" the numbering back.**
#: The drinking-water door comes first: identity before geography.
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
#: The order follows what depends on
#: what. Identity first, then the zones the records sit in, then the
#: records (use areas, the wells and diversions that attach to them, the
#: stations), then the accounting setup, and the ledger last because it is data
#: entry, not setup.
GETTING_STARTED_STEPS = (
    ("pwsid", "drinking"),
    ("zones", None),
    ("use_areas", "parcels"),
    ("wells", "wells"),
    ("surface", "surface"),
    ("stations", "datasync"),
    ("accounts", "accounting"),
    ("water_year", "accounting"),
    ("ceilings", "accounting"),
    ("ledger", "accounting"),
)

#: The steps the Setup Wizard does part of. Wells and
#: surface are NOT on this list because the wizard never did them:
#: ``setup/services.py`` ``WIZARD_STEPS`` imports basins (as zones), parcels
#: (use areas), flowlines and monitoring stations, and no wells or recharge
#: basins. 150.1 (2026-10-10): zones joined it, because the basins step adds
#: zones, so the one sentence "Run the Setup Wizard before Steps 2, 3 and 6"
#: replaces the old "does Steps 3 and 6 and part of Step 2", and the accounting
#: range ("Steps 7 through 10 are your agency's policy choices") left the page
#: with the note that used it.
_WIZARD_CITED_STEPS = ("zones", "use_areas", "stations")


def _getting_started_numbering():
    """``{step key: rendered number}`` plus the wizard's step citation and its count.

    The state-report step (``reporting``, with a second condition on ``wells`` or
    ``surface``) is not on the page (the
    module is not fully developed), so no row needs a second condition now.
    """
    numbers = {}
    n = 0
    for key, module in GETTING_STARTED_STEPS:
        shown = module is None or is_enabled(module)
        if shown:
            n += 1
            numbers[key] = n

    cited = [str(numbers[k]) for k in _WIZARD_CITED_STEPS if k in numbers]
    return {
        "steps": numbers,
        # No serial comma: the sentence reads "Steps 2, 3 and 6".
        "wizard_cited_steps": (
            f"{', '.join(cited[:-1])} and {cited[-1]}" if len(cited) > 1
            else "".join(cited)
        ),
        "wizard_cited_count": len(cited),
    }


@public_in_open_demo
def getting_started(request):
    """Getting Started walkthrough for new GSA administrators."""
    return render(request, "help/getting_started.html", _getting_started_numbering())


#: The five explainer pages, paired with every module whose domain they explain.
#:
#: **Hiding these pages is deliberate, and it is a hide, not a rewrite.**
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
    """The old Surface delivery settings address, forwarded to Settings explained.

    The page was folded into Settings explained (one
    fact on one page); a permanent redirect keeps every shared link working.
    """
    if not explainer_is_available("settings_explained"):
        raise Http404("This deployment does not serve Settings explained.")
    return redirect("settings_explained", permanent=True)


@public_in_open_demo
def water_balances(request):
    """Conceptual explainer: crop water use as estimated demand, matched against supplies.

    Leads with the picture's own worked field-month
    (``accounting.services.example_field_month``) through
    ``help/partials/_the_subtraction.html``.
    """
    from accounting.services import example_field_month

    context = example_field_month() or {}
    context.setdefault("demonstration", _demonstration_mode())
    return _explainer(request, "water_balances", "help/water_balances.html", context)


@public_in_open_demo
def methods(request):
    """Explainer: the settings behind each figure, the canal split and the unmetered estimate.

    2026-10-10: built from thirteen facts; the worked
    field-month moved off this page and lives on ``water_balances`` alone.
    """
    return _explainer(request, "methods", "help/methods.html")


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
#: **This table does not decide whether an operator's glossary narrows.** Whether
#: the glossary should
#: narrow to the terms their deployment uses is a product question left open here.
#: What cannot be left
#: alone is the consequence of hiding pages: those five Help pages are
#: hidden when the deployment does not run the domains they explain, so a
#: definition telling the reader to "See Help > Allocations & Ceilings" was
#: sending them at a 404. A cross-reference to a page that is not there is a
#: wrong instruction, not a gap (the same holds for the Setup Wizard's
#: step numbers).
#:
#: The pointer is dropped, never rewritten. The definition before it stands on
#: its own; a dictionary entry does not need a "read more" to be a definition.
_GLOSSARY_HELP_POINTERS = {
    "Allocations & Ceilings": "budgets_allocations",
    "Methods Behind the Numbers": "methods",
    "How Water Balances Work": "water_balances",
    "Settings explained": "settings_explained",
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


def _glossary_entries(terms: dict[str, str]) -> list[dict]:
    """The glossary table rows: terms sorted, help pointers split off, reporting terms gated."""
    if not is_enabled("reporting"):
        # Reporting is off unless a site names it (2026-10-12): with it off, no
        # page names the state's reporting systems, the glossary included.
        terms.pop("GEARS", None)
        terms.pop("CalWATRS", None)
    entries = []
    for term, definition in sorted(terms.items(), key=lambda item: item[0].casefold()):
        text, pointer_page, pointer_url = _split_help_pointer(
            _without_unavailable_help_pointers(definition)
        )
        entries.append({
            "term": term,
            "letter": term[0].upper(),
            "text": text,
            "pointer_page": pointer_page,
            "pointer_url": pointer_url,
        })
    return entries


@public_in_open_demo
def glossary(request):
    """Glossary of the terms this platform uses, for the operator running it.

    **This is a software glossary, not a hydrology one (DESIGN.md copy rule 11).**
    Every reader knows water (an agency or district engineer, a grower, a ditch
    tender, a drinking-water operator), so an entry answers
    *what does this platform mean by X and what does it hold against one* — never
    *what is X*. "Well" does not read
    "A borehole used to draw groundwater", which would tell a thirty-year groundwater
    professional what a well is; it names the record and its fields.

    Three things stay explainable forever and are the legitimate half of the
    boundary: agency and program names with their expansions (CalWATRS, CDEC,
    CIMIS, GEARS, GSA, GSP, OpenET, SGMA, USGS), codes inside data this platform
    did not author, and this platform's own coined concepts (Allocation Ceiling,
    Use Area, Ledger Entry).

    **A deployment never narrows the membership.** The glossary holds the
    same entries on every deployment; a reduced deployment narrows the
    *pointers*, not the dictionary. Only words that a screen, form or public
    guide uses have an entry. A
    definition defines and points to the Help page that explains; the
    explaining stays on that page. And the ``See Help > X.`` sentences are matched byte-for-byte by
    ``_without_unavailable_help_pointers`` above: reword one and it stops being
    stripped, which sends a reduced-deployment reader at a 404
    (``tests/test_help_explainers.py`` guards it).

    **The page is one table.** Each entry is a row: the
    term, the definition with its pointer split off by ``_split_help_pointer``,
    and the pointer as a link in the Read more column, empty where there is none.
    The letter headings that a script used to insert into a ``<dl>`` are rows the
    template renders where the first letter changes, so the jump nav's anchors
    exist without JavaScript. The definitions use DESIGN.md copy rule 12's names: an old name says first which name the
    screens use, and an entry says what the platform holds or does and stops.
    """
    terms = {
        "Allocation Ceiling": "The limit, in acre-feet, that an administrator or operator sets for one zone, one water type and one water year. See Help > Allocations & Ceilings.",
        "Allocation": "One account's share of a zone's groundwater allocation ceiling for a water year. See Help > Allocations & Ceilings.",
        "Analyte": "OpenH2O's record of one analyte, with its name and, when known, its four-digit analyte code from the State Water Board's Division of Drinking Water (DDW). OpenH2O adds a record for each new analyte it finds in an imported lab file.",
        "CalWATRS": "California Water Accounting, Tracking, and Reporting System, the State Water Board's system for reporting surface water diversions. OpenH2O does not submit reports to the state.",
        "CDEC": "California Data Exchange Center, where the California Department of Water Resources publishes real-time station readings.",
        "CFS (Cubic Feet per Second)": "The unit OpenH2O uses for rates: the maximum rate on a point of diversion and on a water right, and the maximum flow rate on a monthly diversion record.",
        "CIMIS": "California Irrigation Management Information System, the California Department of Water Resources' network of agricultural weather stations.",
        "Crop ET (Evapotranspiration)": "A field's crop evapotranspiration for the month, in acre-feet. OpenH2O reads it from OpenET. See Help > How Water Balances Work.",
        "Data Source": "OpenH2O's record of one outside agency or service that OpenH2O reads data from. It holds the source's name, code and web address, how often OpenH2O reads it and the time of the last read.",
        "Delivery Settings": "The screen where an administrator sets the default irrigation efficiency, the treatment of surface water in excess of ETAW, the year-end choice for unused allocation, the reporting year and the web address used in each record's permanent address. See Help > Settings explained.",
        "DLR": "Detection Limit for purposes of Reporting. OpenH2O stores the DLR that a lab file lists for each result, exactly as reported and in the result's units, and shows it on the result's page under the lab file's MCL.",
        "Effective Precipitation": "OpenH2O estimates each field's effective precipitation for the month from rainfall in the gridMET weather dataset. By default it uses the USDA-SCS method. See Help > Methods Behind the Numbers.",
        "ELAP": "Environmental Laboratory Accreditation Program, California's program for accrediting laboratories. OpenH2O stores the ELAP certification number of the laboratory that ran each result and shows it on the result's page.",
        "ETAW (Evapotranspiration of Applied Water)": "A field's crop ET minus its effective precipitation for the month. See Help > Methods Behind the Numbers.",
        "ETAW Met by Surface Water": "The part of a field's ETAW that its surface water delivery meets. It is the delivery times the field's irrigation efficiency or the month's ETAW, whichever is smaller. See Help > Methods Behind the Numbers.",
        "ETAW Met by Groundwater": "The part of a field's ETAW that surface water does not meet, when the field has a well. If the well has no meter, the month's calculated row on the Use Ledger holds this figure. See Help > Methods Behind the Numbers.",
        "Groundwater Extraction": "The groundwater a well pumps in a month. OpenH2O uses the meter reading where the well has a meter, and otherwise divides ETAW met by groundwater by the field's irrigation efficiency. See Help > Methods Behind the Numbers.",
        "Surface Water in Excess of ETAW": "The amount by which a field's surface water delivery times its irrigation efficiency exceeds its ETAW for the month. See Help > Settings explained.",
        "GEARS": "Groundwater Extraction Annual Reporting System, the State Water Board's system for annual reports of groundwater extraction. OpenH2O does not submit reports to the state.",
        "GSA": "Groundwater Sustainability Agency, a local agency that manages groundwater in a basin under SGMA.",
        "GSP": "Groundwater Sustainability Plan, the plan under SGMA for managing a basin's groundwater.",
        "Health Check": "One of OpenH2O's checks on this site's records and server. Each result is green, yellow or red and carries a message. The Site health page shows the latest result of each check.",
        "Ledger Entry": "One row on the Use Ledger, with its date, use area, water type, amount in acre-feet and description. Negative amounts are water delivered or pumped, and positive amounts are credits.",
        "Managed Aquifer Recharge (MAR)": "OpenH2O keeps managed aquifer recharge as one record for each recharge site, with its capacity in acre-feet, its zone, its location and outline on the map, the points of diversion that feed it and its recharge events. Each recharge event has its dates, a volume in acre-feet and a water type.",
        "MCL": "Maximum Contaminant Level. OpenH2O stores the MCL that a lab file lists for each result, exactly as reported and in the result's units, and shows it on the result's page and the sampling point's page.",
        "Methodology / Calculation Plan": "The calculation steps on Methodology Settings and the choices that go with them: the order of the steps, which steps are switched on, the effective precipitation method and the lowest remainder. See Help > Settings explained.",
        "Monitoring Station": "OpenH2O's record of one outside station, such as a stream gauge, a weather station or a groundwater level well. The record holds the station's name, its ID at the data source, its location and the parameters it reports.",
        "OpenET": "A service that estimates evapotranspiration from satellite data. It is the source of OpenH2O's crop ET.",
        "Use Area": "OpenH2O's record of one field, with its Assessor Parcel Number (APN), owner, area in acres and outline on the map. OpenH2O calculates each month's figures for every use area.",
        "PS Code": "Primary Station Code, the identifier of one sampling point. For a California water system, it is the PWSID, the state's facility ID and the point number, joined by underscores. For a system in another state, it is the code the lab results file uses. OpenH2O files each imported lab result under the sampling point with that PS Code, and rejects a row when no sampling point on file has its PS Code.",
        "PWSID": "Public Water System Identification number. When an administrator or operator enters a PWSID on Add a water system, OpenH2O reads the system and its facilities from EPA's records. Every California PS Code begins with the system's PWSID.",
        "Point of Diversion (POD)": "OpenH2O's record of one point of diversion, with its location, the water right it diverts under, its stream or flowline, its maximum rate in CFS, its canal losses, the use areas it serves and its monthly diversion records.",
        "Sampling Schedule": "The checklist of samples taken on a cycle at a drinking-water system. Each row holds what is sampled, the frequency, the date last done and the date next due. Both dates are entered by hand; OpenH2O does not calculate the next due date from the frequency.",
        "Reporting Level": "OpenH2O stores the reporting level that a lab file lists for each numeric result. When a result is marked Less Than Reporting Level, OpenH2O shows it as < and that level, such as < 0.005 mg/L, or as < RL when no level is given.",
        "Water Year": "OpenH2O's record of one accounting period on the Water Years page, with its name and its start and end dates. While a water year is finalized, its ledger entries, allocations, diversion records and calculation results cannot be added, changed or removed.",
        "Sampling Point": "OpenH2O's record of one place on a facility where samples are taken, with its PS Code, a name and a point type. An administrator or operator adds sampling points on the water system's Sampling points page, and OpenH2O builds each PS Code for a California water system.",
        "SGMA": "Sustainable Groundwater Management Act, California's 2014 law under which GSAs manage groundwater basins.",
        "Up to date / Slightly behind / Dormant": "OpenH2O labels each station on the Monitoring stations page by the age of its latest reading, measured against how often the station's source usually publishes (CDEC and CNRFC 36 hours; USGS and CIMIS 2 days; NOAA 3 days; OpenET 45 days; DWR-WDL and DWR-SGMA 120 days; any other source 1 day). A station is Up to date within 1.5 times its source's interval, Slightly behind within 4 times, and Dormant after that or with no reading at all.",
        "USGS": "United States Geological Survey. OpenH2O reads stream flow and groundwater levels from USGS stations.",
        "Water Account": "OpenH2O's record of one account, with its name, account number, contact, status and the use areas it holds. OpenH2O works out the account's allocation and remaining allocation from those use areas. See Help > Allocations & Ceilings.",
        "Water Right": "OpenH2O's record of one water right, with its state ID, type, holder, priority date, face value in acre-feet, diversion seasons and status, and the use areas in its place of use.",
        "Zone / Management Zone": "OpenH2O's record of one area that has its own allocation ceilings. It holds the zone's name, type, outline on the map and the use areas assigned to it. See Help > Allocations & Ceilings.",
        "Well": "OpenH2O's record of one well, with its state well number, well completion report (WCR) number, local ID, meters, depth, casing and screen interval, and the use areas it irrigates.",
    }
    entries = _glossary_entries(terms)
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
            # No message here: the profile shows messages
            # ("You changed your password."), and "Profile updated." is not a
            # sentence this site uses. It never showed on this page before; it waited
            # and surfaced on the next page that shows messages.
            return redirect("profile")
    else:
        form = ProfileForm(instance=request.user)
    # A host administrator's sign-in card depends on whether another
    # active host administrator can change their address on the Users page.
    from core.models import User

    other_host_exists = (
        request.user.is_staff
        and User.objects.filter(is_staff=True, is_active=True)
        .exclude(pk=request.user.pk)
        .exists()
    )
    return render(
        request,
        "core/profile.html",
        {"form": form, "other_host_exists": other_host_exists},
    )
