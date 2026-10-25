# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Accounting views.

The dashboards and balance surfaces of the platform: estimated consumptive use
(ET) against the reconciled supplies, the raw ledger rows behind them, and the
administrator pages that tune the calculation engine. One module per screen:

- dashboard: the accounting dashboard.
- periods: reporting periods, their calculation and finalizing.
- allocations: allocation plans.
- accounts: water accounts and the parcels assigned to them.
- ledger: the parcel ledger, its CSV upload, template and export.
- calculation_runs: the "How was this calculated?" page for one parcel.
- settings_pages: delivery settings and the methodology steps.
- common: the one helper the dashboard and the account list share.
"""
