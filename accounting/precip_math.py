# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pure effective-precipitation math — the single most contested number here.

This module is intentionally Django-free (imports only ``decimal`` + ``math``)
so the part that actually needs proving — the USDA-SCS / TR-21 formula — has a
fast, real RED->GREEN test cycle in bare local Python. The thin cache-reading
wrapper that turns parcel-month rows into ``(P, ET)`` lives in
``accounting/steps.py`` and is DB-bound (tested in the running container).

"Effective precipitation" is the share of rainfall that actually contributes to
crop ET — what you may credit against gross satellite ET to get *net* consumptive
use. Over-crediting it directly understates billable groundwater, so the doctrine
(Phase 29-03) is that the math is proven against published reference values before
any parcel's bill depends on it.

Three methods (see 38-DESIGN.md Step 3):
  - raw      : Pe = P                (subtract all rainfall — crude, over-credits)
  - fraction : Pe = fraction * P     (flat haircut; default fraction 0.70)
  - usda_scs : USDA-SCS / TR-21, capped at both P and ET   (default)

USDA-SCS / TR-21 (P and ET in INCHES, monthly):
    Pe = SF * (1.25 * P**0.824 - 2.93) * 10**(0.000955 * ET)
    SF = 0.531747 + 0.295164*D - 0.057697*D**2 + 0.003804*D**3   (D = soil_storage_in)
    Pe = max(0, min(Pe, P, ET))                                  (cap at P and ET, floor at 0)

Reference: USDA-SCS TR-21 / FAO Irrigation & Drainage Paper 25; soil storage
factor SF(3.0 in) = 1.000674.
"""

import math
from decimal import Decimal


def _dec(x):
    """Coerce to Decimal without binary-float noise (Decimal passes through)."""
    return x if isinstance(x, Decimal) else Decimal(str(x))


def _storage_factor(soil_storage_in):
    """USDA-SCS storage factor SF for a given net soil moisture storage D (inches)."""
    d = float(soil_storage_in)
    return 0.531747 + 0.295164 * d - 0.057697 * d**2 + 0.003804 * d**3


def effective_precip_inches(
    p_in, et_in, *, method="usda_scs", fraction=0.70, soil_storage_in=3.0
):
    """Effective precipitation (inches) from monthly rainfall P and crop ET.

    Args:
        p_in: monthly precipitation, inches (Decimal/float/str).
        et_in: monthly crop ET, inches (Decimal/float/str).
        method: "raw" | "fraction" | "usda_scs".
        fraction: multiplier for method="fraction" (default 0.70).
        soil_storage_in: net soil moisture storage D for usda_scs (default 3.0 in).

    Returns:
        Decimal effective precipitation in inches. For usda_scs the result is
        capped at both P and ET and floored at 0, so 0 <= Pe <= min(P, ET).

    Raises:
        ValueError: for an unknown method — fail loud, never silently pass all
            rainfall through (which would over-credit and understate the bill).
    """
    p = _dec(p_in)
    et = _dec(et_in)

    if method == "raw":
        return p
    if method == "fraction":
        return _dec(fraction) * p
    if method == "usda_scs":
        sf = _storage_factor(soil_storage_in)
        pf = float(p)
        etf = float(et)
        # TR-21's P**0.824 term is only defined for non-negative rainfall.
        p_pow = math.pow(pf, 0.824) if pf > 0 else 0.0
        # ISS-032: the TR-21 core is evaluated in binary float (math.pow needs a
        # fractional power, which Decimal lacks natively) before re-Decimalizing.
        # The float error here is ~1e-12 relative — orders of magnitude below the
        # ledger's 1e-4 AF resolution — and the result is hard-capped at min(P, ET)
        # immediately below, so the float core can never move a billed figure at
        # ledger precision. The cap + sub-resolution error is the bound that makes
        # the float route safe; locked by test_usda_scs_stable_at_ledger_resolution.
        pe = sf * (1.25 * p_pow - 2.93) * math.pow(10, 0.000955 * etf)
        pe_d = _dec(pe)
        # Cap at both rainfall and ET, then floor at zero.
        capped = min(pe_d, p, et)
        return capped if capped > 0 else Decimal("0")

    raise ValueError(
        f"unknown effective-precip method {method!r}; "
        "expected 'raw', 'fraction', or 'usda_scs'"
    )
