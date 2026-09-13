-- FIG-recharge-002, 003, 004, 007 (the recharge site page's lead panel, its
-- "by water type" breakdown, and the event table's own current-year closing
-- subtotal). 143-10, Task 3.
--
-- WHAT THIS FILE CHECKS. Task 3 gave a recharge site's detail page a lead
-- panel: the CURRENT water year's Recharged total (a SUM, never a
-- difference -- a recharge event has nothing to subtract, unlike the
-- diversion page's Diverted/Return flow/Retained), with a "by water type"
-- breakdown when the period holds more than one type. The panel is
-- asserted, by the template and by Task 5's guards, to equal the SAME
-- group's subtotal in the event table under it -- this file is the THIRD
-- route: it does not read the view's grouping code at all, only
-- `recharge_rechargeevent`, `accounting_reportingperiod` and
-- `accounting_watertype`.
--
-- PINS (matching the local demonstration database, 2026-09-12):
--   period_id = 2      -- WY 2025-2026, the id accounting.services.current_period_id resolves to today, stated but not invoked here
--   site_id   = 1       -- El Nido Recharge Basin 1
--
-- INDEPENDENCE. Tables and columns only, no application import, run on the
-- host through audit/figure_ledger/run_sql.sh (docker compose exec db),
-- outside the process that owns the object-relational mapper.
--
-- RULES TRANSCRIBED FROM SOURCE, read 2026-09-12:
--   recharge/views.py::_group_recharge_events   groups an already-fetched
--       list of RechargeEvent rows by which ReportingPeriod's
--       [start_date, end_date] range contains the event's start_date (the
--       model carries NO reporting_period FK, unlike surface.DiversionRecord,
--       so this file re-derives the same date-range join directly against
--       the base tables) and sums volume_acre_feet per group, and per water
--       type within the group. An event outside every period's range would
--       close into a trailing "Outside any water year on record" group; the
--       local demonstration's six events on site 1 all fall inside one of
--       the two periods on file, so that branch is not exercised by this pin.
--   accounting/services.py::current_period_id   the period with a
--       "calculated" ledger row, most recent by start_date; named only to
--       STATE which period_id this pin selects. This file is plain SQL, so
--       nothing in it can reach that function or any other application code.

\set ON_ERROR_STOP on

WITH pin AS (
    SELECT 2::bigint AS period_id, 1::bigint AS site_id
),

-- ── The recharge site page: site 1, every water year on record, via a
--    date-range join against accounting_reportingperiod (RechargeEvent
--    carries no period FK) ─────────────────────────────────────────────────
site_year_sums AS (
    SELECT rp.id                                     AS reporting_period_id,
           rp.name                                    AS period_name,
           count(*)                                   AS event_count,
           round(SUM(e.volume_acre_feet), 2)          AS volume
      FROM recharge_rechargeevent e
      JOIN pin ON e.recharge_site_id = pin.site_id
      JOIN accounting_reportingperiod rp
        ON e.start_date BETWEEN rp.start_date AND rp.end_date
     GROUP BY rp.id, rp.name
),
site_current_year AS (
    SELECT s.* FROM site_year_sums s JOIN pin ON s.reporting_period_id = pin.period_id
),

-- "By water type", current water year only.
site_current_year_by_type AS (
    SELECT COALESCE(wt.name, 'Not recorded')         AS water_type_name,
           count(*)                                   AS event_count,
           round(SUM(e.volume_acre_feet), 2)          AS volume
      FROM recharge_rechargeevent e
      JOIN pin ON e.recharge_site_id = pin.site_id
      JOIN accounting_reportingperiod rp
        ON e.start_date BETWEEN rp.start_date AND rp.end_date AND rp.id = pin.period_id
      LEFT JOIN accounting_watertype wt ON wt.id = e.water_type_id
     GROUP BY wt.name
),

site_capacity AS (
    SELECT capacity_acre_feet FROM recharge_rechargesite s JOIN pin ON s.id = pin.site_id
)

SELECT 'site_year_sums' AS section, reporting_period_id::text AS key, period_name,
       event_count::text, volume::text
  FROM site_year_sums
UNION ALL
SELECT 'site_current_year_by_type', water_type_name, NULL,
       event_count::text, volume::text
  FROM site_current_year_by_type
UNION ALL
SELECT 'site_capacity', NULL, NULL, NULL,
       (SELECT capacity_acre_feet FROM site_capacity)::text
ORDER BY section, key;
