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


# Import all concrete adapters to auto-populate the registry.
# Each module calls register_adapter() at import time.
from datasync.adapters.cdec import CDECAdapter  # noqa: F401
from datasync.adapters.cimis import CIMISAdapter  # noqa: F401
from datasync.adapters.cnrfc import CNRFCAdapter  # noqa: F401
from datasync.adapters.dwr_sgma import DWRSGMAAdapter  # noqa: F401
from datasync.adapters.dwr_wdl import DWRWDLAdapter  # noqa: F401
from datasync.adapters.noaa import NOAAAdapter  # noqa: F401
from datasync.adapters.openet import OpenETAdapter  # noqa: F401
from datasync.adapters.usgs import USGSAdapter  # noqa: F401
