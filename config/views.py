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
