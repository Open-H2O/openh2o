# SPDX-License-Identifier: AGPL-3.0-or-later
"""The History panel on a record's page (147-01).

``{% change_history_panel obj %}`` shows the last ten changes to one record.
``{% change_history_panel record_type="accounting.CalculationStep" %}`` shows
the last ten changes to every record of one type, for a page that edits a set
of records rather than one (the methodology page's steps). ``fields=`` limits
the panel to the named fields (the delivery settings page shows the history
of the settings it edits, not every column of the settings row). Both link to the
Change history page filtered the same way. Rows come from ``core/changes.py``.
"""
from urllib.parse import urlencode

from django import template
from django.urls import reverse

from core import changes

register = template.Library()


@register.inclusion_tag("partials/_change_history.html")
def change_history_panel(obj=None, record_type="", heading="History", fields=None):
    if obj is not None:
        rows = changes.changes_for(obj, fields=fields)
        query = {"type": obj._meta.label, "record": obj.pk}
        # A record whose history takes in its linked records (a well's use
        # area shares) names which record each row is about.
        show_record = bool(changes.related_records(obj._meta.label))
    else:
        filters = changes.build_filters(record_type=record_type)
        rows = changes.recent_changes(filters, per_page=changes.PANEL_SIZE).object_list
        query = {"type": record_type}
        show_record = True
    return {
        "rows": rows,
        "heading": heading,
        "show_record": show_record,
        "see_all_url": f"{reverse('change_history')}?{urlencode(query)}",
    }
