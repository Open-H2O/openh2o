-- FIG-parcels-011 (block C). Blocks A and B, which recomputed the old
-- FIG-accounting-007, FIG-accounting-012 and FIG-accounting-018, were removed
-- on 2026-09-28 when 148-03 made the calculation page a receipt and those
-- three sites went with it (the receipt's own sites are recomputed in
-- calculation_receipt.sql). What remains is the field page's cause line.
--
-- THE FIGURE.
--   FIG-parcels-011     templates/parcels/partials/_detail_pane.html, the
--       cause line under a residual that is real (a field with no meter and
--       no closing estimate): "Canal water beyond what the crop could use:
--       N AF", the sum of CalculationRun.over_delivery_af over the runs the
--       balance beside it reads, under EVERY over_delivery_treatment value
--       (accounting/services.py, parcel_over_delivery_total; unlike
--       parcel_over_delivery_shown, FIG-parcels-013, which sums only the
--       named_line runs). On the section's pinned screen, MER-APN-011 in WY
--       2025-2026, the sum is 0.0000 and the line is absent (DESIGN.md rule
--       8). It renders on MER-APN-019 in WY 2024-2025, the row's pinned
--       instance: 4.21 AF, the December 2024 month (4.2068 AF, a no-well month
--       the calculation page now answers with its short page) plus eleven
--       months of 0.
--
-- INDEPENDENCE. This file names tables and columns only. It imports nothing,
-- calls no project function, and runs on the host through
-- audit/figure_ledger/run_sql.sh, outside the process that owns the
-- object-relational mapper. The period sum runs under the same date
-- membership rule parcel_unmet_demand.sql transcribes from runs_in_period.

\set ON_ERROR_STOP on

\echo ''
\echo '== C. FIG-parcels-011: SUM(over_delivery_af) over the runs in the period, every treatment value, under the date membership rule runs_in_period applies: period_start between the first day of the period''s opening month and its end date. MER-APN-011 WY 2025-2026 expect 0.0000 (line absent); MER-APN-019 WY 2024-2025 expect 4.2069 (rendered 4.21). =='

CREATE TEMP VIEW _periods AS
SELECT rp.id AS period_id, rp.name AS water_year,
       date_trunc('month', rp.start_date)::date AS first_month, rp.end_date
  FROM accounting_reportingperiod rp;

SELECT 'FIG-parcels-011' AS id, p.parcel_number, pr.water_year,
       count(cr.id) AS runs,
       round(coalesce(sum(cr.over_delivery_af), 0), 4) AS over_delivery_total_af,
       round(coalesce(sum(cr.over_delivery_af) FILTER (WHERE cr.period = '2024-12'), 0), 4)
         AS of_which_december_2024
  FROM parcels_parcel p
 CROSS JOIN _periods pr
  LEFT JOIN accounting_calculationrun cr
         ON cr.parcel_id = p.id
        AND cr.period_start >= pr.first_month
        AND cr.period_start <= pr.end_date
 WHERE (p.parcel_number, pr.water_year) IN (('MER-APN-011', 'WY 2025-2026'),
                                            ('MER-APN-019', 'WY 2024-2025'))
 GROUP BY p.parcel_number, pr.water_year
 ORDER BY p.parcel_number;
