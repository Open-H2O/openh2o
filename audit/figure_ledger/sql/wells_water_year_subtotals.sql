-- FIG-wells-004
--
-- 143-10, Task 4 (R-111). The well page's meter-reads table gained a
-- water-year closing row inside the body (footer A, rule 7, no `tfoot`,
-- copying the diversion and recharge-event tables' own shape): a
-- `tr.row-subtotal` per water year whose Delta cell is the SUM of that
-- year's `calculated_volume` reads, computed in Python from the rows the
-- view already fetched (wells/measurement_history.py::meter_history) --
-- never a second query, never template arithmetic. This file recomputes the
-- same sum from the base table directly, outside the ORM.
--
-- SCREEN AND PIN: /wells/10/, well id 10 (MER-W-001), its one current meter
-- MTR-MER-W-001 (meter id 1). The page's two water years are labelled from
-- the read date, in the application's configured time zone
-- (America/Los_Angeles), never UTC -- the same conversion
-- well_measurement_history.sql already uses for this meter's Totalizer and
-- Delta figures (FIG-wells-002/003).
--
-- The Totalizer column carries no matching total: a totalizer is a running
-- reading, never summed. Only the Delta closes (wells/measurement_history.py,
-- the water-year loop that builds `delta_total`).
--
-- INDEPENDENCE. This file names tables and columns only. It imports nothing,
-- calls no project function, and runs on the host through
-- audit/figure_ledger/run_sql.sh, outside the process that owns the
-- object-relational mapper. INDEPENDENCE CLASS: TRANSCRIPTION -- the same
-- stored column (measurements_meterreading.calculated_volume) the per-row
-- Delta figure (FIG-wells-003) already reads, summed by a GROUP BY instead
-- of a Python loop over the same rows.

\set ON_ERROR_STOP on

WITH pin AS (
    SELECT 1::bigint AS meter_id  -- MTR-MER-W-001, well 10's one current meter
),
reads AS (
    SELECT mr.reading_date, mr.calculated_volume,
           (mr.reading_date AT TIME ZONE 'America/Los_Angeles') AS local_ts
      FROM measurements_meterreading mr
      JOIN pin ON mr.meter_id = pin.meter_id
),
by_water_year AS (
    -- The water year is named for the calendar year it ENDS in (October
    -- through September): wells/measurement_history.py:water_year().
    SELECT
        CASE WHEN EXTRACT(MONTH FROM local_ts) >= 10
             THEN EXTRACT(YEAR FROM local_ts) + 1
             ELSE EXTRACT(YEAR FROM local_ts) END::int AS water_year_ending,
        count(*) AS n_reads,
        round(sum(calculated_volume), 2) AS delta_total
      FROM reads
     GROUP BY 1
)

SELECT
    'FIG-wells-004' AS id,
    'WY ' || (water_year_ending - 1) || '-' || water_year_ending
        || ', meter MTR-MER-W-001, Delta subtotal (AF), ' || n_reads || ' reads' AS label,
    delta_total AS recomputed
FROM by_water_year
ORDER BY water_year_ending DESC;
