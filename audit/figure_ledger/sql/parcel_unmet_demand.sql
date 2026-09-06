-- FIG-parcels-010: "Water use recorded, no supply reported" (ISS-157, 137-01).
--
-- THE FIGURE. A field with no well cannot have its ET-minus-supplies leftover
-- booked as pumping — there is no well to have pumped it — so the engine
-- (accounting/management/commands/run_calculations.py:579-580) writes that
-- leftover onto the CalculationRun as `unmet_demand_af`, tagged
-- `residual_disposition="unmet_demand"`. The platform has always recorded
-- this; 137-01 is the first time any screen reads it back. The pane shows it
-- under the settled words, and ONLY when the sum is positive (DESIGN.md rule
-- 8: a zero renders nothing, never "0.00").
--
-- INDEPENDENCE. This file names tables and columns only. It imports nothing,
-- calls no project function, and runs on the host through
-- audit/figure_ledger/run_sql.sh, outside the process that owns the
-- object-relational mapper.
--
-- Selection rules transcribed from source, read 2026-09-06:
--   accounting/services.py:802-835  parcel_unmet_demand, taking a parcel and a
--       reporting period: sum of CalculationRun.unmet_demand_af, filtered
--       residual_disposition = 'unmet_demand', over the runs
--       `runs_in_period` selects for this parcel and period; Decimal("0")
--       when none, else quantized to 4 places.
--   accounting/services.py:617-634  runs_in_period, the SAME membership rule
--       `parcel_detail_pane.sql`'s `runs`/`periods` CTEs already transcribe: a
--       CalculationRun belongs to a period when its period_start falls between
--       the first day of the period's opening month and the period's end date.
--
-- THE SIX FIELDS CARRYING UNMET DEMAND (ISS-157), named rather than
-- rediscovered: MER-APN-010 (parcel id 10), -011 (11), -012 (12), -013 (13),
-- -014 (14), -019 (19). Measured 2026-09-06: 1,986.5015 AF total in WY
-- 2025-2026 (period 2, the dry year) and 962.6696 AF total in WY 2024-2025
-- (period 1, the wet year) across the six. MER-APN-011's own dry-year figure
-- is 330.3700 AF -- 330.37 AF as rendered (the pinned ISS-157 instance).
--
-- CROSS-CHECK BEFORE TRUSTING ANYTHING ELSE. Block A must reproduce the two
-- totals above; if it does not, the query is wrong and Block B is not to be
-- trusted either.

\set ON_ERROR_STOP on

CREATE TEMP VIEW _periods AS
SELECT rp.id AS period_id,
       rp.name AS water_year,
       date_trunc('month', rp.start_date)::date AS first_month,
       rp.end_date
  FROM accounting_reportingperiod rp;

-- The unmet-demand sum, per (parcel, period), reproducing
-- accounting/services.py:parcel_unmet_demand exactly: only runs whose
-- residual_disposition is 'unmet_demand' contribute, and a run belongs to a
-- period under the same date-overlap rule runs_in_period applies.
CREATE TEMP VIEW _unmet AS
SELECT p.id AS parcel_id, p.parcel_number, pr.period_id, pr.water_year,
       COALESCE(SUM(cr.unmet_demand_af)
                FILTER (WHERE cr.residual_disposition = 'unmet_demand'), 0)
         AS unmet_demand_af
  FROM parcels_parcel p
 CROSS JOIN _periods pr
  LEFT JOIN accounting_calculationrun cr
         ON cr.parcel_id = p.id
        AND cr.period_start >= pr.first_month
        AND cr.period_start <= pr.end_date
 GROUP BY p.id, p.parcel_number, pr.period_id, pr.water_year;

\echo ''
\echo '== A. The two known totals. Expect 1986.5015 for WY 2025-2026 and 962.6696 for WY 2024-2025, over MER-APN-010/011/012/013/014/019. =='

SELECT water_year,
       round(sum(unmet_demand_af), 4) AS total_unmet_demand_af
  FROM _unmet
 WHERE parcel_number IN ('MER-APN-010', 'MER-APN-011', 'MER-APN-012',
                          'MER-APN-013', 'MER-APN-014', 'MER-APN-019')
 GROUP BY water_year, period_id
 ORDER BY period_id;

\echo ''
\echo '== B. FIG-parcels-010: the pinned instance. MER-APN-011, WY 2025-2026 and WY 2024-2025, side by side. =='

SELECT 'FIG-parcels-010' AS id,
       parcel_number || ' p' || period_id AS pin,
       'Water use recorded, no supply reported' AS label,
       round(unmet_demand_af, 2) AS recomputed
  FROM _unmet
 WHERE parcel_number = 'MER-APN-011'
 ORDER BY period_id;

\echo ''
\echo '== C. Every parcel-year carrying unmet demand, whole column. =='

SELECT water_year,
       parcel_number,
       round(unmet_demand_af, 4) AS unmet_demand_af
  FROM _unmet
 WHERE unmet_demand_af > 0
 ORDER BY period_id, parcel_number;

\echo ''
\echo '== D. How many of the 76 parcels carry unmet demand, each year. Expect 6 and 6. =='

SELECT water_year,
       count(*) FILTER (WHERE unmet_demand_af > 0) AS parcels_with_unmet_demand
  FROM _unmet
 GROUP BY water_year, period_id
 ORDER BY period_id;
