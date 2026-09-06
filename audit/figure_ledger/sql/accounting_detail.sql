-- FIG-accounting-001..022, FIG-accounting-046..053. The accounting money layer:
-- the account balance pane, the calculation-run audit page, the methodology live
-- preview, the use-ledger table and its footer subtotals, the allocations table,
-- and the reporting-period detail page. 30 rendered figures across six templates
-- (31 until 136-01 retired the use-ledger footer's net, 2026-09-06: paper and
-- water are not addable, so the platform stopped printing their sum; DESIGN.md
-- rule 12, review question 3, ISS-155. Every id after it moved up by one.)
--
-- Screens, all pinned to WY 2025-2026 (reporting period id 2, the dry year), the
-- same water year section 1 pinned on the dashboard:
--   /accounting/accounts/78/?period=2                       FIG-009..020
--   /accounting/calculation-run/16/2026-03/                 FIG-001..008
--   /accounting/methodology/preview/?parcel_id=16&period=2026-03
--                                                           FIG-049..052
--   /accounting/ledger/?period=2                            FIG-046..048
--   /accounting/allocations/?period=2                       FIG-021..022
--   /accounting/reporting-periods/2/                        FIG-053
--
-- Pinned rows:
--   Account   MER-ACCT-001 Ashvale Orchards Inc. (id 78), the same account
--             section 1 pinned, so the two screens can be held against each other.
--   Parcel    MER-APN-021 (id 21), the first row of that account's per-parcel
--             table. Pinned BY PARCEL NUMBER, not by position: all 18 of this
--             account's assignments carry added_date 2026-09-05, so the view's
--             `-added_date` sort does not order them and "the first row" is not a
--             reproducible pin.
--   Run       parcel 16 (MER-APN-016), month 2026-03, calculation run id 19548.
--             Chosen because effective precipitation actually bites there, so the
--             waterfall's In and Out columns differ instead of repeating one number.
--   Ledger    the first entry row the table shows, reproduced below by restating
--             the view's ORDER BY rather than by guessing at a row.
--   Alloc     Halvern Irrigation-Urban GSA — Groundwater WY 2025-2026 (750.32 AF),
--             first row of the allocations list. On the period detail page the
--             pin is Halvern Valley GSA — Groundwater WY 2025-2026 (9,689.40 AF),
--             pinned by NAME because that view applies no ordering at all.
--
-- INDEPENDENCE. This file references tables and columns only. It does not import,
-- call, or shell into any project module, and it runs on the host through
-- audit/figure_ledger/run_sql.sh, outside the process that owns the
-- object-relational mapper. Constants and selection rules the application owns are
-- transcribed as literals with the source line beside them.
--
-- INDEPENDENCE CLASS, stated per row in the ledger's Notes column:
--   * DIFFERENT IDENTITY. The gross evapotranspiration and effective-precipitation
--     figures are rebuilt from the RAW satellite and weather rows in
--     datasync_openetcache plus the parcel's acreage, through the TR-21 formula
--     transcribed below. They never read gross_et_af or effective_precip_af, so
--     they can disagree with the stored run, and would if the engine's arithmetic
--     were wrong. Likewise the ledger footer's credits+debits=net identity, the
--     waterfall's step-to-step continuity, the per-parcel-sums-to-account-total
--     identity, and final_af against the magnitude of the calculated ledger row.
--   * RESTATEMENT. The supply, net and allocation figures re-derive the same chain
--     the service performs. That can catch a coding mistake; it cannot catch a
--     wrong idea about what the figure should mean.
--
-- Selection rules transcribed from source, read 2026-09-05:
--   accounting/services.py:377  billable_ledger. An `et_estimate` row is
--       suppressed where a `calculated` row exists for the same
--       (parcel, effective_date), or a `meter_reading` row exists for the same
--       (parcel, first-of-that-month). STATED BELOW AS ITS OWN PREDICATE, in the
--       `billable` CTE. Without it every supply figure double-counts a month that
--       carries both a gross estimate and a netted value.
--   accounting/services.py:472  _balance_dict. "usage" is the ABSOLUTE VALUE OF
--       THE SUM of negative amounts excluding surface_diversion. Not the sum of
--       absolute values: a positive row inside that set would offset, and the two
--       differ. Transcribed as written.
--   accounting/services.py:869  surface supply is abs(SUM(amount)) over billable
--       surface_diversion rows. Stored negative by production convention; a canal
--       delivery is a supply to the parcel, so its magnitude counts.
--   accounting/services.py:617  runs_in_period. A CalculationRun belongs to a
--       period when period_start falls between the FIRST OF THE PERIOD'S OPENING
--       MONTH and the period's end date. Monthly runs are not pro-rated.
--   accounting/services.py:919  an account's parcels are its assignments with
--       removed_date IS NULL.
--   accounting/services.py:881  consumptive_use_balance sums gross_et_af,
--       net_consumptive_use_af and effective_precip_af over those runs; supply_total
--       is surface + groundwater + precip and net_vs_supply is supply_total − gross.
--   accounting/views.py:642     the per-parcel table calls the SINGLE-PARCEL
--       wrapper once per assignment, so the suppression above is computed inside a
--       one-parcel scope. The suppression key includes parcel_id, so scoping it to
--       one parcel or to eighteen gives the identical answer, the additivity claim
--       at accounting/services.py:458. Checked below rather than assumed.
--   accounting/views.py:996     the use-ledger footer totals aggregate the RAW
--       filtered queryset. They do NOT pass through billable_ledger, so the ledger
--       page and the balance panes are on different bases by design. Both bases are
--       computed below so the size of that difference is on the record.
--   accounting/views.py:474     allocation_total is a plain SUM over the filtered
--       allocation rows, unsigned.
--   accounting/views.py:1232    the run page takes the most recent run for
--       (parcel, period); the banking block renders only when banked_af > 0 or
--       drawn_af > 0.
--   accounting/services.py:369  et_mm_to_acre_feet. ET (AF) = ET (mm) × area
--       (acres) / 304.8. The 304.8 is millimetre-acres per acre-foot.
--   accounting/precip_math.py:47  storage factor SF = 0.531747 + 0.295164·D
--       − 0.057697·D² + 0.003804·D³, with D the net soil-moisture storage in
--       inches. The saved methodology (accounting_calculationstep id 2) sets
--       D = 3.0, giving SF = 1.000674 exactly at the precision used here.
--   accounting/precip_math.py:94  TR-21 core, evaluated in millimetres:
--       Pe = SF × (1.25 · P^0.824 − 2.93) × 10^(0.000955 · ET)
--       then capped at both P and ET (precip_math.py:97) and floored at zero.
--   accounting/steps.py:369     that Pe in millimetres becomes acre-feet through
--       the same 304.8 divisor, using the parcel's acreage.

