from core.models import SiteConfig


def site_config(request):
    return {"site_config": SiteConfig.objects.first()}
