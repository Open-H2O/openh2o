# SPDX-License-Identifier: AGPL-3.0-or-later
"""Agency-wide delivery-policy constants.

Defined in one place so the recovery-horizon choice strings never get re-typed
(and silently drift) across the four places that reference them:
``core.models.SiteConfig`` (the agency default), ``geography.models.Zone`` (the
per-district override), ``accounting.services.resolve_recovery_horizon`` (the
resolver), and ``accounting.management.commands.rollover_allocations`` (the
consumer). Plain module-level constants — no Django imports — so any of those can
import them without an app-load cycle.
"""

# How a district's unused water budget is treated at the close of a water year.
CARRY_FORWARD = "carry_forward"  # surplus banks forward as an opening credit
SAME_WATER_YEAR = "same_water_year"  # surplus expires; use-it-or-lose-it

RECOVERY_HORIZON_CHOICES = [
    (CARRY_FORWARD, "Carry unused water forward as a credit"),
    (SAME_WATER_YEAR, "Unused water expires at year-end"),
]
