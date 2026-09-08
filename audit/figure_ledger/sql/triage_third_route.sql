-- FIG-geography-002, FIG-geography-003 (ISS-154)
-- FIG-accounting-053, FIG-accounting-054, FIG-accounting-055 (ISS-155)
-- FIG-accounting-022 (ISS-156)
-- FIG-parcels-016, FIG-parcels-017, FIG-accounting-005..007 (UNVERIFIED reasons)
--
-- THIRD-ROUTE RE-DERIVATION for audit/figure_ledger/triage.md.
--
-- WHY A THIRD ROUTE. The ledger already recomputed each of these figures once,
-- independently of the application code. That is enough to catch an arithmetic
-- mistake and not enough to catch a wrong idea: a second derivation that walks
-- the same identity as the first shares the first one's assumptions. Roughly a
-- quarter of the findings in an audit like this are the auditor's error, so a
-- finding does not become an ISS-### number until a THIRD derivation, starting
-- somewhere neither of the first two started, agrees with it.
--
-- What "somewhere else" means, block by block:
--   T1  partitions by source_type and runs BOTH years and ALL THREE districts,
--       where the ledger pinned one cell of one year. Verdano Island takes no
--       canal water, so it is the negative control: if the fault appeared there
--       too, the query would be wrong rather than the screen.
--   T2  drops the account-and-zone membership union entirely and sweeps every
--       row in the period. If the two screens were reading different row sets,
--       this pass would disagree with both of them.
--   T3  groups the allocation footer by water type instead of summing it, so
--       the mixture is visible in the output rather than asserted in prose.
--   T4  and T5 test the two "cannot be reached" claims by counting the thing
--       that would have to exist for the branch to render.
--
-- INDEPENDENCE. This file names tables and columns only. It imports nothing,
-- calls no project function, and runs on the host through
-- audit/figure_ledger/run_sql.sh, outside the process that owns the
-- object-relational mapper.
--
-- Selection rules transcribed from source, read 2026-09-05:
--   geography/views.py:196-201   where the allocation's water type code
--       upper-cases to 'GW', "used" is the ABSOLUTE VALUE OF THE SUM OF EVERY
--       NEGATIVE ledger row, whatever its source type, and the screen labels the
--       column "pumped". No source-type filter is applied. Surface canal
--       deliveries are stored negative, so they fall inside it.
--   geography/views.py:217-223   remaining = allocation - used.
--   accounting/services.py:767   runoff is the literal Decimal zero, a
--       bookkeeping boundary, because the platform models no surface hydrology.
--   accounting/services.py:581   REALISTIC_RESIDUAL_BAND = 0.25 of gross ET.
--
-- ROUNDING, and a phantom it produced. The dashboard's supplies total is the
-- sum of three terms rounded ONCE, at the end. Rounding each term to two
-- decimals first gives 17,458.36 and a net of +1,249.08, a one-cent
-- disagreement with the screen that is the recomputation's own artifact. T2
-- therefore carries the unrounded components beside the rounded total.

\echo ''
\echo '== T1. ISS-154: the district Used column, decomposed by source type =='
\echo '   All three groundwater districts, both water years.'
\echo '   Verdano Island is the negative control: no canal water, so its two'
\echo '   remaining columns must be identical.'

WITH gw_plans AS (
    SELECT ap.zone_id,
           ap.reporting_period_id AS period_id,
           ap.allocation_acre_feet AS allocation,
           z.name AS district
      FROM accounting_allocationplan ap
      JOIN accounting_watertype wt ON wt.id = ap.water_type_id
      JOIN geography_zone z ON z.id = ap.zone_id
     WHERE upper(wt.code) = 'GW'
),
negative_rows AS (
    SELECT g.district, g.period_id, g.allocation,
           pl.source_type, pl.amount_acre_feet
      FROM gw_plans g
      JOIN geography_parcelzone pz ON pz.zone_id = g.zone_id
      JOIN parcels_parcelledger pl
        ON pl.parcel_id = pz.parcel_id
       AND pl.reporting_period_id = g.period_id
     WHERE pl.amount_acre_feet < 0
)
SELECT district,
       rp.name AS water_year,
       round(max(allocation), 2) AS allocation_af,
       round(abs(sum(amount_acre_feet)), 2) AS used_as_screened,
       round(abs(COALESCE(sum(amount_acre_feet)
             FILTER (WHERE source_type = 'surface_diversion'), 0)), 2)
           AS canal_water_inside_it,
       round(abs(COALESCE(sum(amount_acre_feet)
             FILTER (WHERE source_type <> 'surface_diversion'), 0)), 2)
           AS groundwater_alone,
       round(max(allocation) - abs(sum(amount_acre_feet)), 2)
           AS remaining_as_screened,
       round(max(allocation) - abs(COALESCE(sum(amount_acre_feet)
             FILTER (WHERE source_type <> 'surface_diversion'), 0)), 2)
           AS remaining_groundwater_alone
  FROM negative_rows nr
  JOIN accounting_reportingperiod rp ON rp.id = nr.period_id
 GROUP BY district, rp.name, nr.period_id
 ORDER BY district, nr.period_id;

