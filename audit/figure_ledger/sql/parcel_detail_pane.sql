-- FIG-parcels-001 .. FIG-parcels-020: the parcel detail pane, all 20 figures.
--
-- Screens: /parcels/32/  (MER-APN-032, Ashvale Orchards Inc., the DISAGREEING
--                         pinned instance, where the pane's two balances differ)
--          /parcels/17/  (MER-APN-017, Saddlebow Ag Holdings, the AGREEING
--                         pinned instance, where they are the same number)
--
-- THE PANE HAS NO PERIOD CONTROL. parcels/views.py:181 builds the pane's context
-- from the parcel alone and never reads the request, so `?period=1` and
-- `?period=2` change nothing on this screen. That was OBSERVED, not inferred:
-- three captures of /parcels/32/ (bare, ?period=1, ?period=2) differ only in the
-- per-request cross-site token. The period each pane shows is therefore the one
-- parcels/views.py:118-127 resolves, transcribed as `resolved_period` below.
-- Both pinned parcels resolve to WY 2025-2026 (period id 2), the dry year.
--
-- INDEPENDENCE. This file references tables and columns only. It does not
-- import, call, or shell into any project module, and it runs on the host
-- through audit/figure_ledger/run_sql.sh, outside the process that owns the
-- object-relational mapper. Selection rules the application owns are transcribed
-- as literals with the source line beside them.
--
-- INDEPENDENCE CLASS, stated per row in the ledger's Notes column:
--   * RESTATEMENT: the supply, consumptive-use and mass-balance terms re-derive
--     the same chain the two services perform, starting from the stored rows.
--     This catches a coding mistake; it cannot catch a wrong idea about what a
--     figure should mean.
--   * DIFFERENT IDENTITY: the CHK- rows at the end start somewhere the pane does
--     not. CHK-parcels-051 in particular asserts an algebraic relation between
--     the pane's two balances that neither service computes.
--
-- Selection rules transcribed from source, read 2026-09-05:
--   parcels/views.py:118-127   the pane's period: the most recent reporting
--       period (by start_date) carrying a non-'allocation' ledger row for THIS
--       parcel; falling back to the most recent period overall when it has none.
--   accounting/services.py:377 billable_ledger. An `et_estimate` row is
--       suppressed where a `calculated` row exists for the same
--       (parcel, effective_date), or a `meter_reading` row exists for the same
--       (parcel, first-of-that-month). Stated below as its own predicate. On this
--       data it is inert: there are zero `et_estimate` rows (CHK-parcels-060).
--   accounting/services.py:472 _balance_dict. "usage" is the ABSOLUTE VALUE OF
--       THE SUM of negative amounts excluding surface_diversion. Not the sum of
--       absolute values: a positive row inside that set would offset, and the two
--       differ. Transcribed as written. This is the pane's Groundwater figure and
--       the mass balance's "Groundwater pumped": one quantity, printed twice.
--   accounting/services.py:747 surface supply is abs(SUM(amount)) over billable
--       rows in the mass balance (accounting/services.py:869 in the consumptive-use
--       read, the same rule written twice).
--       Stored negative by production convention; a canal delivery is a supply to
--       the parcel, so its magnitude counts.
--   accounting/services.py:617 runs_in_period. A CalculationRun belongs to a
--       period when period_start falls between the FIRST OF THE PERIOD'S OPENING
--       MONTH and the period's end date. A whole month that merely overlaps is
--       included; monthly runs are not pro-rated.
--   accounting/services.py:600 and 765 _incidental_recharge_af. The Recharge output is
--       read off each run's stored breakdown: the FIRST step whose step_type is
--       'clamp_floor', field detail.incidental_recharge_af, defaulting to 0 when
--       no such step ran.
--   accounting/services.py:767 runoff is the literal Decimal("0"), a named
--       bookkeeping term under the platform's "no surface hydrology" boundary,
--       not a measurement. Written here as the same literal 0.
--   accounting/services.py:762 delta_storage is SUM(banked_af - drawn_af).
--   accounting/services.py:571 MASS_BALANCE_TOLERANCE = 0.01 AF, the band inside
--       which the residual is called "Balanced".
--   accounting/services.py:580 REALISTIC_RESIDUAL_BAND = 0.25. A residual within
--       this fraction of gross ET is presented as normal rather than flagged.
--   parcels/views.py:107-109   Recent ledger entries are the parcel's rows
--       ordered by effective_date descending then created_at descending, first
--       ten. FIG-parcels-020 is the first of those.
--   parcels/views.py:151-160   the editable-field list. Only "area_acres" has
--       type "number", so it is the only one the pane sends through the
--       two-decimal display filter: FIG-parcels-018.

\set ON_ERROR_STOP on

WITH periods AS (
    SELECT id, start_date, end_date,
           date_trunc('month', start_date)::date AS first_month
      FROM accounting_reportingperiod
),
latest_period AS (
    SELECT id FROM accounting_reportingperiod ORDER BY start_date DESC LIMIT 1
),

-- parcels/views.py:118-127, transcribed. One row per parcel: the period its pane
-- actually shows.
resolved_period AS (
    SELECT p.id AS parcel_id,
           COALESCE(
             (SELECT pl.reporting_period_id
                FROM parcels_parcelledger pl
                JOIN accounting_reportingperiod rp ON rp.id = pl.reporting_period_id
               WHERE pl.parcel_id = p.id
                 AND pl.reporting_period_id IS NOT NULL
                 AND pl.source_type <> 'allocation'
               ORDER BY rp.start_date DESC
               LIMIT 1),
             (SELECT id FROM latest_period)
           ) AS period_id
      FROM parcels_parcel p
),

-- Every ledger row in scope, one (parcel, period) pair at a time, before the
-- authority ladder is applied.
ledger AS (
    SELECT pl.parcel_id, pl.reporting_period_id AS period_id, pl.effective_date,
           pl.source_type, pl.amount_acre_feet, pl.created_at
      FROM parcels_parcelledger pl
     WHERE pl.reporting_period_id IS NOT NULL
),
suppression AS (
    SELECT DISTINCT parcel_id, period_id, effective_date AS key_date
      FROM ledger WHERE source_type = 'calculated'
    UNION
    SELECT DISTINCT parcel_id, period_id,
           date_trunc('month', effective_date)::date
      FROM ledger WHERE source_type = 'meter_reading'
),
billable AS (
    SELECT l.*
      FROM ledger l
     WHERE NOT (
        l.source_type = 'et_estimate'
        AND EXISTS (SELECT 1 FROM suppression s
                     WHERE s.parcel_id = l.parcel_id
                       AND s.period_id = l.period_id
                       AND s.key_date = l.effective_date)
     )
),

-- Ledger-sourced terms, per (parcel, period). Every parcel crossed with every
-- period so a parcel with no rows in a period still produces a zero row rather
-- than vanishing.
led AS (
    SELECT p.id AS parcel_id, rp.id AS period_id,
           abs(COALESCE(SUM(b.amount_acre_feet)
               FILTER (WHERE b.source_type = 'surface_diversion'), 0)) AS surface,
           abs(COALESCE(SUM(b.amount_acre_feet)
               FILTER (WHERE b.amount_acre_feet < 0
                         AND b.source_type <> 'surface_diversion'), 0)) AS groundwater
      FROM parcels_parcel p
     CROSS JOIN periods rp
      LEFT JOIN billable b ON b.parcel_id = p.id AND b.period_id = rp.id
     GROUP BY 1, 2
),

-- CalculationRun-sourced terms, per (parcel, period).
runs AS (
    SELECT p.id AS parcel_id, rp.id AS period_id,
           COALESCE(SUM(cr.gross_et_af), 0)              AS et,
           COALESCE(SUM(cr.net_consumptive_use_af), 0)   AS net_cu,
           COALESCE(SUM(cr.effective_precip_af), 0)      AS precip,
           COALESCE(SUM(cr.banked_af - cr.drawn_af), 0)  AS delta_storage,
           COALESCE(SUM(
             (SELECT (step->'detail'->>'incidental_recharge_af')::numeric
                FROM jsonb_array_elements(cr.breakdown) step
               WHERE step->>'step_type' = 'clamp_floor'
               LIMIT 1)), 0)                             AS recharge,
           COUNT(cr.id)                                  AS run_count
      FROM parcels_parcel p
     CROSS JOIN periods rp
      LEFT JOIN accounting_calculationrun cr
             ON cr.parcel_id = p.id
            AND cr.period_start >= rp.first_month
            AND cr.period_start <= rp.end_date
     GROUP BY 1, 2
),

-- The two balances the pane prints, side by side.
balance AS (
    SELECT l.parcel_id, l.period_id,
           l.surface, l.groundwater, r.precip, r.et, r.net_cu,
           r.recharge, r.delta_storage, r.run_count,
           0::numeric AS runoff,
           l.surface + l.groundwater + r.precip                       AS supply_total,
           l.surface + l.groundwater + r.precip - r.et                AS net_vs_supply,
           (l.surface + r.precip + l.groundwater)
             - (r.et + r.recharge + 0 + r.delta_storage)              AS residual
      FROM led l
      JOIN runs r ON r.parcel_id = l.parcel_id AND r.period_id = l.period_id
),

-- The two pinned parcels, each at the period its own pane resolves to.
pinned AS (
    SELECT pa.parcel_number, b.*
      FROM balance b
      JOIN resolved_period rs ON rs.parcel_id = b.parcel_id
                             AND rs.period_id = b.period_id
      JOIN parcels_parcel pa ON pa.id = b.parcel_id
     WHERE b.parcel_id IN (17, 32)
),

-- FIG-parcels-018: the one editable field rendered as a number.
area AS (
    SELECT id AS parcel_id, area_acres FROM parcels_parcel WHERE id IN (17, 32)
),
-- FIG-parcels-019: the first well share in the Related wells card.
well_share AS (
    SELECT DISTINCT ON (wip.parcel_id)
           wip.parcel_id, wip.fraction
      FROM wells_wellirrigatedparcel wip
     WHERE wip.parcel_id IN (17, 32)
     ORDER BY wip.parcel_id, wip.id
),
-- FIG-parcels-020: the first of the ten most recent ledger rows.
recent_row AS (
    SELECT DISTINCT ON (pl.parcel_id)
           pl.parcel_id, pl.amount_acre_feet
      FROM parcels_parcelledger pl
     WHERE pl.parcel_id IN (17, 32)
     ORDER BY pl.parcel_id, pl.effective_date DESC, pl.created_at DESC
),

-- ── The 20 figures, for each pinned parcel ──────────────────────────────────
figures AS (
    SELECT 'FIG-parcels-001' AS id, p.parcel_number AS pin,
           'Consumptive use (ET)' AS label, round(p.et, 2) AS recomputed FROM pinned p
    UNION ALL SELECT 'FIG-parcels-002', p.parcel_number, 'Total supplies',
           round(p.supply_total, 2) FROM pinned p
    UNION ALL SELECT 'FIG-parcels-003', p.parcel_number, 'Supplies minus consumptive use',
           round(p.net_vs_supply, 2) FROM pinned p
    UNION ALL SELECT 'FIG-parcels-004', p.parcel_number, 'Net consumptive demand',
           round(p.net_cu, 2) FROM pinned p
    UNION ALL SELECT 'FIG-parcels-005', p.parcel_number, 'Surface water (supply split)',
           round(p.surface, 2) FROM pinned p
    UNION ALL SELECT 'FIG-parcels-006', p.parcel_number, 'Groundwater (supply split)',
           round(p.groundwater, 2) FROM pinned p
    UNION ALL SELECT 'FIG-parcels-007', p.parcel_number, 'Precipitation (supply split)',
           round(p.precip, 2) FROM pinned p

    UNION ALL SELECT 'FIG-parcels-008', p.parcel_number, 'Summary table: Surface',
           round(p.surface, 2) FROM pinned p
    UNION ALL SELECT 'FIG-parcels-009', p.parcel_number, 'Summary table: ET',
           round(p.et, 2) FROM pinned p
    UNION ALL SELECT 'FIG-parcels-010', p.parcel_number, 'Summary table: Precip',
           round(p.precip, 2) FROM pinned p
    UNION ALL SELECT 'FIG-parcels-011', p.parcel_number, 'Summary table: Recharge',
           round(p.recharge, 2) FROM pinned p
    UNION ALL SELECT 'FIG-parcels-012', p.parcel_number, 'Summary table: Groundwater pumped',
           round(p.groundwater, 2) FROM pinned p
    UNION ALL SELECT 'FIG-parcels-013', p.parcel_number, 'Summary table: Runoff',
           round(p.runoff, 2) FROM pinned p
    UNION ALL SELECT 'FIG-parcels-014', p.parcel_number, 'Summary table: Net Banked/Drawn',
           round(p.delta_storage, 2) FROM pinned p
    UNION ALL SELECT 'FIG-parcels-015', p.parcel_number, 'Residual',
           round(p.residual, 2) FROM pinned p

    -- FIG-parcels-016 and -017 live in the pane's "ET has not been computed"
    -- branch (_detail_pane.html:178-179). It renders only when the parcel has NO
    -- calculation runs in the resolved period. Both pinned parcels have runs, and
    -- so does every other parcel (CHK-parcels-070/071), so the branch never
    -- renders and there is no rendered value to check a recomputation against.
    -- The supply figures it WOULD print are recomputed here anyway, so the day
    -- the branch becomes reachable the number is already on file.
    UNION ALL SELECT 'FIG-parcels-016', p.parcel_number,
           'ET-not-computed branch: surface (branch not rendered)',
           round(p.surface, 2) FROM pinned p
    UNION ALL SELECT 'FIG-parcels-017', p.parcel_number,
           'ET-not-computed branch: groundwater (branch not rendered)',
           round(p.groundwater, 2) FROM pinned p

    UNION ALL SELECT 'FIG-parcels-018', pa.parcel_number, 'Area (Acres)',
           round(a.area_acres, 2)
      FROM area a JOIN parcels_parcel pa ON pa.id = a.parcel_id
    UNION ALL SELECT 'FIG-parcels-019', pa.parcel_number, 'Well share (fraction)',
           round(w.fraction, 2)
      FROM well_share w JOIN parcels_parcel pa ON pa.id = w.parcel_id
    UNION ALL SELECT 'FIG-parcels-020', pa.parcel_number,
           'Recent ledger entries: first Amount (AF)',
           round(rr.amount_acre_feet, 2)
      FROM recent_row rr JOIN parcels_parcel pa ON pa.id = rr.parcel_id
),

-- ── Whole-column checks, both periods, all 76 parcels ───────────────────────
-- Every count below is named with the period it was measured over. The plan text
-- this section inherited carried "32 of 76" with no period attached, and that is
-- how the wetter year's figure came to be read as the whole truth.
column_checks AS (
    SELECT 'CHK-parcels-030' AS id,
           'WY 2024-2025 (period 1): parcels where the card and the residual disagree on sign, i.e. (card >= 0) is not (residual >= 0)' AS label,
           count(*) FILTER (WHERE (net_vs_supply >= 0) <> (residual >= 0))::numeric AS recomputed
      FROM balance WHERE period_id = 1
    UNION ALL
    SELECT 'CHK-parcels-031',
           'WY 2025-2026 (period 2): parcels where the card and the residual disagree on sign',
           count(*) FILTER (WHERE (net_vs_supply >= 0) <> (residual >= 0))::numeric
      FROM balance WHERE period_id = 2
    UNION ALL
    SELECT 'CHK-parcels-032',
           'WY 2024-2025 (period 1): of those, how many are card-says-surplus while residual is negative',
           count(*) FILTER (WHERE net_vs_supply >= 0 AND residual < 0)::numeric
      FROM balance WHERE period_id = 1
    UNION ALL
    SELECT 'CHK-parcels-033',
           'WY 2025-2026 (period 2): of those, how many are card-says-surplus while residual is negative',
           count(*) FILTER (WHERE net_vs_supply >= 0 AND residual < 0)::numeric
      FROM balance WHERE period_id = 2
    UNION ALL
    SELECT 'CHK-parcels-034',
           'WY 2024-2025 (period 1): parcels where the two PRINTED numbers differ at two decimal places',
           count(*) FILTER (WHERE round(net_vs_supply, 2) <> round(residual, 2))::numeric
      FROM balance WHERE period_id = 1
    UNION ALL
    SELECT 'CHK-parcels-035',
           'WY 2025-2026 (period 2): parcels where the two PRINTED numbers differ at two decimal places',
           count(*) FILTER (WHERE round(net_vs_supply, 2) <> round(residual, 2))::numeric
      FROM balance WHERE period_id = 2
    UNION ALL
    SELECT 'CHK-parcels-036',
           'WY 2024-2025 (period 1): parcels printing a non-zero card beside a residual that prints 0.00',
           count(*) FILTER (WHERE round(net_vs_supply, 2) <> 0
                              AND round(residual, 2) = 0)::numeric
      FROM balance WHERE period_id = 1
    UNION ALL
    SELECT 'CHK-parcels-037',
           'WY 2025-2026 (period 2): parcels printing a non-zero card beside a residual that prints 0.00',
           count(*) FILTER (WHERE round(net_vs_supply, 2) <> 0
                              AND round(residual, 2) = 0)::numeric
      FROM balance WHERE period_id = 2
    UNION ALL
    SELECT 'CHK-parcels-040',
           'WY 2024-2025 (period 1): parcels whose residual falls inside the 0.01 AF Balanced band',
           count(*) FILTER (WHERE abs(residual) <= 0.01)::numeric
      FROM balance WHERE period_id = 1
    UNION ALL
    SELECT 'CHK-parcels-041',
           'WY 2025-2026 (period 2): parcels whose residual falls inside the 0.01 AF Balanced band',
           count(*) FILTER (WHERE abs(residual) <= 0.01)::numeric
      FROM balance WHERE period_id = 2
    UNION ALL
    SELECT 'CHK-parcels-042',
           'WY 2024-2025 (period 1): of the sign-disagreeing parcels, how many nevertheless show the grey Balanced badge (residual inside 0.01 AF)',
           count(*) FILTER (WHERE (net_vs_supply >= 0) <> (residual >= 0)
                              AND abs(residual) <= 0.01)::numeric
      FROM balance WHERE period_id = 1
    UNION ALL
    SELECT 'CHK-parcels-043',
           'WY 2025-2026 (period 2): of the sign-disagreeing parcels, how many nevertheless show the grey Balanced badge',
           count(*) FILTER (WHERE (net_vs_supply >= 0) <> (residual >= 0)
                              AND abs(residual) <= 0.01)::numeric
      FROM balance WHERE period_id = 2
    UNION ALL
    SELECT 'CHK-parcels-044',
           'WY 2025-2026 (period 2): the largest Supplies-minus-consumptive-use figure printed on a pane whose badge reads Balanced',
           round(COALESCE(max(net_vs_supply) FILTER (WHERE abs(residual) <= 0.01), 0), 2)
      FROM balance WHERE period_id = 2
    UNION ALL
    SELECT 'CHK-parcels-045',
           'WY 2024-2025 (period 1): the largest Supplies-minus-consumptive-use figure printed on a pane whose badge reads Balanced',
           round(COALESCE(max(net_vs_supply) FILTER (WHERE abs(residual) <= 0.01), 0), 2)
      FROM balance WHERE period_id = 1
    UNION ALL
    -- DIFFERENT IDENTITY. Neither service computes this relation; it falls out of
    -- the two definitions and says exactly what the gap between the pane's two
    -- balances is made of. A non-zero count would mean one of the two chains was
    -- transcribed wrongly above.
    SELECT 'CHK-parcels-051',
           'Both periods, all 152 parcel-periods: violations of residual = card - recharge - net banked/drawn',
           count(*) FILTER (WHERE round(residual, 6)
                                <> round(net_vs_supply - recharge - delta_storage, 6))::numeric
      FROM balance
    UNION ALL
    SELECT 'CHK-parcels-052',
           'Both periods: parcel-periods where the whole gap between the two balances is the recharge term alone',
           count(*) FILTER (WHERE recharge <> 0 AND delta_storage = 0)::numeric
      FROM balance
    UNION ALL
    SELECT 'CHK-parcels-053',
           'Both periods: parcel-periods where the Net Banked/Drawn term is non-zero, i.e. banked credit contributes to the gap at all',
           count(*) FILTER (WHERE delta_storage <> 0)::numeric
      FROM balance
    UNION ALL
    SELECT 'CHK-parcels-054',
           'Both periods: parcel-periods where the Recharge term is non-zero',
           count(*) FILTER (WHERE recharge <> 0)::numeric
      FROM balance
    UNION ALL
    SELECT 'CHK-parcels-060',
           'et_estimate ledger rows in the whole database. The suppression rule above is inert while this is 0',
           count(*)::numeric
      FROM parcels_parcelledger WHERE source_type = 'et_estimate'
    UNION ALL
    SELECT 'CHK-parcels-070',
           'WY 2024-2025 (period 1): parcels with NO calculation runs, which is what would render the ET-not-computed branch',
           count(*) FILTER (WHERE run_count = 0)::numeric
      FROM balance WHERE period_id = 1
    UNION ALL
    SELECT 'CHK-parcels-071',
           'WY 2025-2026 (period 2): parcels with NO calculation runs',
           count(*) FILTER (WHERE run_count = 0)::numeric
      FROM balance WHERE period_id = 2
    UNION ALL
    SELECT 'CHK-parcels-080',
           'Parcels whose pane resolves to WY 2024-2025 (period 1)',
           count(*) FILTER (WHERE period_id = 1)::numeric FROM resolved_period
    UNION ALL
    SELECT 'CHK-parcels-081',
           'Parcels whose pane resolves to WY 2025-2026 (period 2)',
           count(*) FILTER (WHERE period_id = 2)::numeric FROM resolved_period
    UNION ALL
    SELECT 'CHK-parcels-090',
           'Total parcels',
           count(*)::numeric FROM parcels_parcel
)

SELECT id, pin, label, recomputed FROM figures
UNION ALL
SELECT id, '(all 76 parcels)', label, recomputed FROM column_checks
ORDER BY 1, 2;
