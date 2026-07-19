# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ensemble provenance: what the six satellite models actually said.

OpenET publishes one ET number per parcel-month. That number is the mean of
six independent research models (DisALEXI, eeMETRIC, geeSEBAL, PT-JPL, SIMS,
SSEBop) after discarding any that a median-absolute-deviation filter marks as
an outlier (Melton et al. 2022). The platform files the mean and, until now,
showed nothing about how it was produced.

This module surfaces two facts that OpenET computes and we were discarding:

  * ``model_count`` — how many of the six survived the outlier filter.
  * ``low_mm`` / ``high_mm`` — the lowest and highest of those survivors.

IT DELIBERATELY DOES NOT GRADE THEM.

An earlier version of this file scored the pair into a confidence verdict
("Models agree closely" / "Models diverge — verify"). That was withdrawn, for
two reasons worth recording so it is not reinvented:

1. Spread between members is NOT the error bar of the ensemble mean. Averaging
   estimators with different biases REDUCES error — that is the entire reason
   an ensemble exists. Wide member spread with a well-behaved mean can still be
   a sound estimate, so treating spread as the mean's uncertainty overstates
   alarm.

2. The verdict keyed on RELATIVE width (range ÷ value) against invented
   thresholds, and relative width is dominated by the denominator. Measured on
   the live Merced demo: parcels under 10 mm of ET had a median relative width
   of 200% and graded "low" 100% of the time, while parcels above 80 mm — where
   the water and the money actually are — had a median of 26% and graded "low"
   1% of the time. The flag was mostly detecting small numbers, and was closest
   to backwards on the parcels that matter most.

If a flag is wanted later, the defensible unit is ABSOLUTE VOLUME: convert the
spread to acre-feet at the parcel's acreage and set thresholds from what
materially moves a filing. A percentage is not that.

None of these values enter the calculation. The accounting engine reads only
variable="ET", model="Ensemble" (accounting.steps). This is provenance shown
beside a number, never an input to it.
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
