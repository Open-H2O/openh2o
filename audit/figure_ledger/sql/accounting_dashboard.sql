-- FIG-accounting-023..045 — the accounting dashboard, all 23 rendered figures.
--
-- Screen: /accounting/dashboard/?period=2  (WY 2025-2026, the dry year; the same
-- page the bare /accounting/dashboard/ URL resolves to on this data — observed,
-- not inferred: the two captures differ only in their cross-site request token).
-- Pinned account row: MER-ACCT-001 Ashvale Orchards Inc. (id 12, first row).
-- IDS ARE THE CANDIDATE'S (136-02, 2026-09-06): the ledger re-measure runs on the
-- restored candidate.dump, whose keys are a clean sequence and are what the
-- golden and therefore production will carry; the development database this was
-- first written against had gaps (this account was id 78 there).
-- Pinned zone row:    Halvern Irrigation-Urban GSA (id 2, first row, 23 parcels).
--
-- INDEPENDENCE. This file references tables and columns only. It does not
-- import, call, or shell into any project module, and it runs on the host
-- through audit/figure_ledger/run_sql.sh, outside the process that owns the
-- object-relational mapper. Constants and selection rules that the application
-- owns are transcribed as literals with the source line beside them.
--
-- INDEPENDENCE CLASS, stated honestly per row in the ledger's Notes column:
--   * RESTATEMENT — the supply, consumptive-use and net figures re-derive the
--     same chain the service performs, starting from the stored rows. This can
--     catch a coding mistake; it cannot catch a wrong idea about what the figure
--     should mean.
--   * DIFFERENT IDENTITY — the two cross-checks at the end of this file
--     (single_pass_grand_total, balance_identity) start somewhere the view does
--     not and CAN disagree with it.
--
-- Selection rules transcribed from source, read 2026-09-05:
--   accounting/services.py:377  billable_ledger — an `et_estimate` row is
--       suppressed where a `calculated` row exists for the same
--       (parcel, effective_date), or a `meter_reading` row exists for the same
--       (parcel, first-of-that-month). Stated below as its own predicate.
--   accounting/services.py:472  _balance_dict — "usage" is the ABSOLUTE VALUE OF
--       THE SUM of negative amounts excluding surface_diversion. Not the sum of
--       absolute values: a positive row inside that set would offset, and the
--       two differ. Transcribed as written.
--   accounting/services.py:864  surface supply is abs(SUM(amount)) over billable
--       surface_diversion rows. Stored negative by production convention; a
--       canal delivery is a supply to the parcel, so its magnitude counts.
--   accounting/services.py:617  runs_in_period — a CalculationRun belongs to a
--       period when period_start falls between the FIRST OF THE PERIOD'S OPENING
--       MONTH and the period's end date. A whole month that merely overlaps is
--       included; monthly runs are not pro-rated.
--   accounting/services.py:912  an account's parcels are its assignments with
--       removed_date IS NULL.
--   accounting/services.py:926  a zone's parcels are its ParcelZone rows.
--   accounting/views.py:135     the grand totals roll up ACTIVE accounts only.
--
-- BUDGET BASIS AFTER 136-01 (read 2026-09-06; ISS-151, option A, Brent 2026-09-05):
--   accounting/views.py         the account allocation is pro-rated by PARCEL
--       COUNT within each zone, over GROUNDWATER plans only: a plan counts when
--       its accounting_watertype.code is 'GW' (matched case-insensitively, as the
--       view does). Σ_zones zone_gw_allocation × (this account's rows in that
--       zone ÷ all rows in that zone). Still arithmetic in the view, not in any
--       service.
--   accounting/views.py         remaining = allocation − groundwater use, where
--       groundwater use is the same "usage" magnitude the Groundwater column
--       shows (negative non-surface_diversion billable rows).
--   accounting/views.py         zone_allocation sums GW plans only; a zone with
--       none renders a dash in all three budget cells. zone_remaining =
--       available_with_carryover(zone_allocation, carry-over) − groundwater use.
--
-- BEFORE 136-01 (the basis this file recomputed on 2026-09-05, kept for the
-- record; the ledger's before-picture rows were measured on it):
--   accounting/views.py:140-166 the account allocation summed EVERY plan in every
--       zone the account touched, whatever its water type, so MER-ACCT-001 read
--       2,901.42 AF of groundwater allocation plus 16,200.00 AF of surface
--       entitlement as one 19,101.42 AF figure.
--   accounting/views.py:171     remaining = allocation − consumptive_use_gross.
--   accounting/views.py:223     zone_remaining = zone_available − gross.
--   accounting/carryover_math.py:51  water_year_of — a water year is named by the
--       calendar year it ENDS in; months >= 10 belong to the next year's label.
--   accounting/carryover_math.py:96  available_with_carryover with the view's
--       arguments (no depreciation rate, no periods elapsed) is allocation +
--       signed carry-over, quantized to four decimal places.

\set ON_ERROR_STOP on

WITH pin AS (
    SELECT 2::bigint AS period_id, 12::bigint AS account_id, 2::bigint AS zone_id
),
period AS (
    SELECT rp.id,
           rp.start_date,
           rp.end_date,
           date_trunc('month', rp.start_date)::date AS first_month,
           -- water_year_of, transcribed: named by the year it ends in.
           (CASE WHEN EXTRACT(MONTH FROM rp.end_date) >= 10
                 THEN EXTRACT(YEAR FROM rp.end_date) + 1
                 ELSE EXTRACT(YEAR FROM rp.end_date) END)::int AS water_year
      FROM accounting_reportingperiod rp
      JOIN pin ON rp.id = pin.period_id
),

-- Which parcels each figure's row is about. UNION (not UNION ALL) so a parcel
-- assigned twice counts once, matching an `id IN (...)` lookup.
membership AS (
    SELECT 'account'::text AS set_kind, wa.id AS set_id, wap.parcel_id
      FROM accounting_wateraccount wa
      JOIN accounting_wateraccountparcel wap ON wap.water_account_id = wa.id
     WHERE wa.status = 'active'
       AND wap.removed_date IS NULL
    UNION
    SELECT 'zone'::text, pz.zone_id, pz.parcel_id
      FROM geography_parcelzone pz
),
sets AS (
    SELECT 'account'::text AS set_kind, id AS set_id FROM accounting_wateraccount
     WHERE status = 'active'
    UNION ALL
    SELECT 'zone'::text, id FROM geography_zone
),

-- Every ledger row in scope, before the authority ladder is applied.
ledger AS (
    SELECT m.set_kind, m.set_id, pl.parcel_id, pl.effective_date,
           pl.source_type, pl.amount_acre_feet
      FROM membership m
      JOIN parcels_parcelledger pl ON pl.parcel_id = m.parcel_id
      JOIN period p ON pl.reporting_period_id = p.id
),
-- The suppression keys, scoped to the same rows the service scopes them to.
suppression AS (
    SELECT DISTINCT set_kind, set_id, parcel_id, effective_date AS key_date
      FROM ledger WHERE source_type = 'calculated'
    UNION
    SELECT DISTINCT set_kind, set_id, parcel_id,
           date_trunc('month', effective_date)::date
      FROM ledger WHERE source_type = 'meter_reading'
),
billable AS (
    SELECT l.*
      FROM ledger l
     WHERE NOT (
        l.source_type = 'et_estimate'
        AND EXISTS (SELECT 1 FROM suppression s
                     WHERE s.set_kind = l.set_kind
                       AND s.set_id = l.set_id
                       AND s.parcel_id = l.parcel_id
                       AND s.key_date = l.effective_date)
     )
),
supplies AS (
    SELECT set_kind, set_id,
           abs(COALESCE(SUM(amount_acre_feet)
               FILTER (WHERE source_type = 'surface_diversion'), 0)) AS surface,
           abs(COALESCE(SUM(amount_acre_feet)
               FILTER (WHERE amount_acre_feet < 0
                         AND source_type <> 'surface_diversion'), 0)) AS groundwater
      FROM billable
     GROUP BY set_kind, set_id
),
runs AS (
    SELECT m.set_kind, m.set_id,
           COALESCE(SUM(cr.gross_et_af), 0) AS gross,
           COALESCE(SUM(cr.net_consumptive_use_af), 0) AS net_cu,
           COALESCE(SUM(cr.effective_precip_af), 0) AS precip,
           COUNT(cr.id) AS run_count
      FROM membership m
      JOIN accounting_calculationrun cr ON cr.parcel_id = m.parcel_id
      JOIN period p ON cr.period_start >= p.first_month
                   AND cr.period_start <= p.end_date
     GROUP BY m.set_kind, m.set_id
),
balance AS (
    SELECT s.set_kind, s.set_id,
           COALESCE(sup.surface, 0)     AS surface,
           COALESCE(sup.groundwater, 0) AS groundwater,
           COALESCE(r.precip, 0)        AS precip,
           COALESCE(sup.surface, 0) + COALESCE(sup.groundwater, 0)
             + COALESCE(r.precip, 0)    AS supply_total,
           COALESCE(r.gross, 0)         AS gross,
           COALESCE(r.net_cu, 0)        AS net_cu,
           COALESCE(r.run_count, 0)     AS run_count,
           COALESCE(sup.surface, 0) + COALESCE(sup.groundwater, 0)
             + COALESCE(r.precip, 0) - COALESCE(r.gross, 0) AS net_vs_supply
      FROM sets s
      LEFT JOIN supplies sup ON sup.set_kind = s.set_kind AND sup.set_id = s.set_id
      LEFT JOIN runs r       ON r.set_kind  = s.set_kind AND r.set_id  = s.set_id
),

-- The account allocation, pro-rated by parcel-row count within each zone.
-- GROUNDWATER plans only (136-01): the join on accounting_watertype is the
-- like-with-like rule, and a zone with no GW plan has NO row here, which is
-- what makes the zone table's dash below an absence rather than a zero.
zone_period_alloc AS (
    SELECT ap.zone_id, SUM(ap.allocation_acre_feet) AS zone_alloc
      FROM accounting_allocationplan ap
      JOIN period p ON ap.reporting_period_id = p.id
      JOIN accounting_watertype wt ON wt.id = ap.water_type_id
                                  AND upper(wt.code) = 'GW'
     GROUP BY ap.zone_id
),
zone_row_counts AS (
    SELECT zone_id, COUNT(*) AS total_rows
      FROM geography_parcelzone
     GROUP BY zone_id
),
account_zone_rows AS (
    SELECT m.set_id AS account_id, pz.zone_id, COUNT(*) AS account_rows
      FROM membership m
      JOIN geography_parcelzone pz ON pz.parcel_id = m.parcel_id
     WHERE m.set_kind = 'account'
     GROUP BY m.set_id, pz.zone_id
),
account_allocation AS (
    SELECT azr.account_id,
           COALESCE(SUM(COALESCE(zpa.zone_alloc, 0)
                        * azr.account_rows::numeric
                        / NULLIF(zrc.total_rows, 0)::numeric), 0) AS allocation
      FROM account_zone_rows azr
      JOIN zone_row_counts zrc ON zrc.zone_id = azr.zone_id
      LEFT JOIN zone_period_alloc zpa ON zpa.zone_id = azr.zone_id
     GROUP BY azr.account_id
),
zone_budget AS (
    -- zpa.zone_alloc is NULL for a zone with no groundwater plan; the view
    -- renders that as a dash, and this recomputation carries the NULL through
    -- rather than coercing it to 0.
    SELECT z.id AS zone_id,
           zpa.zone_alloc AS allocation,
           COALESCE((SELECT SUM(ac.amount_af)
                       FROM accounting_allocationcarryover ac
                       JOIN period p ON ac.water_year = p.water_year
                      WHERE ac.zone_id = z.id), 0) AS carryover
      FROM geography_zone z
      LEFT JOIN zone_period_alloc zpa ON zpa.zone_id = z.id
),

-- The account row and the zone row the ledger pins.
pinned_account AS (
    SELECT b.*, round(aa.allocation, 4) AS allocation,
           -- 136-01: minus groundwater use, not gross ET.
           round(aa.allocation, 4) - b.groundwater AS remaining
      FROM balance b
      JOIN pin ON b.set_id = pin.account_id
      LEFT JOIN account_allocation aa ON aa.account_id = b.set_id
     WHERE b.set_kind = 'account'
),
pinned_zone AS (
    SELECT b.*, zb.allocation, zb.carryover,
           round(zb.allocation + zb.carryover, 4) AS available,
           -- 136-01: minus groundwater use, not gross ET.
           round(zb.allocation + zb.carryover, 4) - b.groundwater AS remaining
      FROM balance b
      JOIN pin ON b.set_id = pin.zone_id
      JOIN zone_budget zb ON zb.zone_id = b.set_id
     WHERE b.set_kind = 'zone'
),
-- The grand totals: summed ACROSS ACTIVE ACCOUNTS, the way the view accumulates
-- them one account at a time.
grand AS (
    SELECT SUM(supply_total) AS supply_total,
           SUM(gross)        AS consumptive_use,
           SUM(surface)      AS surface,
           SUM(groundwater)  AS groundwater,
           SUM(precip)       AS precip
      FROM balance WHERE set_kind = 'account'
),

-- ── The 23 figures ────────────────────────────────────────────────────────────
figures AS (
    SELECT 'FIG-accounting-023' AS id, 'Supplies (grand total)' AS label,
           round(supply_total, 2) AS recomputed FROM grand
    UNION ALL SELECT 'FIG-accounting-024', 'Consumptive use (grand total)',
           round(consumptive_use, 2) FROM grand
    UNION ALL SELECT 'FIG-accounting-025', 'Balance (grand total)',
           round(supply_total - consumptive_use, 2) FROM grand
    UNION ALL SELECT 'FIG-accounting-026', 'Surface (panel foot)',
           round(surface, 2) FROM grand
    UNION ALL SELECT 'FIG-accounting-027', 'Groundwater (panel foot)',
           round(groundwater, 2) FROM grand
    UNION ALL SELECT 'FIG-accounting-028', 'Rain (panel foot)',
           round(precip, 2) FROM grand

    UNION ALL SELECT 'FIG-accounting-029', 'Account MER-ACCT-001 Consumptive Use',
           round(gross, 2) FROM pinned_account
    UNION ALL SELECT 'FIG-accounting-030', 'Account MER-ACCT-001 Surface',
           round(surface, 2) FROM pinned_account
    UNION ALL SELECT 'FIG-accounting-031', 'Account MER-ACCT-001 Groundwater',
           round(groundwater, 2) FROM pinned_account
    UNION ALL SELECT 'FIG-accounting-032', 'Account MER-ACCT-001 Precip',
           round(precip, 2) FROM pinned_account
    UNION ALL SELECT 'FIG-accounting-033', 'Account MER-ACCT-001 Supplies',
           round(supply_total, 2) FROM pinned_account
    UNION ALL SELECT 'FIG-accounting-034', 'Account MER-ACCT-001 Net',
           round(net_vs_supply, 2) FROM pinned_account
    UNION ALL SELECT 'FIG-accounting-035', 'Account MER-ACCT-001 Allocation',
           round(allocation, 2) FROM pinned_account
    UNION ALL SELECT 'FIG-accounting-036', 'Account MER-ACCT-001 Remaining',
           round(remaining, 2) FROM pinned_account

    UNION ALL SELECT 'FIG-accounting-037', 'Zone Halvern Irrigation-Urban GSA Consumptive Use',
           round(gross, 2) FROM pinned_zone
    UNION ALL SELECT 'FIG-accounting-038', 'Zone Halvern Irrigation-Urban GSA Surface',
           round(surface, 2) FROM pinned_zone
    UNION ALL SELECT 'FIG-accounting-039', 'Zone Halvern Irrigation-Urban GSA Groundwater',
           round(groundwater, 2) FROM pinned_zone
    UNION ALL SELECT 'FIG-accounting-040', 'Zone Halvern Irrigation-Urban GSA Precip',
           round(precip, 2) FROM pinned_zone
    UNION ALL SELECT 'FIG-accounting-041', 'Zone Halvern Irrigation-Urban GSA Supplies',
           round(supply_total, 2) FROM pinned_zone
    UNION ALL SELECT 'FIG-accounting-042', 'Zone Halvern Irrigation-Urban GSA Net',
           round(net_vs_supply, 2) FROM pinned_zone
    UNION ALL SELECT 'FIG-accounting-043', 'Zone Halvern Irrigation-Urban GSA Allocation',
           round(allocation, 2) FROM pinned_zone
    UNION ALL SELECT 'FIG-accounting-044', 'Zone Halvern Irrigation-Urban GSA Carried fwd',
           round(carryover, 2) FROM pinned_zone
    UNION ALL SELECT 'FIG-accounting-045', 'Zone Halvern Irrigation-Urban GSA Remaining',
           round(remaining, 2) FROM pinned_zone
)
SELECT id, label, recomputed FROM figures ORDER BY id;
