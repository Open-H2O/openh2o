-- FIG-parcels-001 .. FIG-parcels-015: the parcel detail pane, its balance
-- panel and its unrelated attribute/ledger figures (137-01 basis).
--
-- Screens pinned: /parcels/11/?period=2  (MER-APN-011, the ISS-157 instance —
--                     a no-well field with recorded unmet demand, the DRY year)
--                 /parcels/11/?period=1  (the same field, the WET year, for
--                     the ISS-157 checkpoint's "line disappears" comparison)
--                 /parcels/32/?period=2  (MER-APN-032, the RECHARGE instance —
--                     the one parcel-year where the Uses foot's Recharge cell
--                     is non-zero, so a wrong subtraction there could fail)
--                 /parcels/17/?period=2  (MER-APN-017, the PLAIN instance —
--                     no recharge, no storage change; the panel's ordinary case)
--
-- 137-01 REWRITE. The pane used to show TWO balances (a "Supplies minus
-- consumptive use" card and a mass-balance residual, ISS-148) across 20 figure
-- sites: three stat cards, a "Net consumptive demand" sentence, three supply
-- composition cards, a seven-row supply-vs-use table, and a free-standing
-- residual row. 137-01 replaced all of that with ONE `.budget-panel` — three
-- segments (Supplies / Uses / Residual) and a two-line foot — plus the new
-- ISS-157 unmet-demand line. Figure ids were reassigned in template order by
-- `scripts/figure_inventory.py`; see `audit/figure_ledger/remap_ids.py`'s
-- output at 137-01's ledger commit for the full old-id -> new-id (or
-- "retired") table. THE SEGMENTS AND FOOT CELLS ARE NOT NEW ARITHMETIC: they
-- are `parcel_mass_balance`'s existing `inputs_total` / `outputs_total` /
-- `residual_af` / `inputs.*` / `outputs.*`, the same identity this file
-- already computed as `supply_total` / `net_vs_supply`'s complement /
-- `residual` / the per-term columns below. This file's `balance` CTE is
-- UNCHANGED from before 137-01; only the `figures` block that names which
-- column backs which FIG- id was re-pointed.
--
-- THE PANE NOW HAS A PERIOD CONTROL (ISS-147, 137-01 Task 3). Before 137-01,
-- parcels/views.py:181 built the pane's context from the parcel alone and
-- never read the request, so `?period=` changed nothing — observed by
-- diffing three captures of the same parcel byte-for-byte. It now reads
-- `?period=<pk>` on all three render paths, and its DEFAULT (no `?period=`)
-- changed too: from "the most recent period with a non-allocation ledger
-- row" to "the most recent period this parcel has a CalculationRun in",
-- falling back to the old heuristic and then to the most recent period
-- overall. `resolved_period` below transcribes the NEW four-step order.
-- Every FIGURE pin in this file is nonetheless read at an EXPLICIT period_id
-- literal, matching the `?period=` on its capture URL — never through
-- `resolved_period` — so a figure's value can never depend on getting the
-- default-resolution heuristic right. `resolved_period` exists only to back
-- the whole-column checks CHK-parcels-080/081/082, which are ABOUT the
-- default itself.
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
--     not.
--
-- Selection rules transcribed from source, read 2026-09-05, re-checked 2026-09-06:
--   parcels/views.py:139-171   the pane's period (137-01, ISS-147), FOUR steps
--       in order: (1) a valid `?period=` pk; (2) the most recent
--       ReportingPeriod for which `parcel_run_periods` returns a non-empty
--       list (i.e. the parcel has a CalculationRun in it); (3) the old
--       heuristic — most recent period with a non-'allocation' ledger row;
--       (4) the most recent period overall.
--   accounting/services.py:377 billable_ledger. An `et_estimate` row is
--       suppressed where a `calculated` row exists for the same
--       (parcel, effective_date), or a `meter_reading` row exists for the same
--       (parcel, first-of-that-month). Stated below as its own predicate. On this
--       data it is inert: there are zero `et_estimate` rows (CHK-parcels-060).
--   accounting/services.py:472 _balance_dict. "usage" is the ABSOLUTE VALUE OF
--       THE SUM of negative amounts excluding surface_diversion. Not the sum of
--       absolute values: a positive row inside that set would offset, and the two
--       differ. Transcribed as written. This is the pane's foot "Groundwater"
--       figure and the mass balance's `inputs.gw_recovered`: one quantity.
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
--       not a measurement. Written here as the same literal 0. DROPPED FROM THE
--       SCREEN by 137-01 (a cell that can only ever read 0.00 says nothing); the
--       key is kept in the dict and in this SQL for the CHK-parcels-051 identity
--       check.
--   accounting/services.py:762 delta_storage is SUM(banked_af - drawn_af).
--   accounting/services.py:571 MASS_BALANCE_TOLERANCE = 0.01 AF, the band inside
--       which the residual is called "Balanced".
--   accounting/services.py:580 REALISTIC_RESIDUAL_BAND = 0.25. A residual within
--       this fraction of gross ET is presented as normal rather than flagged.
--   parcels/views.py:107-109   Recent ledger entries are the parcel's rows
--       ordered by effective_date descending then created_at descending, first
--       ten. FIG-parcels-015 is the first of those.
--   parcels/views.py:151-160   the editable-field list. Only "area_acres" has
--       type "number", so it is the only one the pane sends through the
--       two-decimal display filter: FIG-parcels-013.

\set ON_ERROR_STOP on

WITH periods AS (
    SELECT id, start_date, end_date,
           date_trunc('month', start_date)::date AS first_month
      FROM accounting_reportingperiod
),
latest_period AS (
    SELECT id FROM accounting_reportingperiod ORDER BY start_date DESC LIMIT 1
),

-- parcels/views.py:139-171, transcribed (137-01, ISS-147). One row per
-- parcel: the period its pane resolves to with NO `?period=` given. Used only
-- by the whole-column checks below; every FIGURE pin in this file reads an
-- explicit period_id literal instead (see header).
resolved_period AS (
    SELECT p.id AS parcel_id,
           COALESCE(
             -- Step 2: the most recent period this parcel has a
             -- CalculationRun in at all (parcel_run_periods non-empty).
             (SELECT rp.id
                FROM periods rp
               WHERE EXISTS (
                       SELECT 1 FROM accounting_calculationrun cr
                        WHERE cr.parcel_id = p.id
                          AND cr.period_start >= rp.first_month
                          AND cr.period_start <= rp.end_date)
               ORDER BY rp.start_date DESC
               LIMIT 1),
             -- Step 3: the pre-137-01 heuristic, most recent period with a
             -- non-'allocation' ledger row for this parcel.
             (SELECT pl.reporting_period_id
                FROM parcels_parcelledger pl
                JOIN accounting_reportingperiod rp ON rp.id = pl.reporting_period_id
               WHERE pl.parcel_id = p.id
                 AND pl.reporting_period_id IS NOT NULL
                 AND pl.source_type <> 'allocation'
               ORDER BY rp.start_date DESC
               LIMIT 1),
             -- Step 4: most recent period overall.
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

-- The mass-balance identity, per (parcel, period). `supply_total` is the
-- panel's Supplies segment (`inputs_total`); `outputs_total` is the panel's
-- Uses segment; `residual` is the panel's Residual segment. Unchanged from
-- before 137-01 — only the names on the SCREEN moved.
balance AS (
    SELECT l.parcel_id, l.period_id,
           l.surface, l.groundwater, r.precip, r.et, r.net_cu,
           r.recharge, r.delta_storage, r.run_count,
           0::numeric AS runoff,
           l.surface + l.groundwater + r.precip                       AS supply_total,
           r.et + r.recharge + 0 + r.delta_storage                    AS outputs_total,
           (l.surface + r.precip + l.groundwater)
             - (r.et + r.recharge + 0 + r.delta_storage)              AS residual
      FROM led l
      JOIN runs r ON r.parcel_id = l.parcel_id AND r.period_id = l.period_id
),

-- The three pinned parcels, each at an EXPLICIT period literal matching its
-- capture URL's `?period=` — never through `resolved_period` (see header).
pinned AS (
    SELECT pa.parcel_number, b.*
      FROM balance b
      JOIN parcels_parcel pa ON pa.id = b.parcel_id
     WHERE (b.parcel_id, b.period_id) IN ((17, 2), (32, 2), (11, 2))
),
-- MER-APN-011, the WET year (period 1) — the ISS-157 checkpoint's second
-- instance, captured to observe the unmet-demand line disappear.
pinned_wet AS (
    SELECT pa.parcel_number, b.*
      FROM balance b
      JOIN parcels_parcel pa ON pa.id = b.parcel_id
     WHERE (b.parcel_id, b.period_id) IN ((11, 1))
),

-- FIG-parcels-013: the one editable field rendered as a number.
area AS (
    SELECT id AS parcel_id, area_acres FROM parcels_parcel WHERE id IN (11, 17, 32)
),
-- FIG-parcels-014: the first well share in the Related wells card.
well_share AS (
    SELECT DISTINCT ON (wip.parcel_id)
           wip.parcel_id, wip.fraction
      FROM wells_wellirrigatedparcel wip
     WHERE wip.parcel_id IN (11, 17, 32)
     ORDER BY wip.parcel_id, wip.id
),
-- FIG-parcels-015: the first of the ten most recent ledger rows.
recent_row AS (
    SELECT DISTINCT ON (pl.parcel_id)
           pl.parcel_id, pl.amount_acre_feet
      FROM parcels_parcelledger pl
     WHERE pl.parcel_id IN (11, 17, 32)
     ORDER BY pl.parcel_id, pl.effective_date DESC, pl.created_at DESC
),

-- ── The 15 figures, for each pinned parcel-period ───────────────────────────
figures AS (
    SELECT 'FIG-parcels-001' AS id, p.parcel_number || ' p' || p.period_id AS pin,
           'Supplies (segment)' AS label, round(p.supply_total, 2) AS recomputed
      FROM pinned p
    UNION ALL SELECT 'FIG-parcels-005', p.parcel_number || ' p' || p.period_id,
           'Uses (segment)', round(p.outputs_total, 2) FROM pinned p
    UNION ALL SELECT 'FIG-parcels-009', p.parcel_number || ' p' || p.period_id,
           'Residual (segment)', round(p.residual, 2) FROM pinned p
    UNION ALL SELECT 'FIG-parcels-002', p.parcel_number || ' p' || p.period_id,
           'Foot: Surface', round(p.surface, 2) FROM pinned p
    UNION ALL SELECT 'FIG-parcels-003', p.parcel_number || ' p' || p.period_id,
           'Foot: Groundwater', round(p.groundwater, 2) FROM pinned p
    UNION ALL SELECT 'FIG-parcels-004', p.parcel_number || ' p' || p.period_id,
           'Foot: Rain', round(p.precip, 2) FROM pinned p
    UNION ALL SELECT 'FIG-parcels-006', p.parcel_number || ' p' || p.period_id,
           'Foot: Consumptive use', round(p.et, 2) FROM pinned p
    UNION ALL SELECT 'FIG-parcels-007', p.parcel_number || ' p' || p.period_id,
           'Foot: Recharge', round(p.recharge, 2) FROM pinned p
    UNION ALL SELECT 'FIG-parcels-008', p.parcel_number || ' p' || p.period_id,
           'Foot: Storage change', round(p.delta_storage, 2) FROM pinned p

    -- Same nine, for the WET-year instance of MER-APN-011 (the ISS-157
    -- checkpoint's second capture). Same figure ids: a rendered value is
    -- matched to this row set by (pin, period) in the merge, not by id alone.
    UNION ALL SELECT 'FIG-parcels-001', p.parcel_number || ' p' || p.period_id,
           'Supplies (segment)', round(p.supply_total, 2) FROM pinned_wet p
    UNION ALL SELECT 'FIG-parcels-005', p.parcel_number || ' p' || p.period_id,
           'Uses (segment)', round(p.outputs_total, 2) FROM pinned_wet p
    UNION ALL SELECT 'FIG-parcels-009', p.parcel_number || ' p' || p.period_id,
           'Residual (segment)', round(p.residual, 2) FROM pinned_wet p
    UNION ALL SELECT 'FIG-parcels-002', p.parcel_number || ' p' || p.period_id,
           'Foot: Surface', round(p.surface, 2) FROM pinned_wet p
    UNION ALL SELECT 'FIG-parcels-003', p.parcel_number || ' p' || p.period_id,
           'Foot: Groundwater', round(p.groundwater, 2) FROM pinned_wet p
    UNION ALL SELECT 'FIG-parcels-004', p.parcel_number || ' p' || p.period_id,
           'Foot: Rain', round(p.precip, 2) FROM pinned_wet p
    UNION ALL SELECT 'FIG-parcels-006', p.parcel_number || ' p' || p.period_id,
           'Foot: Consumptive use', round(p.et, 2) FROM pinned_wet p
    UNION ALL SELECT 'FIG-parcels-007', p.parcel_number || ' p' || p.period_id,
           'Foot: Recharge', round(p.recharge, 2) FROM pinned_wet p
    UNION ALL SELECT 'FIG-parcels-008', p.parcel_number || ' p' || p.period_id,
           'Foot: Storage change', round(p.delta_storage, 2) FROM pinned_wet p

    -- FIG-parcels-011, -012 live in the pane's "ET has not been computed"
    -- branch. It renders only when the parcel has NO calculation runs in the
    -- resolved period. All three pinned parcels have runs, and so does every
    -- other parcel (CHK-parcels-070/071), so the branch never renders and
    -- there is no rendered value to check a recomputation against. The supply
    -- figures it WOULD print are recomputed here anyway (against MER-APN-032
    -- at p2), so the day the branch becomes reachable the number is on file.
    UNION ALL SELECT 'FIG-parcels-011', p.parcel_number || ' p' || p.period_id,
           'ET-not-computed branch: surface (branch not rendered)',
           round(p.surface, 2) FROM pinned p WHERE p.parcel_number = 'MER-APN-032'
    UNION ALL SELECT 'FIG-parcels-012', p.parcel_number || ' p' || p.period_id,
           'ET-not-computed branch: groundwater (branch not rendered)',
           round(p.groundwater, 2) FROM pinned p WHERE p.parcel_number = 'MER-APN-032'

    UNION ALL SELECT 'FIG-parcels-013', pa.parcel_number, 'Area (Acres)',
           round(a.area_acres, 2)
      FROM area a JOIN parcels_parcel pa ON pa.id = a.parcel_id
    UNION ALL SELECT 'FIG-parcels-014', pa.parcel_number, 'Well share (fraction)',
           round(w.fraction, 2)
      FROM well_share w JOIN parcels_parcel pa ON pa.id = w.parcel_id
    UNION ALL SELECT 'FIG-parcels-015', pa.parcel_number,
           'Recent ledger entries: first Amount (AF)',
           round(rr.amount_acre_feet, 2)
      FROM recent_row rr JOIN parcels_parcel pa ON pa.id = rr.parcel_id
),

-- ── Whole-column checks, both periods, all 76 parcels ───────────────────────
column_checks AS (
    -- DIFFERENT IDENTITY. Neither service prints both sides of this any more
    -- (card 3 is retired, 137-01), but the relation still holds inside
    -- `parcel_mass_balance` itself: residual = supply_total - outputs_total by
    -- construction. A non-zero count here means the two SQL expressions were
    -- transcribed inconsistently above, not a platform defect.
    SELECT 'CHK-parcels-051' AS id,
           'Both periods, all 152 parcel-periods: violations of residual = supply_total - outputs_total' AS label,
           count(*) FILTER (WHERE round(residual, 6)
                                <> round(supply_total - outputs_total, 6))::numeric AS recomputed
      FROM balance
    UNION ALL
    SELECT 'CHK-parcels-053',
           'Both periods: parcel-periods where the Net Banked/Drawn term is non-zero, i.e. banked credit contributes to the panel at all',
           count(*) FILTER (WHERE delta_storage <> 0)::numeric
      FROM balance
    UNION ALL
    SELECT 'CHK-parcels-054',
           'Both periods: parcel-periods where the Recharge term is non-zero (the Uses foot cell reads something other than 0.00)',
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
    -- 137-01, ISS-147: the six curtailed parcels (MER-APN-010/011/012/013/
    -- 014/019) must now resolve to WY 2025-2026 by DEFAULT (no `?period=`).
    -- Before 137-01 the old heuristic put them on the wrong year; this is the
    -- independent proof of the fix, over `resolved_period`'s new four-step
    -- transcription rather than the six parcels named by hand.
    SELECT 'CHK-parcels-080',
           'Parcels whose pane resolves to WY 2024-2025 (period 1) with no ?period= given',
           count(*) FILTER (WHERE period_id = 1)::numeric FROM resolved_period
    UNION ALL
    SELECT 'CHK-parcels-081',
           'Parcels whose pane resolves to WY 2025-2026 (period 2) with no ?period= given',
           count(*) FILTER (WHERE period_id = 2)::numeric FROM resolved_period
    UNION ALL
    SELECT 'CHK-parcels-082',
           'Of the six ISS-147 parcels (MER-APN-010/011/012/013/014/019), how many resolve to WY 2025-2026 (period 2) with no ?period= given. Expect 6.',
           count(*) FILTER (WHERE rp.period_id = 2)::numeric
      FROM resolved_period rp
      JOIN parcels_parcel pa ON pa.id = rp.parcel_id
     WHERE pa.parcel_number IN ('MER-APN-010', 'MER-APN-011', 'MER-APN-012',
                                 'MER-APN-013', 'MER-APN-014', 'MER-APN-019')
    UNION ALL
    SELECT 'CHK-parcels-090',
           'Total parcels',
           count(*)::numeric FROM parcels_parcel
)

SELECT id, pin, label, recomputed FROM figures
UNION ALL
SELECT id, '(all 76 parcels)', label, recomputed FROM column_checks
ORDER BY 1, 2;
