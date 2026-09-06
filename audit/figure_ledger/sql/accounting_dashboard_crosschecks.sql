-- FIG-accounting-023..028 — DIFFERENT-IDENTITY cross-checks on the three grand
-- totals and the three supply splits at the top of /accounting/dashboard/.
--
-- Why a second file. The recomputation in accounting_dashboard.sql restates the
-- chain the view performs, starting from stored rows: it can catch a coding
-- mistake but not a wrong idea. These checks start somewhere the view does not,
-- so they CAN disagree with it, and what they measure is the shape of the
-- population each figure covers rather than its arithmetic.
--
-- Same independence rule: tables and columns only, run on the host.
--
--   1. single_pass_*  — the panel's totals computed ONCE over the distinct union
--      of every active account's parcels, instead of account by account and
--      added up. These differ if any parcel belongs to two active accounts.
--   2. zone_side_*    — the same totals over every parcel that sits in a zone.
--      The panel counts only parcels attached to an ACTIVE account; the zone
--      table below it counts every parcel in a zone. The two describe
--      deliberately different populations (accounting/views.py:129-135), and a
--      reader comparing the panel to the column beneath it sees the gap.
--   3. coverage       — how many parcels each population actually holds.

\set ON_ERROR_STOP on

WITH period AS (
    SELECT rp.id, rp.start_date, rp.end_date,
           date_trunc('month', rp.start_date)::date AS first_month
      FROM accounting_reportingperiod rp WHERE rp.id = 2
),
account_parcels AS (
    SELECT DISTINCT wap.parcel_id
      FROM accounting_wateraccount wa
      JOIN accounting_wateraccountparcel wap ON wap.water_account_id = wa.id
     WHERE wa.status = 'active' AND wap.removed_date IS NULL
),
zone_parcels AS (
    SELECT DISTINCT parcel_id FROM geography_parcelzone
),
population AS (
    SELECT 'account_side'::text AS side, parcel_id FROM account_parcels
    UNION ALL
    SELECT 'zone_side'::text, parcel_id FROM zone_parcels
),
ledger AS (
    SELECT pop.side, pl.parcel_id, pl.effective_date, pl.source_type,
           pl.amount_acre_feet
      FROM population pop
      JOIN parcels_parcelledger pl ON pl.parcel_id = pop.parcel_id
      JOIN period p ON pl.reporting_period_id = p.id
),
suppression AS (
    SELECT DISTINCT side, parcel_id, effective_date AS key_date
      FROM ledger WHERE source_type = 'calculated'
    UNION
    SELECT DISTINCT side, parcel_id, date_trunc('month', effective_date)::date
      FROM ledger WHERE source_type = 'meter_reading'
),
billable AS (
    SELECT l.* FROM ledger l
     WHERE NOT (l.source_type = 'et_estimate'
                AND EXISTS (SELECT 1 FROM suppression s
                             WHERE s.side = l.side
                               AND s.parcel_id = l.parcel_id
                               AND s.key_date = l.effective_date))
),
sup AS (
    SELECT side,
           abs(COALESCE(SUM(amount_acre_feet)
               FILTER (WHERE source_type = 'surface_diversion'), 0)) AS surface,
           abs(COALESCE(SUM(amount_acre_feet)
               FILTER (WHERE amount_acre_feet < 0
                         AND source_type <> 'surface_diversion'), 0)) AS groundwater
      FROM billable GROUP BY side
),
run AS (
    SELECT pop.side,
           COALESCE(SUM(cr.gross_et_af), 0) AS gross,
           COALESCE(SUM(cr.effective_precip_af), 0) AS precip
      FROM population pop
      JOIN accounting_calculationrun cr ON cr.parcel_id = pop.parcel_id
      JOIN period p ON cr.period_start >= p.first_month
                   AND cr.period_start <= p.end_date
     GROUP BY pop.side
),
totals AS (
    SELECT s.side, s.surface, s.groundwater, r.precip,
           s.surface + s.groundwater + r.precip AS supply_total,
           r.gross
      FROM sup s JOIN run r ON r.side = s.side
)
SELECT 'single_pass_supplies' AS check, round(supply_total, 2) AS value,
       'FIG-accounting-023' AS figure FROM totals WHERE side = 'account_side'
UNION ALL SELECT 'single_pass_consumptive_use', round(gross, 2), 'FIG-accounting-024'
  FROM totals WHERE side = 'account_side'
UNION ALL SELECT 'single_pass_balance', round(supply_total - gross, 2), 'FIG-accounting-025'
  FROM totals WHERE side = 'account_side'
UNION ALL SELECT 'single_pass_surface', round(surface, 2), 'FIG-accounting-026'
  FROM totals WHERE side = 'account_side'
UNION ALL SELECT 'single_pass_groundwater', round(groundwater, 2), 'FIG-accounting-027'
  FROM totals WHERE side = 'account_side'
UNION ALL SELECT 'single_pass_precip', round(precip, 2), 'FIG-accounting-028'
  FROM totals WHERE side = 'account_side'
UNION ALL SELECT 'zone_side_supplies', round(supply_total, 2), '(zone table)'
  FROM totals WHERE side = 'zone_side'
UNION ALL SELECT 'zone_side_consumptive_use', round(gross, 2), '(zone table)'
  FROM totals WHERE side = 'zone_side'
UNION ALL SELECT 'coverage_parcels_total',
       (SELECT count(*)::numeric FROM parcels_parcel), '—'
UNION ALL SELECT 'coverage_parcels_in_active_account',
       (SELECT count(*)::numeric FROM account_parcels), '—'
UNION ALL SELECT 'coverage_parcels_in_a_zone',
       (SELECT count(*)::numeric FROM zone_parcels), '—'
UNION ALL SELECT 'coverage_parcels_in_two_active_accounts',
       (SELECT count(*)::numeric FROM (
          SELECT wap.parcel_id FROM accounting_wateraccount wa
            JOIN accounting_wateraccountparcel wap ON wap.water_account_id = wa.id
           WHERE wa.status = 'active' AND wap.removed_date IS NULL
           GROUP BY wap.parcel_id HAVING count(DISTINCT wa.id) > 1) d), '—'
UNION ALL SELECT 'coverage_et_estimate_rows_in_period',
       (SELECT count(*)::numeric FROM parcels_parcelledger pl JOIN period p
          ON pl.reporting_period_id = p.id WHERE pl.source_type = 'et_estimate'), '—'
-- A reader who adds up the zone table's Supplies column does NOT get the panel's
-- grand total, because a parcel sits in a groundwater-agency zone AND in a
-- surface service-area zone. The membership rows below say by how much.
UNION ALL SELECT 'coverage_zone_membership_rows',
       (SELECT count(*)::numeric FROM geography_parcelzone), '—'
UNION ALL SELECT 'coverage_parcels_in_more_than_one_zone',
       (SELECT count(*)::numeric FROM (SELECT parcel_id FROM geography_parcelzone
          GROUP BY parcel_id HAVING count(*) > 1) d), '—';