\set ON_ERROR_STOP on

WITH pin AS (
    SELECT 2::bigint   AS period_id,      -- WY 2025-2026, the dry year
           78::bigint  AS account_id,     -- MER-ACCT-001 Ashvale Orchards Inc.
           21::bigint  AS parcel_row_id,  -- MER-APN-021, the pinned per-parcel row
           16::bigint  AS run_parcel_id,  -- MER-APN-016, the pinned calculation run
           '2026-03'::text AS run_period
),
period AS (
    SELECT rp.id, rp.start_date, rp.end_date,
           date_trunc('month', rp.start_date)::date AS first_month
      FROM accounting_reportingperiod rp
      JOIN pin ON rp.id = pin.period_id
),

-- ── The account's parcels, and the ledger rows in scope ───────────────────────
members AS (
    SELECT wap.parcel_id
      FROM accounting_wateraccountparcel wap
      JOIN pin ON wap.water_account_id = pin.account_id
     WHERE wap.removed_date IS NULL
     GROUP BY wap.parcel_id
),
ledger AS (
    SELECT pl.parcel_id, pl.effective_date, pl.source_type, pl.amount_acre_feet
      FROM parcels_parcelledger pl
      JOIN members m ON m.parcel_id = pl.parcel_id
      JOIN period p ON pl.reporting_period_id = p.id
),
-- The suppression keys. Written out as its own predicate because it is the one
-- rule that, if dropped, silently doubles every supply figure on the pane.
suppression AS (
    SELECT DISTINCT parcel_id, effective_date AS key_date
      FROM ledger WHERE source_type = 'calculated'
    UNION
    SELECT DISTINCT parcel_id, date_trunc('month', effective_date)::date
      FROM ledger WHERE source_type = 'meter_reading'
),
billable AS (
    SELECT l.*
      FROM ledger l
     WHERE NOT (
        l.source_type = 'et_estimate'
        AND EXISTS (SELECT 1 FROM suppression s
                     WHERE s.parcel_id = l.parcel_id
                       AND s.key_date = l.effective_date)
     )
),
supplies_by_parcel AS (
    SELECT parcel_id,
           abs(COALESCE(SUM(amount_acre_feet)
               FILTER (WHERE source_type = 'surface_diversion'), 0)) AS surface,
           abs(COALESCE(SUM(amount_acre_feet)
               FILTER (WHERE amount_acre_feet < 0
                         AND source_type <> 'surface_diversion'), 0)) AS groundwater
      FROM billable
     GROUP BY parcel_id
),
runs_by_parcel AS (
    SELECT m.parcel_id,
           COALESCE(SUM(cr.gross_et_af), 0)            AS gross,
           COALESCE(SUM(cr.net_consumptive_use_af), 0) AS net_cu,
           COALESCE(SUM(cr.effective_precip_af), 0)    AS precip,
           COUNT(cr.id)                                AS run_count
      FROM members m
      LEFT JOIN accounting_calculationrun cr ON cr.parcel_id = m.parcel_id
      LEFT JOIN period p ON cr.period_start >= p.first_month
                        AND cr.period_start <= p.end_date
     WHERE cr.id IS NULL OR p.id IS NOT NULL
     GROUP BY m.parcel_id
),
parcel_balance AS (
    SELECT m.parcel_id,
           COALESCE(s.surface, 0)     AS surface,
           COALESCE(s.groundwater, 0) AS groundwater,
           COALESCE(r.precip, 0)      AS precip,
           COALESCE(s.surface, 0) + COALESCE(s.groundwater, 0)
             + COALESCE(r.precip, 0)  AS supply_total,
           COALESCE(r.gross, 0)       AS gross,
           COALESCE(r.net_cu, 0)      AS net_cu,
           COALESCE(r.run_count, 0)   AS run_count,
           COALESCE(s.surface, 0) + COALESCE(s.groundwater, 0)
             + COALESCE(r.precip, 0) - COALESCE(r.gross, 0) AS net_vs_supply
      FROM members m
      LEFT JOIN supplies_by_parcel s ON s.parcel_id = m.parcel_id
      LEFT JOIN runs_by_parcel r     ON r.parcel_id = m.parcel_id
),
-- The account-level pane. Computed over the WHOLE parcel set in one pass, which
-- is how account_consumptive_balance does it: one billable_ledger call spanning
-- every parcel, not eighteen single-parcel calls added up.
account_supplies AS (
    SELECT abs(COALESCE(SUM(amount_acre_feet)
               FILTER (WHERE source_type = 'surface_diversion'), 0)) AS surface,
           abs(COALESCE(SUM(amount_acre_feet)
               FILTER (WHERE amount_acre_feet < 0
                         AND source_type <> 'surface_diversion'), 0)) AS groundwater
      FROM billable
),
account_runs AS (
    SELECT COALESCE(SUM(cr.gross_et_af), 0)            AS gross,
           COALESCE(SUM(cr.net_consumptive_use_af), 0) AS net_cu,
           COALESCE(SUM(cr.effective_precip_af), 0)    AS precip,
           COUNT(cr.id)                                AS run_count
      FROM members m
      JOIN accounting_calculationrun cr ON cr.parcel_id = m.parcel_id
      JOIN period p ON cr.period_start >= p.first_month
                   AND cr.period_start <= p.end_date
),
account_balance AS (
    SELECT s.surface, s.groundwater, r.precip, r.gross, r.net_cu, r.run_count,
           s.surface + s.groundwater + r.precip                AS supply_total,
           s.surface + s.groundwater + r.precip - r.gross      AS net_vs_supply
      FROM account_supplies s CROSS JOIN account_runs r
),
pinned_parcel AS (
    SELECT pb.* FROM parcel_balance pb JOIN pin ON pb.parcel_id = pin.parcel_row_id
),

