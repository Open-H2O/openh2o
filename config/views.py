from django.shortcuts import render


def index(request):
    """Render the index/status page."""
    return render(request, "index.html")
