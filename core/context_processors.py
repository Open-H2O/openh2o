# SPDX-License-Identifier: AGPL-3.0-or-later
from core.models import SiteConfig


def site_config(request):
    return {"site_config": SiteConfig.objects.first()}