-- ── The calculation-run audit page ────────────────────────────────────────────
run_row AS (
    SELECT cr.*
      FROM accounting_calculationrun cr
      JOIN pin ON cr.parcel_id = pin.run_parcel_id AND cr.period = pin.run_period
     ORDER BY cr.created_at DESC
     LIMIT 1
),
run_steps AS (
    SELECT s.ord,
           (s.step->>'input_af')::numeric  AS input_af,
           (s.step->>'output_af')::numeric AS output_af,
           s.step->>'step_type'            AS step_type
      FROM run_row cr,
           LATERAL jsonb_array_elements(cr.breakdown) WITH ORDINALITY AS s(step, ord)
),
-- The `calculated` ledger row the result card says the final figure equals.
run_ledger_row AS (
    SELECT abs(COALESCE(SUM(pl.amount_acre_feet), 0)) AS magnitude
      FROM parcels_parcelledger pl
      JOIN pin ON pl.parcel_id = pin.run_parcel_id
     WHERE pl.source_type = 'calculated'
       AND pl.effective_date = (pin.run_period || '-01')::date
),

-- ── DIFFERENT IDENTITY: rebuild the run's two source figures from raw rows ────
-- Nothing below reads gross_et_af or effective_precip_af. It starts at the
-- satellite and weather observations and the parcel's acreage and walks the
-- published TR-21 formula, so it can disagree with the engine.
raw_monthly AS (
    SELECT c.parcel_id,
           (e.value->>'date')          AS month_label,
           MAX((e.value->>'et')::numeric) FILTER
               (WHERE c.variable = 'ET' AND c.model_name = 'Ensemble')     AS et_mm,
           MAX((e.value->>'precip')::numeric) FILTER
               (WHERE c.variable = 'precip' AND c.model_name = 'GRIDMET')  AS precip_mm
      FROM datasync_openetcache c,
           LATERAL jsonb_array_elements(c.et_data) AS e(value)
     WHERE c.variable IN ('ET', 'precip')
     GROUP BY c.parcel_id, e.value->>'date'
),
raw_derived AS (
    SELECT rm.parcel_id, rm.month_label, rm.et_mm, rm.precip_mm, p.area_acres,
           -- 304.8: accounting/services.py:369, mm-acres per acre-foot.
           rm.et_mm * p.area_acres / 304.8 AS gross_af,
           -- TR-21 in mm, then capped at min(P, ET) and floored at zero, then
           -- converted through the same divisor. SF = 1.000674 for D = 3.0 inches.
           GREATEST(
             LEAST(
               (1.000674
                 * (1.25 * power(rm.precip_mm::double precision, 0.824) - 2.93)
                 * power(10::double precision,
                         0.000955 * rm.et_mm::double precision))::numeric,
               rm.precip_mm, rm.et_mm),
             0) * p.area_acres / 304.8 AS pe_af
      FROM raw_monthly rm
      JOIN parcels_parcel p ON p.id = rm.parcel_id
     WHERE rm.et_mm IS NOT NULL AND rm.precip_mm IS NOT NULL
),
raw_run_pin AS (
    SELECT rd.* FROM raw_derived rd
      JOIN pin ON rd.parcel_id = pin.run_parcel_id AND rd.month_label = pin.run_period
),
raw_account AS (
    SELECT COALESCE(SUM(rd.gross_af), 0) AS gross_af,
           COALESCE(SUM(rd.pe_af), 0)    AS pe_af,
           COUNT(*)                      AS months
      FROM raw_derived rd
      JOIN members m ON m.parcel_id = rd.parcel_id
      JOIN period p ON (rd.month_label || '-01')::date >= p.first_month
                   AND (rd.month_label || '-01')::date <= p.end_date
),

