# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Drinking water views, one module per screen.

These serve a public water system's records: its identity and facilities, its
sampling points and sample results, the lab-file import, onboarding, the
production year and the sampling schedule. No view compares a result against a
limit or colors a row by it: showing a result and showing what the limit is are
both facts, but rendering a verdict is a regulatory determination this platform
does not make (see ``drinking/models.py``). The list and detail pages are
read-only; the write paths are the lab-file import, onboarding, the production
add and import, the facility add and edit forms and the schedule forms, each a
full page of its own, plus Django admin for one-off corrections.

``overview``: the system's front door.
``facilities``: the facility list and detail pages, the add and edit forms, and the map data.
``sampling_points``: the sampling-point list and detail page.
``results``: the sample-result list and detail page.
``lab_import``: the lab-file import (page, preview, commit).
``onboard``: onboarding from EPA's public record, then the sampling-point builder.
``production``: production by month and source, by hand or by file.
``schedule``: the sampling schedule.
``common``: helpers that more than one of these modules uses.
"""
