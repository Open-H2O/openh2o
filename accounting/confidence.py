# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ensemble confidence: how much the satellite ET models actually agreed.

OpenET reports a single ET number per parcel-month, and until now the platform
filed that number as though it were exact. It is not. The "Ensemble" value is
the mean of the six member models that survived a median-absolute-deviation
outlier filter (Melton et al. 2022) — a modeled estimate with a knowable spread
that OpenET computes and we were discarding.

This module turns the stored spread rows into two separate signals, because
they answer two different questions:

  * The RANGE (et_mad_min .. et_mad_max) is a magnitude — how wide the surviving
    models spread, in the same millimetres as the value itself.
  * The AGREEMENT (model_count) is a quality judgment — how many of the six
    survived the filter at all.

Deliberately NOT reusing the green/yellow/red vocabulary from health.checks.
That palette means "system fault", and low model agreement is not a fault: it
means the models disagree here and the number deserves a second look. Painting
it red would teach operators to read uncertainty as error.

Accessibility: ``token`` (e.g. "4/6") always carries the agreement signal in
text. Colour may reinforce it, never replace it — WCAG 1.4.1, and these figures
end up in filings that get printed in greyscale.
"""

from dataclasses import dataclass

MODEL_TOTAL = 6

# Agreement bands, keyed on how many of the six member models survived the MAD
# filter. Thresholds are conservative: 6/6 is genuinely common on well-behaved
# irrigated cropland, so treating 5/6 as already "moderate" keeps the top band
# meaningful instead of universal.
UNKNOWN_LEVEL = "unknown"
AGREEMENT_BANDS = (
    # (minimum surviving models, level, plain-English label)
    (6, "high", "Models agree closely"),
    (5, "moderate", "Minor disagreement"),
    (4, "guarded", "Notable disagreement"),
    (0, "low", "Models diverge — verify"),
)
UNKNOWN_LABEL = "Agreement not retrieved"


@dataclass(frozen=True)
class EnsembleConfidence:
    """Spread and agreement for one parcel-month of ensemble ET."""

    value_mm: object = None
    low_mm: object = None
    high_mm: object = None
    model_count: object = None

    @property
    def has_range(self):
        """True only when BOTH bounds are present and actually bracket a span.

        A single bound is not a range, and a zero-width range is a claim of
        perfect precision we have no basis for — in both cases the honest
        display is no range at all.
        """
        if self.low_mm is None or self.high_mm is None:
            return False
        return self.high_mm > self.low_mm

    @property
    def has_agreement(self):
        return self.model_count is not None

    @property
    def level(self):
        if not self.has_agreement:
            return UNKNOWN_LEVEL
        count = int(self.model_count)
        for threshold, level, _label in AGREEMENT_BANDS:
            if count >= threshold:
                return level
        return UNKNOWN_LEVEL

    @property
    def label(self):
        if not self.has_agreement:
            return UNKNOWN_LABEL
        count = int(self.model_count)
        for threshold, _level, label in AGREEMENT_BANDS:
            if count >= threshold:
                return label
        return UNKNOWN_LABEL

    @property
    def token(self):
        """The agreement signal as text, e.g. "4/6".

        This is what makes the badge readable without colour. Returns an em-dash
        rather than a fake "0/6" when the count was never retrieved — absent and
        zero are different facts.
        """
        if not self.has_agreement:
            return "—"
        return f"{int(self.model_count)}/{MODEL_TOTAL}"


def parcel_ensemble_confidence(parcel, period, model="Ensemble"):
    """Build the confidence signal for one parcel-month.

    Reads through accounting.steps._read_cache_mm — the single shared cache
    reader — so the spread variables can never drift from ET on the
    variable/model/key strings. A missing spread row yields None for that
    component rather than a default, so "not fetched" stays distinguishable
    from "fetched and narrow".
    """
    from accounting.steps import _read_cache_mm

    def read(variable, key=None):
        # ET is the one variable whose payload key differs from its variable name
        # ("ET" / "et"); precip and the spread variables key on their own name.
        # Passing the key explicitly keeps that asymmetry visible rather than
        # letting a lowercase() guess silently match zero rows and read as 0.
        total, months_matched, _rows = _read_cache_mm(
            parcel, period, variable, model, key or variable
        )
        # months_matched == 0 means no row carried this variable for this month.
        # _read_cache_mm returns Decimal("0") in that case, which is a real value
        # for ET and a lie for a bound — hence the explicit miss check.
        return total if months_matched else None

    value = read("ET", "et")
    count = read("model_count")
    return EnsembleConfidence(
        value_mm=value,
        low_mm=read("et_mad_min"),
        high_mm=read("et_mad_max"),
        # model_count is a tally, not a depth — _read_cache_mm sums across the
        # month's items, which for a single monthly value is that value. Round
        # defensively so a float round-trip can't render "5.999999/6".
        model_count=round(float(count)) if count is not None else None,
    )
