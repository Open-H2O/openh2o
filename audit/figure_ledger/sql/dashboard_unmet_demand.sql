-- FIG-accounting-052, FIG-accounting-053, FIG-accounting-054: the dashboard's
-- "Fields with water use recorded and no supply reported" section (ISS-157,
-- surface 2, 137-02): the per-row Consumptive Use cell, the per-row "water use
-- recorded, no supply reported" cell, and the District total footer.
--
-- THE FIGURE. Same engine output `parcel_unmet_demand.sql` already recomputes
-- for the field's own page (FIG-parcels-010): the CalculationRun rows whose
-- residual_disposition is 'unmet_demand'. This file is the district-wide half
-- of the identical question, grouped by parcel across the WHOLE reporting
-- period rather than summed for one field, so it is the same query shape as
-- `parcel_unmet_demand.sql`'s Block C, restated with a per-parcel gross-ET sum
-- alongside it and a district total, which is what the dashboard's tfoot prints.
--
-- INDEPENDENCE. This file names tables and columns only. It imports nothing,
-- calls no project function, and runs on the host through
-- audit/figure_ledger/run_sql.sh, outside the process that owns the
-- object-relational mapper.
--
-- Selection rules transcribed from source, read 2026-09-06:
--   accounting/services.py:853-889  unmet_demand_by_parcel, taking a reporting
--       period: the runs `runs_in_period` selects for that period, filtered
--       residual_disposition = 'unmet_demand' AND unmet_demand_af > 0, grouped
--       by parcel, Sum(unmet_demand_af) and Sum(gross_et_af), ordered by the
--       unmet sum descending. ONLY a non-zero shortfall is a row (137-02): 47
--       parcels carry the disposition and 41 sit at exactly zero, because canal
--       water covered the whole year, and are excluded here the same way.
--   accounting/services.py:617-634  runs_in_period, the SAME membership rule
--       `parcel_unmet_demand.sql` already transcribes: a CalculationRun belongs
--       to a period when its period_start falls between the first day of the
--       period's opening month and the period's end date.
--
-- THE PINNED INSTANCE (dashboard, WY 2025-2026, dry year, period id 2):
-- MER-APN-011, gross ET 363.2576 -> 363.26 AF, unmet 330.3677 -> 330.37 AF --
-- the same field and figure `parcel_unmet_demand.sql` pins on the field's own
-- page. District total for that period: 1,986.5015 -> 1,986.50 AF over six
-- fields (010, 011, 012, 013, 014, 019). WY 2024-2025 carries the same six
-- fields at 962.6696 AF total -- the wet year is NOT silent (137-02 Task 2's
-- plan premise did not reproduce; see 137-02-EVIDENCE.md section 3.1).
--
-- CROSS-CHECK BEFORE TRUSTING ANYTHING ELSE. Block A must reproduce the two
-- known totals; if it does not, the query is wrong and Block B is not to be
-- trusted either.

\set ON_ERROR_STOP on

CREATE TEMP VIEW _periods AS
SELECT rp.id AS period_id,
       rp.name AS water_year,
       date_trunc('month', rp.start_date)::date AS first_month,
       rp.end_date
  FROM accounting_reportingperiod rp;

-- Per (parcel, period): the unmet-demand sum AND the gross-ET sum, reproducing
-- accounting/services.py:unmet_demand_by_parcel exactly -- only runs whose
-- residual_disposition is 'unmet_demand' contribute to either aggregate, and a
-- run belongs to a period under the same date-overlap rule runs_in_period
-- applies.
CREATE TEMP VIEW _unmet AS
SELECT p.id AS parcel_id, p.parcel_number, pr.period_id, pr.water_year,
       COALESCE(SUM(cr.unmet_demand_af)
                FILTER (WHERE cr.residual_disposition = 'unmet_demand'), 0)
         AS unmet_demand_af,
       COALESCE(SUM(cr.gross_et_af)
                FILTER (WHERE cr.residual_disposition = 'unmet_demand'), 0)
         AS gross_et_af
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
\echo '== B. FIG-accounting-052 / 047: the pinned instance. MER-APN-011, WY 2025-2026. =='

SELECT 'FIG-accounting-052' AS id,
       'Consumptive Use (AF)' AS label,
       round(gross_et_af, 2) AS recomputed
  FROM _unmet
 WHERE parcel_number = 'MER-APN-011' AND period_id = 2
UNION ALL
SELECT 'FIG-accounting-053' AS id,
       'Water use recorded, no supply reported (AF)' AS label,
       round(unmet_demand_af, 2) AS recomputed
  FROM _unmet
 WHERE parcel_number = 'MER-APN-011' AND period_id = 2;

\echo ''
\echo '== C. FIG-accounting-054: the District total footer, both periods. Expect 1986.50 and 962.67. =='

SELECT water_year,
       round(sum(unmet_demand_af), 2) AS district_total_af
  FROM _unmet
 WHERE unmet_demand_af > 0
 GROUP BY water_year, period_id
 ORDER BY period_id;

\echo ''
\echo '== D. The whole section, WY 2025-2026, in the order the dashboard renders it (unmet descending). =='

SELECT parcel_number,
       round(gross_et_af, 2) AS consumptive_use_af,
       round(unmet_demand_af, 2) AS unmet_demand_af
  FROM _unmet
 WHERE period_id = 2 AND unmet_demand_af > 0
 ORDER BY unmet_demand_af DESC;

\echo ''
\echo '== E. How many parcels carry a non-zero shortfall, each year. Expect 6 and 6 -- the same count parcel_unmet_demand.sql block D reports. =='

SELECT water_year,
       count(*) FILTER (WHERE unmet_demand_af > 0) AS parcels_with_unmet_demand
  FROM _unmet
 GROUP BY water_year, period_id
 ORDER BY period_id;
