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


# Concrete adapters are imported in Task 2. Until then the registry is empty
# but the framework is functional (commands will report "no adapter").
