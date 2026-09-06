-- FIG-parcels-001 .. FIG-parcels-015 (the parcel detail pane's balance card)
--
-- THE OUT-OF-BAND PARCEL REVIEW: every parcel whose water balance sits outside
-- the acceptance band, for BOTH water years, with each supply and output term
-- beside it so a reader can see WHY rather than take the flag on trust.
--
-- THE BAND IS NOT A DEFECT THRESHOLD. Brent set the bar on 2026-06-04 (ISS-057):
-- real water accounting never closes to zero. Deficit irrigation in drought,
-- salt-flush and operational flooding, shallow-groundwater and stream-adjacent
-- rootzone supplement, and conveyance loss all make real residuals nonzero in
-- both directions. The bar is "small, realistic, and never alarming". A parcel
-- outside the band therefore needs a REASON, and "the demonstration seed sized
-- this one badly" and "the arithmetic is wrong" are different findings.
--
-- INDEPENDENCE. This file names tables and columns only. It imports nothing,
-- calls no project function, and runs on the host through
-- audit/figure_ledger/run_sql.sh, outside the process that owns the
-- object-relational mapper.
--
-- Selection rules transcribed from source, read 2026-09-05:
--   accounting/services.py:581   REALISTIC_RESIDUAL_BAND = Decimal("0.25"),
--       a fraction of GROSS evapotranspiration, not of supplies.
--   accounting/services.py:571   MASS_BALANCE_TOLERANCE = Decimal("0.01"),
--       the width of the "Balanced" band around zero.
--   accounting/services.py:702   the mass-balance identity:
--       surface + precip + gw_recovered = et + recharge + runoff + delta_storage
--   accounting/services.py:767   runoff is the literal Decimal zero, a
--       bookkeeping boundary; the platform models no surface hydrology.
--   accounting/services.py:762   delta_storage is SUM(banked_af - drawn_af).
--   accounting/services.py:600, :765  the Recharge output is read off each run's
--       stored breakdown: the FIRST step whose step_type is 'clamp_floor',
--       field detail.incidental_recharge_af, defaulting to 0 when absent.
--   accounting/services.py:377   an et_estimate row is suppressed where a
--       calculated row exists for the same (parcel, effective_date), or a
--       meter_reading row exists for the same (parcel, first-of-that-month).
--
-- THE TWO QUANTITIES THE PANE PRINTS, and the whole of ISS-148:
--   card 3        = supplies - gross ET
--   residual      = supplies - (gross ET + recharge + runoff + delta_storage)
-- They differ by exactly (recharge + delta_storage). On this data delta_storage
-- is zero on all 152 parcel-years, so the gap is incidental recharge alone.
--
-- CROSS-CHECK BEFORE TRUSTING ANYTHING ELSE. Four rows are already known from
-- the 2026-09-05 measurement and are reproduced by block B below. If they do not
-- come back at these figures the query is wrong and every row after it is too:
--   MER-APN-011  WY 2024-2025  gross ET 370.26  net CU 307.40  supplies 224.64
--                              card 3 -145.62   residual -181.57
--   MER-APN-002  WY 2024-2025  gross ET 564.23  net CU 485.77  supplies 845.18
--                              card 3  280.94   residual  280.94
--
-- EXPECTED COUNTS, from the same measurement: 10 out-of-band parcels in
-- WY 2024-2025 and 11 in WY 2025-2026.

\set ON_ERROR_STOP on

CREATE TEMP VIEW _periods AS
SELECT rp.id AS period_id,
       rp.name AS water_year,
       date_trunc('month', rp.start_date)::date AS first_month,
       rp.end_date
  FROM accounting_reportingperiod rp;

CREATE TEMP VIEW _ledger AS
SELECT pl.parcel_id, pl.reporting_period_id AS period_id, pl.effective_date,
       pl.source_type, pl.amount_acre_feet
  FROM parcels_parcelledger pl
 WHERE pl.reporting_period_id IS NOT NULL;

CREATE TEMP VIEW _suppression AS
SELECT DISTINCT parcel_id, period_id, effective_date AS key_date
  FROM _ledger WHERE source_type = 'calculated'
UNION
SELECT DISTINCT parcel_id, period_id,
       date_trunc('month', effective_date)::date
  FROM _ledger WHERE source_type = 'meter_reading';

CREATE TEMP VIEW _billable AS
SELECT l.* FROM _ledger l
 WHERE NOT (
    l.source_type = 'et_estimate'
    AND EXISTS (SELECT 1 FROM _suppression s
                 WHERE s.parcel_id = l.parcel_id
                   AND s.period_id = l.period_id
                   AND s.key_date = l.effective_date));

CREATE TEMP VIEW _balance AS
WITH led AS (
    SELECT p.id AS parcel_id, rp.period_id,
           abs(COALESCE(SUM(b.amount_acre_feet)
               FILTER (WHERE b.source_type = 'surface_diversion'), 0)) AS canal,
           abs(COALESCE(SUM(b.amount_acre_feet)
               FILTER (WHERE b.amount_acre_feet < 0
                         AND b.source_type <> 'surface_diversion'), 0))
               AS groundwater
      FROM parcels_parcel p
     CROSS JOIN _periods rp
      LEFT JOIN _billable b ON b.parcel_id = p.id AND b.period_id = rp.period_id
     GROUP BY 1, 2
),
runs AS (
    SELECT p.id AS parcel_id, rp.period_id,
           COALESCE(SUM(cr.gross_et_af), 0)             AS gross_et,
           COALESCE(SUM(cr.net_consumptive_use_af), 0)  AS net_cu,
           COALESCE(SUM(cr.effective_precip_af), 0)     AS rainfall,
           COALESCE(SUM(cr.banked_af - cr.drawn_af), 0) AS net_banked,
           COALESCE(SUM(
             (SELECT (step->'detail'->>'incidental_recharge_af')::numeric
                FROM jsonb_array_elements(cr.breakdown) step
               WHERE step->>'step_type' = 'clamp_floor'
               LIMIT 1)), 0)                            AS recharge,
           COUNT(cr.id)                                 AS run_count
      FROM parcels_parcel p
     CROSS JOIN _periods rp
      LEFT JOIN accounting_calculationrun cr
             ON cr.parcel_id = p.id
            AND cr.period_start >= rp.first_month
            AND cr.period_start <= rp.end_date
     GROUP BY 1, 2
)
SELECT pa.parcel_number,
       pa.owner_name,
       pa.area_acres,
       rp.water_year,
       l.period_id,
       l.canal, l.groundwater, r.rainfall,
       r.gross_et, r.net_cu, r.recharge, r.net_banked, r.run_count,
       (l.canal + l.groundwater + r.rainfall)                    AS supplies,
       (l.canal + l.groundwater + r.rainfall) - r.gross_et       AS card_three,
       (l.canal + l.groundwater + r.rainfall)
         - (r.gross_et + r.recharge + 0 + r.net_banked)          AS residual
  FROM led l
  JOIN runs r ON r.parcel_id = l.parcel_id AND r.period_id = l.period_id
  JOIN parcels_parcel pa ON pa.id = l.parcel_id
  JOIN _periods rp ON rp.period_id = l.period_id
 WHERE pa.parcel_number LIKE 'MER-APN-%';

\echo ''
\echo '== A. The counts. Expect 10 out-of-band for WY 2024-2025, 11 for WY 2025-2026. =='
\echo '   Out of band means abs(residual) > 0.25 * gross ET, the bar at'
\echo '   accounting/services.py:581. Parcels with no runs are excluded, because a'
\echo '   parcel with no evapotranspiration has no band to be outside of.'

SELECT water_year,
       count(*) AS parcels_with_runs,
       count(*) FILTER (WHERE abs(residual) > 0.25 * gross_et) AS outside_the_band,
       count(*) FILTER (WHERE abs(residual) > 0.25 * gross_et
                          AND residual > 0) AS large_surplus,
       count(*) FILTER (WHERE abs(residual) > 0.25 * gross_et
                          AND residual < 0) AS large_deficit,
       count(*) FILTER (WHERE (card_three >= 0) <> (residual >= 0))
           AS card_and_residual_disagree_in_sign,
       count(*) FILTER (WHERE round(card_three, 2) <> round(residual, 2))
           AS printed_numbers_differ
  FROM _balance
 WHERE run_count > 0 AND gross_et > 0
 GROUP BY water_year, period_id
 ORDER BY period_id;

\echo ''
\echo '== B. The four known worked rows. These must reproduce to the cent. =='

SELECT parcel_number, water_year,
       round(gross_et, 2)   AS gross_et,
       round(net_cu, 2)     AS net_consumptive_use,
       round(supplies, 2)   AS supplies,
       round(card_three, 2) AS card_three,
       round(residual, 2)   AS residual,
       round(recharge, 2)   AS incidental_recharge,
       round(net_banked, 2) AS net_banked
  FROM _balance
 WHERE parcel_number IN ('MER-APN-011', 'MER-APN-002')
 ORDER BY parcel_number, period_id;

\echo ''
\echo '== C. Every out-of-band parcel-year, with each term beside it. =='
\echo '   band_af is 0.25 * gross ET, the width the residual had to exceed.'
\echo '   over_by_af is abs(residual) - band_af, how far outside it landed.'

SELECT water_year,
       parcel_number,
       owner_name,
       round(area_acres, 2)   AS acres,
       round(gross_et, 2)     AS gross_et,
       round(net_cu, 2)       AS net_consumptive_use,
       round(canal, 2)        AS canal_delivery,
       round(groundwater, 2)  AS groundwater,
       round(rainfall, 2)     AS effective_rainfall,
       round(supplies, 2)     AS supplies,
       round(recharge, 2)     AS incidental_recharge,
       round(net_banked, 2)   AS net_banked,
       round(card_three, 2)   AS card_three,
       round(residual, 2)     AS residual,
       round(0.25 * gross_et, 2)                  AS band_af,
       round(abs(residual) - 0.25 * gross_et, 2)  AS over_by_af,
       round(100 * residual / NULLIF(gross_et, 0), 1) AS residual_pct_of_gross_et,
       CASE WHEN residual > 0 THEN 'surplus' ELSE 'deficit' END AS direction
  FROM _balance
 WHERE run_count > 0 AND gross_et > 0
   AND abs(residual) > 0.25 * gross_et
 ORDER BY period_id, residual_pct_of_gross_et;

\echo ''
\echo '== D. Is the gap between the two balances one term, everywhere? =='
\echo '   residual = card_three - recharge - net_banked. A violation would mean'
\echo '   the identity at accounting/services.py:702 does not hold on this data.'

SELECT count(*) AS parcel_years_checked,
       count(*) FILTER (WHERE round(residual, 6)
                            <> round(card_three - recharge - net_banked, 6))
           AS identity_violations,
       count(*) FILTER (WHERE net_banked <> 0) AS parcel_years_with_banking,
       count(*) FILTER (WHERE recharge <> 0)   AS parcel_years_with_recharge
  FROM _balance;

\echo ''
\echo '== E. The curtailment archetype, named rather than inferred. =='
\echo '   A parcel served ONLY by canal water is exposed to a curtailment in a way'
\echo '   a parcel that can pump is not. This block asks which out-of-band parcels'
\echo '   are surface-only, so the review can say "curtailed" with evidence.'

SELECT water_year,
       parcel_number,
       round(canal, 2) AS canal_delivery,
       round(groundwater, 2) AS groundwater,
       CASE WHEN groundwater = 0 AND canal > 0 THEN 'surface only'
            WHEN canal = 0 AND groundwater > 0 THEN 'groundwater only'
            WHEN canal = 0 AND groundwater = 0 THEN 'no delivered supply'
            ELSE 'both sources' END AS supply_shape,
       round(residual, 2) AS residual,
       round(100 * residual / NULLIF(gross_et, 0), 1) AS residual_pct_of_gross_et
  FROM _balance
 WHERE run_count > 0 AND gross_et > 0
   AND abs(residual) > 0.25 * gross_et
 ORDER BY period_id, supply_shape, parcel_number;
