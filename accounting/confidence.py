# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read the stored OpenET member-model bounds. NOT SHOWN TO USERS.

OpenET publishes one ET number per parcel-month: the mean of six independent
models (DisALEXI, eeMETRIC, geeSEBAL, PT-JPL, SIMS, SSEBop) after a
median-absolute-deviation filter drops outliers (Melton et al. 2022). This
platform uses that ensemble value as a stand-in for a meter where no meter
exists, and it is the only ET figure the accounting engine reads
(accounting.steps, variable="ET", model="Ensemble").

The member bounds and survivor count are collected and cached alongside it.
On the Earth Engine tier they ride along as extra bands on a reduction we run
anyway, so collection is effectively free.

WHY THEY ARE NOT DISPLAYED
--------------------------
They were briefly rendered on the calculation audit page. That was withdrawn,
and the reasoning should survive so it is not rebuilt:

* The models disagree BY CONSTRUCTION — some are thermal (eeMETRIC), some are
  vegetation-index based (SIMS). Spread is the expected input to the ensemble,
  not evidence the ensemble is wrong. The MAD-filtered mean IS this platform's
  treatment of that spread; it is not an unhandled problem.

* Publishing the bounds beside the governing figure creates a gaming surface.
  A grower with an incentive to show less water use can point at the low bound
  as an official number the platform itself displayed — on the very page that
  explains how a billable figure was derived. The agency then carries the
  burden of rebutting its own UI. That is a self-inflicted wound on a
  regulatory tool.

* An earlier version also GRADED the bounds into a confidence verdict. Doubly
  withdrawn: member spread is not the error bar of the ensemble mean (averaging
  estimators with different biases reduces error), and the metric used relative
  width, which tracks the size of the number rather than model disagreement —
  measured on the live demo, parcels under 10 mm of ET graded "low" 100% of the
  time while parcels above 80 mm, where the water is, graded "low" 1% of the
  time.

WHAT THEY ARE GOOD FOR
----------------------
Internal triage, not disclosure. Extreme model disagreement usually indicates a
problem with the PARCEL rather than uncertainty in the water number — mixed land
cover inside the polygon, cloud contamination, a geometry error, a tree crop
confusing the vegetation-index models. If these are ever surfaced it should be a
staff-facing "parcels worth reviewing" list, never a second number standing
beside the one that governs.

This module is that accessor. It has no user-facing caller by design.
"""

from dataclasses import dataclass

MODEL_TOTAL = 6

ABSENT_TOKEN = "—"


@dataclass(frozen=True)
class EnsembleConfidence:
    """What the member models said for one parcel-month. Facts, not a verdict."""

    value_mm: object = None
    low_mm: object = None
    high_mm: object = None
    model_count: object = None

    @property
    def has_range(self):
        """True only when BOTH bounds are present and actually bracket a span.

        One bound is not a range, and equal bounds would render as a point
        estimate carrying implied perfect precision. Both cases show nothing.
        """
        if self.low_mm is None or self.high_mm is None:
            return False
        return self.high_mm > self.low_mm

    @property
    def has_agreement(self):
        return self.model_count is not None

    @property
    def is_known(self):
        """Whether any provenance was retrieved for this parcel-month."""
        return self.has_range or self.has_agreement

    @property
    def token(self):
        """The survivor count as text, e.g. "6/6".

        Text, not colour, so it survives greyscale printing and colour-vision
        deficiency (WCAG 1.4.1) — these figures reach printed filings. Returns
        an em dash when the count was never retrieved: absent and zero are
        different facts, and "0/6" would assert something false.
        """
        if not self.has_agreement:
            return ABSENT_TOKEN
        return f"{int(self.model_count)}/{MODEL_TOTAL}"


def parcel_ensemble_confidence(parcel, period, model="Ensemble"):
    """Assemble the ensemble provenance for one parcel-month.

    Reads through accounting.steps._read_cache_mm — the single shared cache
    reader — so these variables can never drift from ET on the
    variable/model/key strings. A missing row yields None for that component
    rather than a default, keeping "not collected" distinguishable from
    "collected and narrow".
    """
    from accounting.steps import _read_cache_mm

    def read(variable, key=None):
        # ET is the one variable whose payload key differs from its variable
        # name ("ET" / "et"); precip and the spread variables key on their own
        # name. Passing the key explicitly keeps that asymmetry visible rather
        # than letting a lowercase() guess match zero rows and read as 0.
        total, months_matched, _rows = _read_cache_mm(
            parcel, period, variable, model, key or variable
        )
        # months_matched == 0 means no row carried this variable this month.
        # _read_cache_mm returns Decimal("0") on a miss, which is a real value
        # for ET and a lie for a bound — hence the explicit miss check.
        return total if months_matched else None

    count = read("model_count")
    return EnsembleConfidence(
        value_mm=read("ET", "et"),
        low_mm=read("et_mad_min"),
        high_mm=read("et_mad_max"),
        # The count is a per-pixel spatial mean over the parcel, so it arrives
        # fractional (4.86, not 5). Rounded for display only; the underlying
        # value stays in the cache row.
        model_count=round(float(count)) if count is not None else None,
    )
