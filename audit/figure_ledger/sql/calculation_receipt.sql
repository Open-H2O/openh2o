-- FIG-accounting-002..015: the calculation page as a receipt
-- (templates/accounting/calculation_run_detail.html), 148-03, 2026-09-28.
--
-- THE PAGE. One question, answered first: this field was charged groundwater
-- nobody measured; where did that number come from? It renders only for a
-- run with residual_disposition = 'groundwater' (a well and no meter reading
-- for the month); a metered or no-well month gets a short page with no
-- figure on it. Fourteen floatformat sites, two decimals each (the run's own
-- four-decimal column rides in a title attribute, printed as the stored
-- Decimal, so it adds no site):
--   FIG-accounting-002  the headline, "Estimated pumping, <month>: N acre-feet"
--                       (headline_af = gw_extracted_af, or final_af on a run
--                       from before pumping was stamped; none such here)
--   FIG-accounting-003  Water the crop used (satellite estimate)   gross_et_af
--   FIG-accounting-004  minus rain the crop could use              effective_precip_af
--   FIG-accounting-005  minus canal water the crop could use       surface_water_af
--   FIG-accounting-006  = well water the crop used                 final_af
--   FIG-accounting-007  divided by N%                              gw_efficiency_pct
--   FIG-accounting-008  = pumped, charged to the groundwater budget gw_extracted_af
--   FIG-accounting-009  a zero month: "N acre-feet of the canal water was
--                       more than the crop needed"                 over_delivery_af
--   FIG-accounting-010  ... credited to this field (credited only) over_delivery_credited_af
--   FIG-accounting-011  ... stays in the basin (credited only)     over_delivery_left_af
--   FIG-accounting-012  ... (N%) (credited only)                   over_delivery_share_pct
--   FIG-accounting-013  the canal note: the district's delivery record
--                                                                  surface_delivered_af
--   FIG-accounting-014  the canal note: irrigation efficiency N%   irrigation_efficiency_pct
--   FIG-accounting-015  the note "The N%."                         gw_efficiency_pct
--
-- PINS.
--   Receipt   MER-APN-039 (parcel id 39), August 2026, calculation run id 3535:
--             a well month with no rain, a canal delivery and a remainder.
--             Renders FIG-002..008 and 013..015; 009..012 need a zero month.
--   Zero month MER-APN-016 (parcel id 16), December 2024, run id 3971's
--             neighbour on the same page family: rain alone equalled the crop's
--             water use, so the canal water the crop could use is all beyond
--             it. Renders FIG-003..006, 009, 013, 014; the deployment runs the
--             default treatment (not credited), so 010..012 do not render here
--             and are proven with hand numbers in tests/test_calculation_receipt.py.
--
-- DERIVED FIGURES, transcribed from accounting/views.py::_receipt_context:
--   gw_efficiency_pct         = final_af / gw_extracted_af * 100 (None on a zero month)
--   irrigation_efficiency_pct = surface_efficiency * 100
--   over_delivery_left_af     = over_delivery_af - over_delivery_credited_af
--   over_delivery_share_pct   = over_delivery_leave_behind * 100
--
-- INDEPENDENCE. This file names tables and columns only. It imports nothing,
-- calls no project function, and runs on the host through
-- audit/figure_ledger/run_sql.sh, outside the process that owns the
-- object-relational mapper. Block A rebuilds the crop and rain figures from
-- the RAW satellite and weather rows (datasync_openetcache) and the parcel's
-- acreage through the TR-21 formula transcribed in accounting_detail.sql
-- (304.8 mm-acres per acre-foot; SF = 1.000674 at D = 3.0 inches), never
-- reading gross_et_af or effective_precip_af, so it can disagree with the
-- engine. Block B rebuilds the canal, well-water and pumped figures from
-- other columns than the ones they are printed from: delivered times the
-- stored efficiency, the delivery against the field's own surface_diversion
-- ledger row (a different table), the remainder from the three figures above
-- it floored at zero, and pumped from the remainder and the deployment's
-- core_siteconfig.groundwater_efficiency. Block C does the same for the zero
-- month and the canal water beyond what the crop could use.

\set ON_ERROR_STOP on

\echo ''
\echo '== A. FIG-accounting-003, 004 on both pins: crop water use and rain the crop could use, rebuilt from the raw satellite and weather rows and the acreage, beside the stored columns. Expect 45.0477 / 0.0000 (039 2026-08) and 8.2132 / 8.2132 (016 2024-12). =='

CREATE TEMP VIEW _raw_monthly AS
SELECT c.parcel_id,
       (e.value->>'date') AS month_label,
       MAX((e.value->>'et')::numeric) FILTER
           (WHERE c.variable = 'ET' AND c.model_name = 'Ensemble')    AS et_mm,
       MAX((e.value->>'precip')::numeric) FILTER
           (WHERE c.variable = 'precip' AND c.model_name = 'GRIDMET') AS precip_mm
  FROM datasync_openetcache c,
       LATERAL jsonb_array_elements(c.et_data) AS e(value)
 WHERE c.variable IN ('ET', 'precip')
 GROUP BY c.parcel_id, e.value->>'date';

CREATE TEMP VIEW _raw_derived AS
SELECT rm.parcel_id, rm.month_label, p.parcel_number, rm.et_mm, rm.precip_mm, p.area_acres,
       rm.et_mm * p.area_acres / 304.8 AS gross_af,
       GREATEST(
         LEAST(
           (1.000674
             * (1.25 * power(rm.precip_mm::double precision, 0.824) - 2.93)
             * power(10::double precision, 0.000955 * rm.et_mm::double precision))::numeric,
           rm.precip_mm, rm.et_mm),
         0) * p.area_acres / 304.8 AS pe_af
  FROM _raw_monthly rm
  JOIN parcels_parcel p ON p.id = rm.parcel_id
 WHERE rm.et_mm IS NOT NULL AND rm.precip_mm IS NOT NULL;

