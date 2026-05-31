"""
Adapter registry for external data sources.

Each concrete adapter auto-registers by being imported here.
Use get_adapter(source_code) to get an instantiated adapter.
"""

ADAPTER_REGISTRY = {}


def register_adapter(source_code, adapter_class):
    """Register an adapter class for a source code."""
    ADAPTER_REGISTRY[source_code] = adapter_class


def get_adapter(source_code):
    """Return an instantiated adapter for the given source code, or None."""
    adapter_class = ADAPTER_REGISTRY.get(source_code)
    if adapter_class is None:
        return None
    return adapter_class()


def get_openet_adapter():
    """Return the OpenET adapter for the active tier.

    This is the ONE place OPENET_MODE decides the faucet: "gee" routes the live
    sync through the batched Earth Engine adapter; anything else (default "api")
    keeps the REST tier. REST stays the committed default — GEE is opt-in via a
    deploy's gitignored .env.
    """
    from django.conf import settings

    if getattr(settings, "OPENET_MODE", "api") == "gee":
        return GEEOpenETAdapter()
    return OpenETAdapter()


# Import all concrete adapters to auto-populate the registry.
# Each module calls register_adapter() at import time.
from datasync.adapters.cdec import CDECAdapter  # noqa: F401
from datasync.adapters.cimis import CIMISAdapter  # noqa: F401
from datasync.adapters.cnrfc import CNRFCAdapter  # noqa: F401
from datasync.adapters.dwr_sgma import DWRSGMAAdapter  # noqa: F401
from datasync.adapters.dwr_wdl import DWRWDLAdapter  # noqa: F401
from datasync.adapters.noaa import NOAAAdapter  # noqa: F401
from datasync.adapters.openet import OpenETAdapter  # noqa: F401,E402
from datasync.adapters.openet_gee import GEEOpenETAdapter  # noqa: F401,E402
from datasync.adapters.usgs import USGSAdapter  # noqa: F401

# Registry exports — available after all adapters are registered.
from datasync.adapters.registry import get_all_parameter_maps, get_parameter_label  # noqa: F401
