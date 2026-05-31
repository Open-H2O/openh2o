# SPDX-License-Identifier: AGPL-3.0-or-later
from django.conf import settings

from core.models import SiteConfig


def site_config(request):
    return {"site_config": SiteConfig.objects.first()}


def analytics(request):
    """Expose Umami config to templates. Both values are blank/default on a
    fresh clone, so the tracking tag stays absent unless a deployment opts in
    by setting UMAMI_WEBSITE_ID in its environment."""
    return {
        "umami_website_id": settings.UMAMI_WEBSITE_ID,
        "umami_script_url": settings.UMAMI_SCRIPT_URL,
    }