\echo ''
\echo '== T2. ISS-155: the use ledger footer and the dashboard, same 1,130 rows =='
\echo '   Whole-population sweep. No account join, no zone join, no membership'
\echo '   union, no suppression ladder.'

WITH led AS (
    SELECT * FROM parcels_parcelledger WHERE reporting_period_id = 2
),
runs AS (
    SELECT sum(cr.gross_et_af) AS gross_et,
           sum(cr.effective_precip_af) AS effective_rainfall
      FROM accounting_calculationrun cr
      JOIN accounting_reportingperiod rp ON rp.id = 2
     WHERE cr.period_start >= date_trunc('month', rp.start_date)::date
       AND cr.period_start <= rp.end_date
),
supply AS (
    SELECT abs(sum(amount_acre_feet)
               FILTER (WHERE source_type = 'surface_diversion')) AS canal,
           abs(sum(amount_acre_feet)
               FILTER (WHERE amount_acre_feet < 0
                         AND source_type <> 'surface_diversion')) AS groundwater
      FROM led
)
SELECT (SELECT count(*) FROM led) AS rows_in_period,
       (SELECT count(DISTINCT parcel_id) FROM led) AS parcels,
       round((SELECT sum(amount_acre_feet) FROM led
               WHERE amount_acre_feet > 0), 2) AS ledger_credits,
       round((SELECT sum(amount_acre_feet) FROM led
               WHERE amount_acre_feet < 0), 2) AS ledger_debits,
       round((SELECT sum(amount_acre_feet) FROM led), 2) AS ledger_footer_net,
       supply.canal AS canal_unrounded,
       supply.groundwater AS groundwater_unrounded,
       runs.effective_rainfall AS rainfall_unrounded,
       round(supply.canal + supply.groundwater + runs.effective_rainfall, 2)
           AS dashboard_supplies,
       round(runs.gross_et, 2) AS gross_evapotranspiration,
       round(supply.canal + supply.groundwater + runs.effective_rainfall
             - runs.gross_et, 2) AS dashboard_net_vs_supply
  FROM supply, runs;

\echo ''
\echo '== T3. ISS-156: the allocations footer, partitioned by water type =='
\echo '   Both years, so the mixture is not an artifact of one period.'

SELECT rp.name AS water_year,
       count(*) FILTER (WHERE upper(wt.code) = 'SW') AS surface_plans,
       round(COALESCE(sum(ap.allocation_acre_feet)
             FILTER (WHERE upper(wt.code) = 'SW'), 0), 2) AS surface_af,
       count(*) FILTER (WHERE upper(wt.code) = 'GW') AS groundwater_plans,
       round(COALESCE(sum(ap.allocation_acre_feet)
             FILTER (WHERE upper(wt.code) = 'GW'), 0), 2) AS groundwater_af,
       round(sum(ap.allocation_acre_feet), 2) AS footer_as_printed
  FROM accounting_allocationplan ap
  JOIN accounting_watertype wt ON wt.id = ap.water_type_id
  JOIN accounting_reportingperiod rp ON rp.id = ap.reporting_period_id
 GROUP BY rp.name, ap.reporting_period_id
 ORDER BY ap.reporting_period_id;

\echo ''
\echo '   The OTHER quantity the word "allocation" names, same years:'
\echo '   per-parcel ledger entries rather than zone plans.'

SELECT rp.name AS water_year,
       count(*) AS entries,
       round(sum(pl.amount_acre_feet), 2) AS ledger_allocation_af
  FROM parcels_parcelledger pl
  JOIN accounting_reportingperiod rp ON rp.id = pl.reporting_period_id
 WHERE pl.source_type = 'allocation'
 GROUP BY rp.name, pl.reporting_period_id
 ORDER BY pl.reporting_period_id;

\echo ''
\echo '== T4. FIG-parcels-016/017: is the "no calculation runs" branch reachable? =='
\echo '   A parcel-year with zero runs would render it. Expect zero rows out.'

SELECT rp.name AS water_year, count(*) AS parcels_with_no_runs
  FROM parcels_parcel pa
 CROSS JOIN accounting_reportingperiod rp
 WHERE pa.parcel_number LIKE 'MER-APN-%'
   AND NOT EXISTS (
       SELECT 1 FROM accounting_calculationrun cr
        WHERE cr.parcel_id = pa.id
          AND cr.period_start >= date_trunc('month', rp.start_date)::date
          AND cr.period_start <= rp.end_date)
 GROUP BY rp.name, rp.id
 ORDER BY rp.id;

\echo ''
\echo '== T5. FIG-accounting-005/006/007: does anything carry a deposit or a draw? =='
\echo '   The banked-water block reads the runs. The credit tables are checked'
\echo '   too, because a credit row the block cannot see would still be water.'

SELECT count(*) AS calculation_runs,
       count(*) FILTER (WHERE banked_af <> 0) AS runs_with_a_deposit,
       count(*) FILTER (WHERE drawn_af <> 0) AS runs_with_a_draw,
       (SELECT count(*) FROM accounting_watercredit) AS credit_rows,
       (SELECT count(*) FROM accounting_watercredit
         WHERE amount_af <> 0) AS credit_rows_carrying_water,
       (SELECT count(*) FROM accounting_watercreditdraw) AS draw_rows
  FROM accounting_calculationrun;
