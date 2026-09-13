-- FIG-surface-002..004, 009..011 (the diversion page's lead panel and its
-- table's subtotal rows), FIG-surface-013..019, 021 (the water right page's
-- lead panel, its per-point breakdown, and its table's subtotal rows).
-- 143-10, Task 2.
--
-- WHAT THIS FILE CHECKS. 143-10 added two new SUMS the platform had never
-- rendered before this plan: a diversion point's Diverted/Return flow/Retained
-- for the CURRENT water year alone (the lead panel on the diversion page,
-- repeated as the table's own closing subtotal row for that year), and a
-- water right's Recorded volume for the current water year across every point
-- of diversion it holds, broken down "by point of diversion" (the lead panel
-- on the water right page). Both panels are asserted, by the templates and by
-- Task 5's guards, to equal the SAME group's subtotal in the table under them
-- -- this file is the THIRD route: it does not read the view's grouping code
-- at all, only `surface_diversionrecord` and `accounting_reportingperiod`.
--
-- PINS (matching the local demonstration database, 2026-09-12; also recorded
-- in the ledger notes for each row, since these ids are candidate ids and have
-- moved before, per 136-02's own notes elsewhere in this directory):
--   period_id = 2      -- WY 2025-2026, the id accounting.services.current_period_id resolves to today, stated but not invoked here
--   pod_id    = 9       -- MER-BPOD-001 El Nido Canal Recharge Intake
--   right_id  = 6       -- MER-WR-010-DEMO, Halvern Hydroelectric Co.
--
-- INDEPENDENCE. Tables and columns only, no application import, run on the
-- host through audit/figure_ledger/run_sql.sh (docker compose exec db),
-- outside the process that owns the object-relational mapper.
--
-- RULES TRANSCRIBED FROM SOURCE, read 2026-09-12:
--   surface/models.py:162   consumed/retained magnitude = abs(volume_acre_feet)
--       minus returned_af (this file names the diversion page's version of
--       that figure "retained", the platform's own word, DESIGN.md rule 12).
--   surface/views.py::_group_diversion_records   groups an already-fetched,
--       already-ordered list of DiversionRecord rows by reporting_period_id
--       and sums volume_acre_feet (as `diverted`, absolute value) and
--       returned_af (as `returned`) per group; `retained` is `diverted` minus
--       `returned`. This file re-derives the same three sums straight from
--       the base table, grouped by reporting_period_id, with no ORM in the
--       path.
--   surface/views.py::_water_right_detail_context   the right's current-period
--       Recorded figure is the SAME per-period sum across every point of
--       diversion the right holds (a join through surface_pointofdiversion),
--       and the "By point of diversion" breakdown is that same set of rows
--       grouped a second way, by point_of_diversion_id.
--   accounting/services.py::current_period_id   the period with a
--       "calculated" ledger row, most recent by start_date; named only to STATE
--       which period_id this pin selects. This file is plain SQL, so nothing
--       in it can reach that function or any other application code.

\set ON_ERROR_STOP on

WITH pin AS (
    SELECT 2::bigint AS period_id, 9::bigint AS pod_id, 6::bigint AS right_id
),

-- ── The diversion page: POD 9, every water year on record ────────────────────
pod_year_sums AS (
    SELECT d.reporting_period_id,
           rp.name                                          AS period_name,
           count(*)                                         AS record_count,
           round(SUM(abs(d.volume_acre_feet)), 2)            AS diverted,
           round(SUM(d.returned_af), 2)                      AS returned,
           round(SUM(abs(d.volume_acre_feet) - d.returned_af), 2) AS retained
      FROM surface_diversionrecord d
      JOIN pin ON d.point_of_diversion_id = pin.pod_id
      LEFT JOIN accounting_reportingperiod rp ON rp.id = d.reporting_period_id
     GROUP BY d.reporting_period_id, rp.name
),
pod_current_year AS (
    SELECT s.* FROM pod_year_sums s JOIN pin ON s.reporting_period_id = pin.period_id
),

-- ── The water right page: right 6, every water year, across both PODs ────────
right_year_sums AS (
    SELECT d.reporting_period_id,
           rp.name                                AS period_name,
           count(*)                                AS record_count,
           round(SUM(abs(d.volume_acre_feet)), 2)  AS diverted
      FROM surface_diversionrecord d
      JOIN surface_pointofdiversion p ON p.id = d.point_of_diversion_id
      JOIN pin ON p.water_right_id = pin.right_id
      LEFT JOIN accounting_reportingperiod rp ON rp.id = d.reporting_period_id
     GROUP BY d.reporting_period_id, rp.name
),
right_current_year AS (
    SELECT s.* FROM right_year_sums s JOIN pin ON s.reporting_period_id = pin.period_id
),
-- "By point of diversion", current water year only.
right_current_year_by_pod AS (
    SELECT p.name                                  AS pod_name,
           count(*)                                AS record_count,
           round(SUM(abs(d.volume_acre_feet)), 2)  AS diverted
      FROM surface_diversionrecord d
      JOIN surface_pointofdiversion p ON p.id = d.point_of_diversion_id
      JOIN pin ON p.water_right_id = pin.right_id AND d.reporting_period_id = pin.period_id
     GROUP BY p.name
),
right_face_value AS (
    SELECT wr.face_value_acre_feet
      FROM surface_waterright wr JOIN pin ON wr.id = pin.right_id
)

SELECT 'pod_year_sums' AS section, reporting_period_id::text AS key, period_name,
       record_count::text, diverted::text, returned::text, retained::text
  FROM pod_year_sums
UNION ALL
SELECT 'right_year_sums', reporting_period_id::text, period_name,
       record_count::text, diverted::text, NULL, NULL
  FROM right_year_sums
UNION ALL
SELECT 'right_current_year_by_pod', pod_name, NULL,
       record_count::text, diverted::text, NULL, NULL
  FROM right_current_year_by_pod
UNION ALL
SELECT 'right_face_value_less_current_year', NULL, NULL, NULL,
       (SELECT face_value_acre_feet FROM right_face_value)::text, NULL,
       (SELECT round(f.face_value_acre_feet - c.diverted, 2)::text
          FROM right_face_value f, right_current_year c)
ORDER BY section, key;