-- ── The use-ledger table and its footer ───────────────────────────────────────
-- The view filters on reporting_period only (no other facet set on the pinned
-- URL) and aggregates the RAW rows; its default order is newest effective_date
-- first with created_at as the tiebreak.
ledger_scope AS (
    SELECT pl.id, pl.parcel_id, pl.effective_date, pl.created_at,
           pl.source_type, pl.amount_acre_feet
      FROM parcels_parcelledger pl
      JOIN period p ON pl.reporting_period_id = p.id
),
ledger_first_row AS (
    SELECT ls.*, pp.parcel_number
      FROM ledger_scope ls
      JOIN parcels_parcel pp ON pp.id = ls.parcel_id
     ORDER BY ls.effective_date DESC, ls.created_at DESC
     LIMIT 1
),
ledger_totals AS (
    SELECT COUNT(*)                                    AS entries,
           COALESCE(SUM(amount_acre_feet), 0)          AS net,
           COALESCE(SUM(amount_acre_feet)
               FILTER (WHERE amount_acre_feet >= 0), 0) AS credits,
           COALESCE(SUM(amount_acre_feet)
               FILTER (WHERE amount_acre_feet < 0), 0)  AS debits
      FROM ledger_scope
),
-- The same footer on the BILLABLE basis the balance panes use, so the size of the
-- difference between the two screens is on the record rather than left implied.
ledger_suppression AS (
    SELECT DISTINCT parcel_id, effective_date AS key_date
      FROM ledger_scope WHERE source_type = 'calculated'
    UNION
    SELECT DISTINCT parcel_id, date_trunc('month', effective_date)::date
      FROM ledger_scope WHERE source_type = 'meter_reading'
),
ledger_totals_billable AS (
    SELECT COUNT(*)                           AS entries,
           COALESCE(SUM(amount_acre_feet), 0) AS net
      FROM ledger_scope ls
     WHERE NOT (
        ls.source_type = 'et_estimate'
        AND EXISTS (SELECT 1 FROM ledger_suppression s
                     WHERE s.parcel_id = ls.parcel_id
                       AND s.key_date = ls.effective_date)
     )
),

