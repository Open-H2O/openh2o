-- FIG-accounting-007, FIG-accounting-012, FIG-accounting-018 and
-- FIG-parcels-011: the four sites 148-03 added on 2026-09-28 when the
-- calculation page's three result bands became one row and the field page's
-- residual gained its canal cause line.
--
-- THE FIGURES.
--   FIG-accounting-007  templates/accounting/calculation_run_detail.html, the
--       result row's first cell on a field with NO well: the month's
--       remainder recorded as "Water use recorded, no supply reported",
--       CalculationRun.unmet_demand_af. Pinned to MER-APN-010, 2025-07
--       (98.3464). A zero renders nothing when the month's canal water went
--       past the crop (rule 12), so MER-APN-019 2024-12 shows no such cell.
--   FIG-accounting-012  the third cell's caption under the credited
--       treatment, "credited, less N% left in the basin":
--       over_delivery_share_pct, the run's stamped over_delivery_leave_behind
--       times 100. NOT rendered on the demonstration, which runs the default
--       (not_credited): the branch is proven with hand numbers in
--       tests/test_over_delivery_pages.py.
--   FIG-accounting-018  the same percent inside the pooled-credit sentence
--       under the row ("credited to the zone's shared account ... N% stays
--       in the basin"). Same column, same reason it does not render here.
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
--       instance: 4.21 AF, the same December 2024 month FIG-accounting-011
--       pins plus eleven months of 0.
--
-- INDEPENDENCE. This file names tables and columns only. It imports nothing,
-- calls no project function, and runs on the host through
-- audit/figure_ledger/run_sql.sh, outside the process that owns the
-- object-relational mapper. The unmet-demand figure is recomputed from the
-- three columns the engine subtracts (a different identity), the percent
-- from the stamped fraction, and the period sum under the same date
-- membership rule parcel_unmet_demand.sql transcribes from runs_in_period.

\set ON_ERROR_STOP on

\echo ''
\echo '== A. FIG-accounting-007: the pinned run, MER-APN-010 2025-07. Stored unmet_demand_af beside the remainder rebuilt from gross ET, effective rain and the canal water the crop could use, floored at 0 (accounting/steps.py clamp_floor). Expect 98.3464 and 98.3464. =='

SELECT 'FIG-accounting-007' AS id,
       p.parcel_number, cr.period, cr.residual_disposition,
       round(cr.unmet_demand_af, 4) AS stored_unmet_demand_af,
       round(greatest(cr.gross_et_af - cr.effective_precip_af - cr.surface_water_af, 0), 4)
         AS rebuilt_unmet_demand_af
  FROM accounting_calculationrun cr
  JOIN parcels_parcel p ON p.id = cr.parcel_id
 WHERE p.parcel_number = 'MER-APN-010' AND cr.period = '2025-07';

\echo ''
\echo '== A2. The same identity on a no-well month where the figure is not zero, MER-APN-011 2025-10 and 2025-11: stored 21.9087 and 1.7118. =='

SELECT p.parcel_number, cr.period,
       round(cr.unmet_demand_af, 4) AS stored_unmet_demand_af,
       round(greatest(cr.gross_et_af - cr.effective_precip_af - cr.surface_water_af, 0), 4)
         AS rebuilt_unmet_demand_af
  FROM accounting_calculationrun cr
  JOIN parcels_parcel p ON p.id = cr.parcel_id
 WHERE p.parcel_number = 'MER-APN-011' AND cr.period IN ('2025-10', '2025-11')
 ORDER BY cr.period;

\echo ''
\echo '== B. FIG-accounting-012 / FIG-accounting-018: the stamped leave-behind share on the pinned run, times 100. Null under the default treatment (nothing was credited, so the run stamps no share), which is why neither site renders on this deployment. =='

SELECT 'FIG-accounting-012, FIG-accounting-018' AS id,
       cr.over_delivery_treatment,
       cr.over_delivery_leave_behind,
       round(cr.over_delivery_leave_behind * 100, 0) AS share_pct
  FROM accounting_calculationrun cr
  JOIN parcels_parcel p ON p.id = cr.parcel_id
 WHERE p.parcel_number = 'MER-APN-019' AND cr.period = '2024-12';

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
