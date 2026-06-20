# SPDX-License-Identifier: AGPL-3.0-or-later
import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from datasync import freshness
from datasync.models import DataSyncLog, MonitoredStation
from parcels.models import Parcel
from recharge.models import RechargeSite
from surface.models import WaterRight
from wells.models import Well
from accounting.models import WaterAccount
from core.models import SiteConfig


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
    context = {
        "parcel_count": Parcel.objects.count(),
        "well_count": Well.objects.count(),
        "water_right_count": WaterRight.objects.count(),
        "recharge_site_count": RechargeSite.objects.count(),
        "water_account_count": WaterAccount.objects.count(),
        "station_count": MonitoredStation.objects.count(),
    }
    if not request.user.is_authenticated:
        return render(request, "index.html", context)

    # Status-hero data — every value is real, never decorative.
    now = timezone.now()
    site_config = SiteConfig.objects.first()
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
            "greeting": _greeting(now),
            "agency_name": site_config.agency_name if site_config else "Your Agency",
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


def about(request):
    """Public About page with policy timeline and platform purpose."""
    logo_path = os.path.join(settings.BASE_DIR, "static", "img", "logo.png")
    return render(request, "about.html", {"logo_exists": os.path.isfile(logo_path)})


@login_required
def getting_started(request):
    """Getting Started walkthrough for new GSA administrators."""
    return render(request, "help/getting_started.html")


@login_required
def budgets_allocations(request):
    """Explainer: how a zone allocation ceiling becomes each account's allocation."""
    return render(request, "help/budgets_allocations.html")


@login_required
def surface_deliveries(request):
    """Explainer: the two agency delivery settings, in plain language."""
    return render(request, "help/surface_deliveries.html")


@login_required
def water_balances(request):
    """Conceptual explainer: ET as estimated use, supplies reconciled against it."""
    return render(request, "help/water_balances.html")


@login_required
def methods(request):
    """Explainer: the calculation chain and the two ET-demand allocation services."""
    return render(request, "help/methods.html")


@login_required
def settings_explained(request):
    """Explainer: every agency-wide configuration knob, what it does and when to change it."""
    return render(request, "help/settings_explained.html")


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
    sorted_terms = sorted(terms.items())
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
