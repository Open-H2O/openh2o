import os

from django.conf import settings
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
def glossary(request):
    """Glossary of water accounting terms used throughout the platform."""
    terms = {
        "Water Budget": "The volume of water assigned to a use area (or zone) for a reporting period. It's the amount you're allowed to use, recorded as a positive ledger entry. Compare with Usage.",
        "Usage": "Water consumed via extraction (well meters) or evapotranspiration (ET estimates), recorded as negative ledger entries.",
        "CalWATRS": "California Water Transfer Reporting System, the Water Board format for surface diversions.",
        "CDEC": "California Data Exchange Center, real-time hydrologic data from DWR.",
        "CIMIS": "California Irrigation Management Information System, weather station data for agriculture.",
        "Data Source": "An external agency or API that provides hydrologic measurements.",
        "GEARS": "Groundwater Extraction Annual Report System, the State Water Board reporting format for per-well extraction.",
        "GSA": "Groundwater Sustainability Agency, the local agency responsible for managing groundwater under SGMA.",
        "GSP": "Groundwater Sustainability Plan, the 20-year plan each GSA must adopt.",
        "Health Check": "Automated system diagnostic covering data freshness, connectivity, and configuration.",
        "Ledger Entry": "A double-entry record: supply amounts are positive, usage amounts are negative.",
        "Managed Aquifer Recharge (MAR)": "Intentionally adding water to an aquifer through spreading basins or injection wells.",
        "Monitoring Station": "A curated external sensor (stream gauge, weather station, groundwater well) linked to a data source.",
        "OpenET": "Satellite-based evapotranspiration estimates, used to calculate crop water use.",
        "Use Area": "A plot of land identified by an Assessor Parcel Number (APN), the basic unit of water accounting.",
        "Point of Diversion (POD)": "The physical location where water is diverted from a stream or river.",
        "Water Year": "A time window (usually October 1 through September 30) for water accounting and reporting.",
        "SGMA": "Sustainable Groundwater Management Act (2014), the California law requiring groundwater management.",
        "USGS": "United States Geological Survey, provides stream gauge and groundwater level data.",
        "Water Account": "Groups use areas for accounting purposes, tracks supply and usage.",
        "Water Right": "A legal entitlement to divert surface water, issued by the State Water Board.",
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
