-- FIG-accounting-043, FIG-accounting-044, FIG-accounting-045 — the zone table's
-- GW allocation / Carried fwd / GW remaining, here for EVERY zone (the ledger
-- pins Halvern Irrigation-Urban GSA; accounting_dashboard.sql is the pinned row).
--
-- zone_budget_basis — the three GSA groundwater budgets against groundwater use,
-- both water years, sixteen rows (three GSA zones + five district zones × two
-- periods; the surface service areas ride along so the file is the whole zone
-- table, and their allocation is the surface plan, not a groundwater one).
--
-- Written by Plan 136-02 as the BEFORE measurement for the re-size of the GSA
-- sustainable-yield rates, and kept as the recomputation for the dashboard's
-- zone table under the option-A basis (136-01): GW remaining = groundwater
-- allocation (plus carry-over) minus groundwater use.
--
-- INDEPENDENCE. Tables and columns only. Runs on the host through
-- audit/figure_ledger/run_sql.sh, outside the process that owns the ORM.
-- Selection rules transcribed from source (read 2026-09-06):
--   accounting/services.py:472  groundwater use = abs(SUM(amount)) over
--       NEGATIVE rows whose source_type <> 'surface_diversion'.
--   accounting/services.py:864  surface delivered = abs(SUM(amount)) over
--       'surface_diversion' rows.
--   accounting/services.py:377  an et_estimate row is suppressed where a
--       calculated row (same date) or a meter_reading row (same month) exists.
--   accounting/services.py:617  a CalculationRun belongs to a period when its
--       period_start falls between the first of the opening month and the end
--       date. accounting_calculationrun carries a period string and a
--       period_start date, no period FK.
--   accounting/services.py:926  a zone's parcels are its ParcelZone rows;
--       SELECT DISTINCT so a parcel listed in a zone twice counts once.
--   accounting/carryover_math.py:51  a water year is named by the year it ends in.
--   core/management/commands/seed_merced_ledgers.py  the GSA plan is
--       max(500, acres × rate) over MER- parcels in the zone; acres here are
--       summed the same way, DISTINCT (zone, parcel).

\set ON_ERROR_STOP on

WITH period AS (
    SELECT rp.id, rp.name, rp.start_date, rp.end_date,
           date_trunc('month', rp.start_date)::date AS first_month,
           (CASE WHEN EXTRACT(MONTH FROM rp.end_date) >= 10
                 THEN EXTRACT(YEAR FROM rp.end_date) + 1
                 ELSE EXTRACT(YEAR FROM rp.end_date) END)::int AS water_year
      FROM accounting_reportingperiod rp
),
membership AS (
    SELECT DISTINCT pz.zone_id, pz.parcel_id
      FROM geography_parcelzone pz
),
zone_size AS (
    SELECT m.zone_id,
           COUNT(*) AS parcels,
           SUM(pr.area_acres) AS acres
      FROM membership m
      JOIN parcels_parcel pr ON pr.id = m.parcel_id
     GROUP BY m.zone_id
),
ledger AS (
    SELECT m.zone_id, p.id AS period_id, pl.parcel_id, pl.effective_date,
           pl.source_type, pl.amount_acre_feet
      FROM membership m
      JOIN parcels_parcelledger pl ON pl.parcel_id = m.parcel_id
      JOIN period p ON pl.reporting_period_id = p.id
),
suppression AS (
    SELECT DISTINCT zone_id, period_id, parcel_id, effective_date AS key_date
      FROM ledger WHERE source_type = 'calculated'
    UNION
    SELECT DISTINCT zone_id, period_id, parcel_id,
           date_trunc('month', effective_date)::date
      FROM ledger WHERE source_type = 'meter_reading'
),
billable AS (
    SELECT l.*
      FROM ledger l
     WHERE NOT (
        l.source_type = 'et_estimate'
        AND EXISTS (SELECT 1 FROM suppression s
                     WHERE s.zone_id = l.zone_id
                       AND s.period_id = l.period_id
                       AND s.parcel_id = l.parcel_id
                       AND s.key_date = l.effective_date)
     )
),
supplies AS (
    SELECT zone_id, period_id,
           abs(COALESCE(SUM(amount_acre_feet)
               FILTER (WHERE source_type = 'surface_diversion'), 0)) AS surface_delivered,
           abs(COALESCE(SUM(amount_acre_feet)
               FILTER (WHERE amount_acre_feet < 0
                         AND source_type <> 'surface_diversion'), 0)) AS groundwater_use
      FROM billable
     GROUP BY zone_id, period_id
),
runs AS (
    SELECT m.zone_id, p.id AS period_id,
           COALESCE(SUM(cr.gross_et_af), 0) AS gross_et,
           COALESCE(SUM(cr.net_consumptive_use_af), 0) AS net_cu
      FROM membership m
      JOIN accounting_calculationrun cr ON cr.parcel_id = m.parcel_id
      JOIN period p ON cr.period_start BETWEEN p.first_month AND p.end_date
     GROUP BY m.zone_id, p.id
),
plans AS (
    SELECT ap.zone_id, ap.reporting_period_id AS period_id,
           wt.code AS water_type, ap.allocation_acre_feet AS allocation, ap.notes
      FROM accounting_allocationplan ap
      JOIN accounting_watertype wt ON wt.id = ap.water_type_id
),
carry AS (
    SELECT ac.zone_id, p.id AS period_id, SUM(ac.amount_af) AS carryover
      FROM accounting_allocationcarryover ac
      JOIN period p ON ac.water_year = p.water_year
     GROUP BY ac.zone_id, p.id
)
SELECT z.name AS zone,
       p.name AS period,
       pl.water_type,
       round(pl.allocation, 2)                        AS allocation,
       round(zs.acres, 1)                             AS acres,
       zs.parcels,
       round(COALESCE(s.groundwater_use, 0), 2)       AS gw_use,
       round(COALESCE(s.surface_delivered, 0), 2)     AS surface_delivered,
       round(COALESCE(r.gross_et, 0), 2)              AS gross_et,
       round(COALESCE(r.net_cu, 0), 2)                AS net_cu,
       round(COALESCE(c.carryover, 0), 2)             AS carryover,
       -- the dashboard's GW remaining: groundwater plans only, else NULL (a dash)
       CASE WHEN upper(pl.water_type) = 'GW'
            THEN round(pl.allocation + COALESCE(c.carryover, 0)
                       - COALESCE(s.groundwater_use, 0), 2)
       END                                            AS gw_remaining,
       CASE WHEN upper(pl.water_type) = 'GW'
            THEN round(pl.allocation - COALESCE(s.groundwater_use, 0), 2)
       END                                            AS gw_remaining_no_carryover
  FROM plans pl
  JOIN geography_zone z ON z.id = pl.zone_id
  JOIN period p ON p.id = pl.period_id
  LEFT JOIN zone_size zs ON zs.zone_id = z.id
  LEFT JOIN supplies s ON s.zone_id = z.id AND s.period_id = p.id
  LEFT JOIN runs r ON r.zone_id = z.id AND r.period_id = p.id
  LEFT JOIN carry c ON c.zone_id = z.id AND c.period_id = p.id
 ORDER BY upper(pl.water_type) DESC, z.name, p.start_date;
