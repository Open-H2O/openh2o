-- FIG-help-001..010 -- "Where this field's water came from", the worked
-- field-month table in templates/help/partials/_the_subtraction.html,
-- included with no extra context by both help/water_balances.html ("The
-- short version") and help/methods.html ("The short version").
--
-- THE FIGURE. Ten floatformat sites over one CalculationRun, chosen by
-- accounting/services.py's example_field_month, added by 148-03 and reused
-- by 148-04, so the two pages can never show two different examples for the
-- same deployment.
--
-- SELECTION RULE, transcribed from source, read 2026-09-28
-- (accounting/services.py:1547-1594, the example_field_month function):
--   this_month = the first of the current calendar month
--   candidates = CalculationRun rows with
--       residual_disposition = 'groundwater'
--       AND surface_delivered_af > 0
--       AND period_start < this_month
--     ordered by period_start DESC, parcel.parcel_number ASC
--   prefer the first candidate with final_af >= 0.01 (a division line with a
--     figure in it rather than an arithmetically-correct-but-teaches-nothing
--     0.00); fall back to the first candidate of any final_af; fall back
--     further to the most recent groundwater-disposition run of any kind.
-- Block A below reproduces this filter directly; if it does not land on the
-- same run the two blocks below are recomputing the wrong figure-month.
--
-- DERIVED FIGURES.
--   irrigation_efficiency_pct = surface_efficiency * 100 (services.py:1630-1632)
--   gw_efficiency_pct: when gw_extracted_af is nonzero, final_af / gw_extracted_af
--     quantized to 4 places, times 100 (services.py:1638-1644, the same
--     division accounting/views.py:calculation_run_detail's own
--     gw_efficiency_applied performs on this run's own two stored columns).
--     Nothing here reads SiteConfig; on this run gw_extracted_af is nonzero so
--     the live-setting fallback branch never fires.
--   over_delivery_af is a stored column, read as-is; the template renders the
--     "Canal water beyond what the crop could use" row only when it is > 0
--     (DESIGN.md rule 8), and it is 0.0000 on the pinned run.
--
-- INDEPENDENCE. This file names tables and columns only. It imports nothing,
-- calls no project function, and runs on the host through
-- audit/figure_ledger/run_sql.sh, outside the process that owns the
-- object-relational mapper.

\set ON_ERROR_STOP on

\echo ''
\echo '== A. Selection rule, reproduced directly: residual_disposition = groundwater, surface_delivered_af > 0, period_start before this month, final_af >= 0.01, ordered -period_start then parcel_number. Expect MER-APN-032, 2026-08-01 on top. =='

CREATE TEMP VIEW _candidates AS
SELECT cr.id, p.parcel_number, cr.period_start, cr.final_af
  FROM accounting_calculationrun cr
  JOIN parcels_parcel p ON p.id = cr.parcel_id
 WHERE cr.residual_disposition = 'groundwater'
   AND cr.surface_delivered_af > 0
   AND cr.period_start < date_trunc('month', current_date)::date;

SELECT id, parcel_number, period_start, final_af
  FROM _candidates
 WHERE final_af >= 0.01
 ORDER BY period_start DESC, parcel_number
 LIMIT 1;

\echo ''
\echo '== B. FIG-help-001..004, 007..009: the six raw figures, restated directly off that run. =='

SELECT cr.id,
       p.parcel_number,
       cr.period_start,
       round(cr.gross_et_af, 4)         AS "FIG-help-001 crop_water_use_af",
       round(cr.effective_precip_af, 4) AS "FIG-help-002 rain_af",
       round(cr.surface_delivered_af,4) AS "FIG-help-003 delivered_af",
       round(cr.surface_water_af, 4)    AS "FIG-help-004/006 canal_water_af",
       round(cr.final_af, 4)            AS "FIG-help-007 groundwater_consumed_af",
       round(cr.gw_extracted_af, 4)     AS "FIG-help-009 groundwater_extracted_af",
       round(cr.over_delivery_af, 4)    AS "FIG-help-008 over_delivery_af (not rendered, is 0)"
  FROM accounting_calculationrun cr
  JOIN parcels_parcel p ON p.id = cr.parcel_id
 WHERE p.parcel_number = 'MER-APN-032'
   AND cr.period_start = '2026-08-01';

\echo ''
\echo '== C. FIG-help-005: irrigation efficiency percent, surface_efficiency * 100. =='

SELECT round(cr.surface_efficiency * 100, 0) AS "FIG-help-005 irrigation_efficiency_pct"
  FROM accounting_calculationrun cr
  JOIN parcels_parcel p ON p.id = cr.parcel_id
 WHERE p.parcel_number = 'MER-APN-032'
   AND cr.period_start = '2026-08-01';

\echo ''
\echo '== D. FIG-help-010: groundwater efficiency percent, final_af / gw_extracted_af (quantized to 4 places, as services.py does), times 100. =='

SELECT round(round(cr.final_af / cr.gw_extracted_af, 4) * 100, 0)
         AS "FIG-help-010 gw_efficiency_pct"
  FROM accounting_calculationrun cr
  JOIN parcels_parcel p ON p.id = cr.parcel_id
 WHERE p.parcel_number = 'MER-APN-032'
   AND cr.period_start = '2026-08-01';
