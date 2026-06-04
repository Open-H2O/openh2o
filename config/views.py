# SPDX-License-Identifier: AGPL-3.0-or-later
import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse

from datasync.models import MonitoredStation
from parcels.models import Parcel
from recharge.models import RechargeSite
from surface.models import WaterRight
from wells.models import Well
from accounting.models import WaterAccount


def index(request):
    """Render the index/status page, or redirect logged-in users to dashboard."""
    if request.user.is_authenticated:
        return redirect(reverse("accounting:dashboard"))
    context = {
        "parcel_count": Parcel.objects.count(),
        "well_count": Well.objects.count(),
        "water_right_count": WaterRight.objects.count(),
        "recharge_site_count": RechargeSite.objects.count(),
        "water_account_count": WaterAccount.objects.count(),
        "station_count": MonitoredStation.objects.count(),
    }
    return render(request, "index.html", context)


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
    """Explainer: how a zone water budget becomes each account's allocation."""
    return render(request, "help/budgets_allocations.html")


@login_required
def surface_deliveries(request):
    """Explainer: the two agency delivery settings, in plain language."""
    return render(request, "help/surface_deliveries.html")


@login_required
def glossary(request):
    """Glossary of water accounting terms used throughout the platform."""
    terms = {
        "Water Budget": "The total volume of water assigned to a zone for a reporting period, set per zone, water type, and period. It is the policy ceiling for a whole area. The platform divides it into per-account Allocations. See Help > Water Budgets & Allocations.",
        "Allocation": "A single account's share of a zone's Water Budget, pro-rated by how many parcels the account holds in the zone. Allocation minus usage gives the account's remaining water; a negative remaining is an overdraft. See Help > Water Budgets & Allocations.",
        "Usage": "Water consumed via extraction (well meters) or evapotranspiration (ET estimates), recorded as negative ledger entries.",
        "CalWATRS": "California Water Transfer Reporting System, the Water Board format for surface diversions.",
        "CDEC": "California Data Exchange Center, real-time hydrologic data from DWR.",
        "CFS (Cubic Feet per Second)": "A rate of flow used for surface water diversions; a point of diversion popup shows a rate like \"50.00 cfs.\" One CFS is about 1.9835 acre-feet per day.",
        "CIMIS": "California Irrigation Management Information System, weather station data for agriculture.",
        "Curtailment": "A State Water Board order to reduce or stop diverting under a water right, usually during drought. A right's curtailment status appears on its water-right detail card.",
        "Delivery Settings": "Two agency-wide settings that shape how surface-water deliveries are counted: how much of a delivery the crop actually uses (the rest recharges the aquifer), and what happens to a district's unused water at year-end (carry it forward or let it expire). Set by the analyst on the Delivery Settings page. See Help > Surface Delivery Settings.",
        "Data Source": "An external agency or API that provides hydrologic measurements.",
        "ET (Evapotranspiration)": "The water consumed by crops — evaporation from the soil plus transpiration through the plants. The methodology's first step estimates groundwater use from ET. (OpenET is the satellite data source; ET is the quantity it measures.)",
        "GEARS": "Groundwater Extraction Annual Report System, the State Water Board reporting format for per-well extraction.",
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
        "Water Year": "A time window (usually October 1 through September 30) for water accounting and reporting.",
        "SGMA": "Sustainable Groundwater Management Act (2014), the California law requiring groundwater management.",
        "USGS": "United States Geological Survey, provides stream gauge and groundwater level data.",
        "Water Account": "Groups use areas for accounting purposes, tracks supply and usage.",
        "Water Right": "A legal entitlement to divert surface water, issued by the State Water Board.",
        "Zone / Management Zone": "A sub-area of the district that carries its own Water Budget. Each use area belongs to a zone, and a zone must exist before a Water Budget can be set for it. See Help > Water Budgets & Allocations.",
        "Extraction Well": "A borehole used to extract groundwater, identified by state well number or local ID.",
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
