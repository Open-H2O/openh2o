# SPDX-License-Identifier: AGPL-3.0-or-later
"""``{% persistent_identifier record as uri %}``: a record's /id/ address.

The one place a template gets a record's persistent identifier
(``templates/partials/_identifier_line.html`` is the one caller), so the page
and the JSON-LD document can never print two different addresses. It reads
``site_config`` from the context the ``core.context_processors.site_config``
processor already put there, rather than querying ``SiteConfig`` again per
record.
"""
from django import template

from core.identifiers import identifier_base, identifier_for

register = template.Library()


@register.simple_tag(takes_context=True)
def persistent_identifier(context, record):
    if "site_config" in context:
        config = context["site_config"]
        host = getattr(config, "identifier_host", "") or ""
    else:
        host = None  # not rendered through the processors: read the setting
    base = identifier_base(context.get("request"), host=host)
    return identifier_for(record, base=base)