-- ── Allocations ───────────────────────────────────────────────────────────────
alloc_scope AS (
    SELECT ap.id, ap.name, ap.allocation_acre_feet, ap.zone_id
      FROM accounting_allocationplan ap
      JOIN period p ON ap.reporting_period_id = p.id
),
alloc_total AS (
    SELECT COUNT(*) AS n, COALESCE(SUM(allocation_acre_feet), 0) AS total
      FROM alloc_scope
),

-- ── Cross-checks that can disagree ────────────────────────────────────────────
checks AS (
    SELECT
      -- Does the suppression rule actually fire on this data?
      (SELECT COUNT(*) FROM ledger_scope WHERE source_type = 'et_estimate')
          AS estimate_rows_in_period,
      (SELECT COUNT(*) FROM ledger_scope ls
        WHERE ls.source_type = 'et_estimate'
          AND EXISTS (SELECT 1 FROM ledger_suppression s
                       WHERE s.parcel_id = ls.parcel_id
                         AND s.key_date = ls.effective_date))
          AS estimate_rows_suppressed,
      (SELECT COUNT(*) FROM parcels_parcelledger WHERE source_type = 'et_estimate')
          AS estimate_rows_all_time,
      -- Banking: can the run page's banked block render at all?
      (SELECT COUNT(*) FROM accounting_calculationrun) AS runs_all,
      (SELECT COUNT(*) FROM accounting_calculationrun
        WHERE banked_af <> 0 OR drawn_af <> 0) AS runs_with_banking,
      (SELECT COUNT(*) FROM accounting_watercreditdraw) AS credit_draws,
      (SELECT COUNT(*) FROM accounting_watercredit) AS credits_held,
      -- Can the preview's "no steps" branch render?
      (SELECT COUNT(*) FROM accounting_calculationstep s
         JOIN accounting_calculationplan pl ON pl.id = s.plan_id
        WHERE pl.is_active AND s.enabled) AS enabled_steps_on_active_plan,
      -- Waterfall continuity: each step's In must equal the previous step's Out.
      (SELECT COUNT(*) FROM (
          SELECT ord, input_af,
                 lag(output_af) OVER (ORDER BY ord) AS prev_out
            FROM run_steps) t
        WHERE prev_out IS NOT NULL AND round(input_af, 4) <> round(prev_out, 4))
          AS waterfall_breaks,
      -- Per-parcel rows must sum to the account pane above them.
      (SELECT round(SUM(supply_total), 2) FROM parcel_balance) AS parcels_supply_sum,
      (SELECT round(SUM(gross), 2)        FROM parcel_balance) AS parcels_gross_sum,
      (SELECT round(SUM(surface), 2)      FROM parcel_balance) AS parcels_surface_sum,
      (SELECT round(SUM(precip), 2)       FROM parcel_balance) AS parcels_precip_sum,
      (SELECT COUNT(*) FROM members)      AS account_parcels,
      (SELECT run_count FROM account_runs) AS account_runs
),

