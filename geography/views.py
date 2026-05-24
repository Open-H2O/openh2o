from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def map_view(request):
    """Map page shell. Loads MapLibre GL JS via the map_scripts block."""
    return render(request, "geography/map.html")