SELECT rd.parcel_number, rd.month_label,
       round(rd.gross_af, 4) AS "FIG-003 rebuilt gross_af",
       round(cr.gross_et_af, 4) AS stored_gross_et_af,
       round(rd.pe_af, 4) AS "FIG-004 rebuilt rain_af",
       round(cr.effective_precip_af, 4) AS stored_effective_precip_af
  FROM _raw_derived rd
  JOIN accounting_calculationrun cr ON cr.parcel_id = rd.parcel_id AND cr.period = rd.month_label
 WHERE (rd.parcel_number, rd.month_label) IN (('MER-APN-039', '2026-08'), ('MER-APN-016', '2024-12'))
 ORDER BY rd.parcel_number;

\echo ''
\echo '== B. The receipt, MER-APN-039 2026-08. FIG-002/008 pumped, 005 canal, 006 well water, 007/015 the divisor percent, 013 delivered, 014 the efficiency percent. Each rebuilt from other columns than the one it prints. Expect delivered 53.6978 = the ledger row; canal 40.2734; well water 4.7743; pumped 5.9679; 80; 75. =='

SELECT p.parcel_number, cr.period, cr.residual_disposition,
       round(cr.surface_delivered_af, 4)                                 AS "FIG-013 stored delivered_af",
       round(abs(COALESCE((SELECT SUM(pl.amount_acre_feet) FROM parcels_parcelledger pl
                             WHERE pl.parcel_id = cr.parcel_id
                               AND pl.source_type = 'surface_diversion'
                               AND pl.effective_date >= cr.period_start
                               AND pl.effective_date < (cr.period_start + interval '1 month')::date), 0)), 4)
                                                                         AS "FIG-013 ledger surface_diversion row",
       round(cr.surface_efficiency * 100, 0)                             AS "FIG-014 irrigation_efficiency_pct",
       round(cr.surface_delivered_af * cr.surface_efficiency, 4)         AS "FIG-005 rebuilt canal_af",
       round(cr.surface_water_af, 4)                                     AS stored_surface_water_af,
       round(GREATEST(cr.gross_et_af - cr.effective_precip_af - cr.surface_water_af, 0), 4)
                                                                         AS "FIG-006 rebuilt well_water_af",
       round(cr.final_af, 4)                                             AS stored_final_af,
       round(cr.final_af / sc.groundwater_efficiency, 4)                 AS "FIG-002/008 rebuilt pumped_af",
       round(cr.gw_extracted_af, 4)                                      AS stored_gw_extracted_af,
       round(cr.final_af / cr.gw_extracted_af * 100, 0)                  AS "FIG-007/015 gw_efficiency_pct",
       round(sc.groundwater_efficiency * 100, 0)                         AS siteconfig_groundwater_efficiency_pct
  FROM accounting_calculationrun cr
  JOIN parcels_parcel p ON p.id = cr.parcel_id
 CROSS JOIN (SELECT groundwater_efficiency FROM core_siteconfig LIMIT 1) sc
 WHERE p.parcel_number = 'MER-APN-039' AND cr.period = '2026-08';

\echo ''
\echo '== C. The zero month, MER-APN-016 2024-12. FIG-009 the canal water beyond what the crop could use, rebuilt as delivered x efficiency minus max(crop use minus rain, 0); FIG-010..012 null under the default treatment (not rendered). Expect canal 4.2028, well water 0.0000, over 4.2028, treatment not_credited. =='

SELECT p.parcel_number, cr.period, cr.residual_disposition,
       round(cr.surface_delivered_af, 4)                                 AS "FIG-013 delivered_af",
       round(cr.surface_efficiency * 100, 0)                             AS "FIG-014 irrigation_efficiency_pct",
       round(cr.surface_delivered_af * cr.surface_efficiency, 4)         AS "FIG-005 rebuilt canal_af",
       round(GREATEST(cr.gross_et_af - cr.effective_precip_af - cr.surface_water_af, 0), 4)
                                                                         AS "FIG-006 rebuilt well_water_af",
       round(cr.final_af, 4)                                             AS stored_final_af,
       round(cr.surface_delivered_af * cr.surface_efficiency
             - GREATEST(cr.gross_et_af - cr.effective_precip_af, 0), 4)  AS "FIG-009 rebuilt over_delivery_af",
       round(cr.over_delivery_af, 4)                                     AS stored_over_delivery_af,
       cr.over_delivery_treatment,
       cr.over_delivery_credited_af                                      AS "FIG-010 credited (null: not rendered)",
       cr.over_delivery_af - cr.over_delivery_credited_af                AS "FIG-011 left (null: not rendered)",
       round(cr.over_delivery_leave_behind * 100, 0)                     AS "FIG-012 share_pct (null: not rendered)",
       cr.gw_extracted_af                                                AS "FIG-002 pumped (0.0000 renders as the headline)"
  FROM accounting_calculationrun cr
  JOIN parcels_parcel p ON p.id = cr.parcel_id
 WHERE p.parcel_number = 'MER-APN-016' AND cr.period = '2024-12';

\echo ''
\echo '== D. Who gets the receipt: the disposition mix, so the short page (no figure) is the answer on 1,385 of 1,824 months and the receipt on 439. =='

SELECT residual_disposition, count(*) FROM accounting_calculationrun GROUP BY 1 ORDER BY 1;