figures AS (
    -- ── The calculation-run audit page ───────────────────────────────────────
    SELECT 'FIG-accounting-001' AS id,
           'Run page: parcel acreage (MER-APN-016)' AS label,
           round((SELECT area_acres FROM parcels_parcel
                   JOIN pin ON parcels_parcel.id = pin.run_parcel_id), 2) AS recomputed
    UNION ALL SELECT 'FIG-accounting-002', 'Run page: header final billable groundwater',
           round((SELECT final_af FROM run_row), 4)
    UNION ALL SELECT 'FIG-accounting-003', 'Run page: step 1 In (AF)',
           round((SELECT input_af FROM run_steps WHERE ord = 1), 4)
    UNION ALL SELECT 'FIG-accounting-004', 'Run page: step 1 Out (AF), from raw satellite rows',
           round((SELECT gross_af FROM raw_run_pin), 4)
    UNION ALL SELECT 'FIG-accounting-005', 'Run page: banked this month (block does not render)',
           round((SELECT banked_af FROM run_row), 4)
    UNION ALL SELECT 'FIG-accounting-006', 'Run page: drawn this month (block does not render)',
           round((SELECT drawn_af FROM run_row), 4)
    UNION ALL SELECT 'FIG-accounting-007', 'Run page: one credit draw (no draw rows exist)',
           (SELECT round(SUM(amount_af), 4) FROM accounting_watercreditdraw)
    UNION ALL SELECT 'FIG-accounting-008', 'Run page: result card final billable groundwater',
           round((SELECT final_af FROM run_row), 4)

    -- ── The account balance pane ─────────────────────────────────────────────
    UNION ALL SELECT 'FIG-accounting-009', 'Account pane: Supplies',
           round((SELECT supply_total FROM account_balance), 2)
    UNION ALL SELECT 'FIG-accounting-010', 'Account pane: Consumptive use',
           round((SELECT gross FROM account_balance), 2)
    UNION ALL SELECT 'FIG-accounting-011', 'Account pane: Balance',
           round((SELECT net_vs_supply FROM account_balance), 2)
    UNION ALL SELECT 'FIG-accounting-012', 'Account pane foot: Surface',
           round((SELECT surface FROM account_balance), 2)
    UNION ALL SELECT 'FIG-accounting-013', 'Account pane foot: Groundwater',
           round((SELECT groundwater FROM account_balance), 2)
    UNION ALL SELECT 'FIG-accounting-014', 'Account pane foot: Rain',
           round((SELECT precip FROM account_balance), 2)

    -- ── The per-parcel table, pinned to MER-APN-021 ──────────────────────────
    UNION ALL SELECT 'FIG-accounting-015', 'Per-parcel MER-APN-021: Consumptive Use',
           round((SELECT gross FROM pinned_parcel), 2)
    UNION ALL SELECT 'FIG-accounting-016', 'Per-parcel MER-APN-021: Surface',
           round((SELECT surface FROM pinned_parcel), 2)
    UNION ALL SELECT 'FIG-accounting-017', 'Per-parcel MER-APN-021: Groundwater',
           round((SELECT groundwater FROM pinned_parcel), 2)
    UNION ALL SELECT 'FIG-accounting-018', 'Per-parcel MER-APN-021: Precip',
           round((SELECT precip FROM pinned_parcel), 2)
    UNION ALL SELECT 'FIG-accounting-019', 'Per-parcel MER-APN-021: Supplies',
           round((SELECT supply_total FROM pinned_parcel), 2)
    UNION ALL SELECT 'FIG-accounting-020', 'Per-parcel MER-APN-021: Net',
           round((SELECT net_vs_supply FROM pinned_parcel), 2)

    -- ── The allocations list ─────────────────────────────────────────────────
    UNION ALL SELECT 'FIG-accounting-021',
           'Allocations list: Halvern Irrigation-Urban GSA — Groundwater WY 2025-2026',
           round((SELECT allocation_acre_feet FROM alloc_scope
                   WHERE name = 'Halvern Irrigation-Urban GSA — Groundwater WY 2025-2026'), 2)
    UNION ALL SELECT 'FIG-accounting-022', 'Allocations list: footer total, all 8 allocations',
           round((SELECT total FROM alloc_total), 2)

    -- ── The use ledger ───────────────────────────────────────────────────────
    UNION ALL SELECT 'FIG-accounting-046', 'Use ledger: first row Amount (AF)',
           round((SELECT amount_acre_feet FROM ledger_first_row), 2)
    -- 136-01: the footer names its two subtotals by kind and prints no net.
    -- Credits are the non-negative rows (allocation and recharge entries);
    -- "Delivered and pumped" is the magnitude of the negative rows.
    UNION ALL SELECT 'FIG-accounting-047', 'Use ledger footer: Credits',
           round((SELECT credits FROM ledger_totals), 2)
    UNION ALL SELECT 'FIG-accounting-048', 'Use ledger footer: Delivered and pumped (magnitude)',
           round(abs((SELECT debits FROM ledger_totals)), 2)

    -- ── The methodology live preview ─────────────────────────────────────────
    -- The preview stores nothing, so the independent thing to hold it against is
    -- the persisted run for the same parcel-month, and the raw rows underneath it.
    UNION ALL SELECT 'FIG-accounting-049', 'Preview: billable groundwater (vs the stored run)',
           round((SELECT final_af FROM run_row), 4)
    UNION ALL SELECT 'FIG-accounting-050', 'Preview: step 1 In (AF)',
           round((SELECT input_af FROM run_steps WHERE ord = 1), 4)
    UNION ALL SELECT 'FIG-accounting-051', 'Preview: step 1 Out (AF), from raw satellite rows',
           round((SELECT gross_af FROM raw_run_pin), 4)
    UNION ALL SELECT 'FIG-accounting-052',
           'Preview: no-steps fallback final (branch cannot render, see checks)',
           NULL::numeric

    -- ── The reporting-period detail page ─────────────────────────────────────
    UNION ALL SELECT 'FIG-accounting-053',
           'Period detail: Halvern Valley GSA — Groundwater WY 2025-2026',
           round((SELECT allocation_acre_feet FROM alloc_scope
                   WHERE name = 'Halvern Valley GSA — Groundwater WY 2025-2026'), 2)

    -- ── Cross-checks. These are not rendered figures; they are the identities
    --    that can disagree, and the guards whose state a reader must know.
    UNION ALL SELECT 'CHECK-run-final-vs-ledger',
           'Run final_af MINUS magnitude of its calculated ledger row (0 = agree)',
           round((SELECT final_af FROM run_row) - (SELECT magnitude FROM run_ledger_row), 4)
    UNION ALL SELECT 'CHECK-run-final-vs-last-step',
           'Run final_af MINUS last waterfall step Out (0 = agree)',
           round((SELECT final_af FROM run_row)
                 - (SELECT output_af FROM run_steps ORDER BY ord DESC LIMIT 1), 4)
    UNION ALL SELECT 'CHECK-waterfall-breaks',
           'Steps whose In differs from the previous Out (0 = continuous)',
           (SELECT waterfall_breaks FROM checks)::numeric
    UNION ALL SELECT 'CHECK-raw-gross-vs-stored-run',
           'Raw-row gross ET MINUS stored gross_et_af, pinned run (0 = agree)',
           round((SELECT gross_af FROM raw_run_pin) - (SELECT gross_et_af FROM run_row), 4)
    UNION ALL SELECT 'CHECK-raw-precip-vs-stored-run',
           'Raw-row TR-21 effective precip MINUS stored effective_precip_af (0 = agree)',
           round((SELECT pe_af FROM raw_run_pin) - (SELECT effective_precip_af FROM run_row), 4)
    UNION ALL SELECT 'CHECK-raw-gross-vs-account-pane',
           'Raw-row gross ET over the account year MINUS the pane Consumptive use',
           round((SELECT gross_af FROM raw_account) - (SELECT gross FROM account_balance), 2)
    UNION ALL SELECT 'CHECK-raw-precip-vs-account-pane',
           'Raw-row TR-21 effective precip over the account year MINUS the pane Rain',
           round((SELECT pe_af FROM raw_account) - (SELECT precip FROM account_balance), 2)
    UNION ALL SELECT 'CHECK-raw-account-months',
           'Parcel-months the raw recomputation covered (18 parcels x 12 = 216)',
           (SELECT months FROM raw_account)::numeric
    UNION ALL SELECT 'CHECK-parcels-sum-supplies',
           'Per-parcel Supplies summed MINUS the pane Supplies (0 = additive)',
           (SELECT parcels_supply_sum FROM checks) - round((SELECT supply_total FROM account_balance), 2)
    UNION ALL SELECT 'CHECK-parcels-sum-gross',
           'Per-parcel Consumptive Use summed MINUS the pane Consumptive use',
           (SELECT parcels_gross_sum FROM checks) - round((SELECT gross FROM account_balance), 2)
    UNION ALL SELECT 'CHECK-parcels-sum-surface',
           'Per-parcel Surface summed MINUS the pane Surface',
           (SELECT parcels_surface_sum FROM checks) - round((SELECT surface FROM account_balance), 2)
    UNION ALL SELECT 'CHECK-parcels-sum-precip',
           'Per-parcel Precip summed MINUS the pane Rain',
           (SELECT parcels_precip_sum FROM checks) - round((SELECT precip FROM account_balance), 2)
    UNION ALL SELECT 'CHECK-ledger-credits-plus-debits',
           'Ledger footer credits + debits MINUS net (0 = internally consistent)',
           round((SELECT credits + debits - net FROM ledger_totals), 2)
    UNION ALL SELECT 'CHECK-ledger-net-billable',
           'The same footer net on the BILLABLE basis the balance panes use',
           round((SELECT net FROM ledger_totals_billable), 2)
    UNION ALL SELECT 'CHECK-ledger-rows-suppressed',
           'Ledger rows the suppression predicate removes in this period',
           ((SELECT entries FROM ledger_totals) - (SELECT entries FROM ledger_totals_billable))::numeric
    UNION ALL SELECT 'CHECK-estimate-rows-in-period',
           'et_estimate rows in the pinned period (the suppression has nothing to bite on at 0)',
           (SELECT estimate_rows_in_period FROM checks)::numeric
    UNION ALL SELECT 'CHECK-estimate-rows-all-time',
           'et_estimate rows anywhere in the ledger',
           (SELECT estimate_rows_all_time FROM checks)::numeric
    UNION ALL SELECT 'CHECK-runs-with-banking',
           'Calculation runs with a non-zero banked or drawn figure',
           (SELECT runs_with_banking FROM checks)::numeric
    UNION ALL SELECT 'CHECK-runs-total',
           'Calculation runs in the database',
           (SELECT runs_all FROM checks)::numeric
    UNION ALL SELECT 'CHECK-credit-draws',
           'WaterCreditDraw rows (the draws table on the run page needs one)',
           (SELECT credit_draws FROM checks)::numeric
    UNION ALL SELECT 'CHECK-credits-held',
           'WaterCredit rows held',
           (SELECT credits_held FROM checks)::numeric
    UNION ALL SELECT 'CHECK-enabled-steps',
           'Enabled steps on the active methodology (the preview fallback needs 0)',
           (SELECT enabled_steps_on_active_plan FROM checks)::numeric
    UNION ALL SELECT 'CHECK-account-parcels',
           'Parcels on the pinned account',
           (SELECT account_parcels FROM checks)::numeric
    UNION ALL SELECT 'CHECK-account-runs',
           'Calculation runs behind the pinned account pane',
           (SELECT account_runs FROM checks)::numeric
    UNION ALL SELECT 'CHECK-ledger-entries',
           'Ledger entries in the pinned period (the footer says "All N entries")',
           (SELECT entries FROM ledger_totals)::numeric
    UNION ALL SELECT 'CHECK-alloc-count',
           'Allocation rows in the pinned period (the count pill)',
           (SELECT n FROM alloc_total)::numeric
    UNION ALL SELECT 'CHECK-ledger-first-row',
           'The first ledger row: parcel id, restating the view ORDER BY',
           (SELECT parcel_id FROM ledger_first_row)::numeric
)
SELECT id, label, recomputed FROM figures ORDER BY id;
