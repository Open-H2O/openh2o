# SPDX-License-Identifier: AGPL-3.0-or-later
"""
OpenET's field-list route: the adapter ``OPENET_MODE=fields`` (the default) selects.

The work is in :mod:`datasync.field_list` (the three kinds of request, the shares, the
depths) and in the ``sync_openet_parcels`` command (setup that resumes, the monthly
figures). This class is the route's name in ``get_openet_adapter()``. It keeps the account
status of the REST adapter, which is free, and it takes no station or parcel-window request:
a field list answers for fields, not for one use area at a time.
"""

from datasync.adapters.openet import OpenETAdapter


class FieldListOpenETAdapter(OpenETAdapter):
    source_code = "openet_fields"

    def sync_parcel_et(self, *args, **kwargs):
        raise NotImplementedError(
            "The field-list route is run by sync_openet_parcels, which asks OpenET in "
            "lookups, outlines and figures; it has no request per use area."
        )
