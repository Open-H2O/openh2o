from django.shortcuts import redirect, render
from django.urls import reverse


def index(request):
    """Render the index/status page, or redirect logged-in users to dashboard."""
    if request.user.is_authenticated:
        return redirect(reverse("accounting:dashboard"))
    return render(request, "index.html")
