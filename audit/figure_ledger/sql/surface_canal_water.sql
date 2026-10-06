-- FIG-surface-005..019 (the diversion point page's "Where the water went"
-- table: the summary line's headgate total, one month's seven cells, and the
-- year's seven totals). 149-02 Task 2b.
--
-- WHAT THIS FILE CHECKS. The table reports, per month, the water taken at the
-- headgate, the three canal losses, the fields' own records, what was divided
-- up among the other fields, and what was left beyond what the crops could
-- use, then the same seven summed over a water year. The platform reads six of
-- those from stored rows (surface_canalmonthloss, parcels_parcelledger split
-- rows, surface_unallocateddelivery). This file does NOT read
-- surface_canalmonthloss to get its answer. It rebuilds the headgate figure
-- from the diversion records, the three losses from the point's own loss
-- fractions, and the fields' own records from the ledger rows a field typed or
-- imported, so a stale or hand-edited canal-loss row would show as a difference
-- rather than being echoed back. The stored canal-loss figure is printed
-- beside it in the `stored` column for exactly that comparison.
--
-- PINS (the restored demonstration database `golden_after`; run with
--   LEDGER_DB=golden_after bash audit/figure_ledger/run_sql.sh \
--     audit/figure_ledger/sql/surface_canal_water.sql):
--   pod_id    = 3            -- MER-POD-006-DEMO Stevinson Diversion Canal Headgate
--   month     = 2026-08-01   -- August 2026
--   period_id = 2            -- WY 2025-2026 (2025-10-01 to 2026-09-30)
--
-- INDEPENDENCE. Tables and columns only. No application import, run on the
-- host through audit/figure_ledger/run_sql.sh outside the process that owns the
-- object-relational mapper.
--
-- RULES TRANSCRIBED FROM SOURCE, read 2026-10-06 (surface/services.py):
--   a month's water at the headgate = the sum over that point's direct_use
--       diversion records of abs(volume_acre_feet) - returned_af
--       (DiversionRecord.consumed_acre_feet).
--   each canal loss = headgate x the point's fraction (evaporation_fraction,
--       seepage_fraction, spill_fraction on surface_pointofdiversion), to four
--       places (_month_losses).
--   a field's own records = its surface_diversion ledger rows with
--       divided_from_headgate false, magnitude summed per month; a field served
--       by one point counts whole, by several counts pro rata to each serving
--       point's recorded consumed total that month, or evenly when none
--       recorded anything (_own_magnitudes, _own_total_for_pod). Only fields
--       linked to the point in surface_pointofdiversionparcel are counted.
--   divided up = the magnitude of the ledger rows with divided_from_headgate
--       true AND divided_from_point_pk = the point (canal_water_by_month).
--   beyond what the crops could use = surface_unallocateddelivery.amount_acre_feet
--       for the point and month. Its month is stored mid-month, so it is
--       truncated to the first of the month before it is matched.
--   a water year's figure = the sum of the unrounded monthly figures over the
--       months inside the year, rounded to two places once, at the end.
--
-- ⚠ NON-DISCRIMINATING ON THIS DATA. In golden_after every canal-loss row on
-- every point has seepage = 0, spill = 0 and own = 0, and there are no
-- field-typed surface_diversion rows at all, so FIG-surface-008, 009, 010 (and
-- 015, 016, 017) agree trivially at 0.00; only evaporation (1 percent at this
-- point), headgate, divided and beyond carry a value that could be wrong.

\set ON_ERROR_STOP on

WITH pin AS (
    SELECT 3::bigint AS pod_id, DATE '2026-08-01' AS pin_month, 2::bigint AS period_id
),
pod AS (
    SELECT p.id, p.evaporation_fraction AS evap, p.seepage_fraction AS seep, p.spill_fraction AS spill
    FROM surface_pointofdiversion p JOIN pin ON p.id = pin.pod_id
),
period AS (
    SELECT rp.start_date, rp.end_date FROM accounting_reportingperiod rp JOIN pin ON rp.id = pin.period_id
),
-- headgate, rebuilt from the diversion records
headgate AS (
    SELECT date_trunc('month', d.month)::date AS m,
           SUM(abs(d.volume_acre_feet) - d.returned_af) AS hg
    FROM surface_diversionrecord d JOIN pin ON d.point_of_diversion_id = pin.pod_id
    WHERE d.diversion_type = 'direct_use'
    GROUP BY 1
),
losses AS (
    SELECT h.m, h.hg,
           round(h.hg * pod.evap, 4)  AS evaporation,
           round(h.hg * pod.seep, 4)  AS seepage,
           round(h.hg * pod.spill, 4) AS spill
    FROM headgate h CROSS JOIN pod
),
-- fields' own records
served AS (
    SELECT parcel_id FROM surface_pointofdiversionparcel JOIN pin ON point_of_diversion_id = pin.pod_id
),
own_parcel_month AS (
    SELECT date_trunc('month', l.effective_date)::date AS m, l.parcel_id, abs(SUM(l.amount_acre_feet)) AS mag
    FROM parcels_parcelledger l
    WHERE l.source_type = 'surface_diversion' AND NOT l.divided_from_headgate
      AND l.parcel_id IN (SELECT parcel_id FROM served)
    GROUP BY 1, 2
),
rec_by_pod_month AS (
    SELECT d.point_of_diversion_id AS pod, date_trunc('month', d.month)::date AS m,
           SUM(abs(d.volume_acre_feet) - d.returned_af) AS rec
    FROM surface_diversionrecord d WHERE d.diversion_type = 'direct_use' GROUP BY 1, 2
),
own_weighted AS (
    SELECT o.m, o.parcel_id, o.mag,
           COALESCE((SELECT SUM(r.rec) FROM surface_pointofdiversionparcel s
                     JOIN rec_by_pod_month r ON r.pod = s.point_of_diversion_id AND r.m = o.m
                     WHERE s.parcel_id = o.parcel_id), 0) AS serving_rec,
           COALESCE((SELECT r.rec FROM rec_by_pod_month r, pin WHERE r.pod = pin.pod_id AND r.m = o.m), 0) AS this_rec,
           (SELECT count(*) FROM surface_pointofdiversionparcel s WHERE s.parcel_id = o.parcel_id) AS n_serving
    FROM own_parcel_month o
),
own AS (
    SELECT m, round(SUM(CASE WHEN serving_rec > 0 THEN mag * this_rec / serving_rec
                             ELSE mag / n_serving END), 4) AS own
    FROM own_weighted GROUP BY m
),
divided AS (
    SELECT date_trunc('month', l.effective_date)::date AS m, SUM(abs(l.amount_acre_feet)) AS divided
    FROM parcels_parcelledger l JOIN pin ON l.divided_from_point_pk = pin.pod_id
    WHERE l.divided_from_headgate AND l.source_type = 'surface_diversion'
    GROUP BY 1
),
beyond AS (
    SELECT date_trunc('month', u.month)::date AS m, SUM(u.amount_acre_feet) AS beyond
    FROM surface_unallocateddelivery u JOIN pin ON u.point_of_diversion_id = pin.pod_id GROUP BY 1
),
months AS (
    SELECT l.m, l.hg AS headgate, l.evaporation, l.seepage, l.spill,
           COALESCE(o.own, 0) AS own, COALESCE(d.divided, 0) AS divided, COALESCE(b.beyond, 0) AS beyond
    FROM losses l
    LEFT JOIN own o ON o.m = l.m LEFT JOIN divided d ON d.m = l.m LEFT JOIN beyond b ON b.m = l.m
),
stored AS (
    SELECT c.month AS m, c.diverted_af, c.evaporation_af, c.seepage_af, c.spill_af, c.own_af
    FROM surface_canalmonthloss c JOIN pin ON c.point_of_diversion_id = pin.pod_id
),
year_months AS (
    SELECT mo.* FROM months mo, period pe WHERE mo.m >= pe.start_date AND mo.m <= pe.end_date
),
year_stored AS (
    SELECT s.* FROM stored s, period pe WHERE s.m >= pe.start_date AND s.m <= pe.end_date
),
-- one (id, scope, figure) list per site, then the recomputed and stored values
figures AS (
    SELECT 'FIG-surface-005'::text AS id, 'summary: WY total, taken at the headgate'::text AS what, 'WY'::text AS scope,
           (SELECT round(SUM(headgate), 2) FROM year_months) AS recomputed,
           (SELECT round(SUM(diverted_af), 2) FROM year_stored) AS stored
    UNION ALL SELECT 'FIG-surface-006', 'month: taken at the headgate', 'month',
           (SELECT round(headgate, 2) FROM months, pin WHERE m = pin.pin_month),
           (SELECT round(diverted_af, 2) FROM stored, pin WHERE m = pin.pin_month)
    UNION ALL SELECT 'FIG-surface-007', 'month: evaporation', 'month',
           (SELECT round(evaporation, 2) FROM months, pin WHERE m = pin.pin_month),
           (SELECT round(evaporation_af, 2) FROM stored, pin WHERE m = pin.pin_month)
    UNION ALL SELECT 'FIG-surface-008', 'month: seepage', 'month',
           (SELECT round(seepage, 2) FROM months, pin WHERE m = pin.pin_month),
           (SELECT round(seepage_af, 2) FROM stored, pin WHERE m = pin.pin_month)
    UNION ALL SELECT 'FIG-surface-009', 'month: spill', 'month',
           (SELECT round(spill, 2) FROM months, pin WHERE m = pin.pin_month),
           (SELECT round(spill_af, 2) FROM stored, pin WHERE m = pin.pin_month)
    UNION ALL SELECT 'FIG-surface-010', 'month: fields'' own records', 'month',
           (SELECT round(own, 2) FROM months, pin WHERE m = pin.pin_month),
           (SELECT round(own_af, 2) FROM stored, pin WHERE m = pin.pin_month)
    UNION ALL SELECT 'FIG-surface-011', 'month: divided up among the other fields', 'month',
           (SELECT round(divided, 2) FROM months, pin WHERE m = pin.pin_month), NULL
    UNION ALL SELECT 'FIG-surface-012', 'month: beyond what the crops could use', 'month',
           (SELECT round(beyond, 2) FROM months, pin WHERE m = pin.pin_month), NULL
    UNION ALL SELECT 'FIG-surface-013', 'WY total: taken at the headgate', 'WY',
           (SELECT round(SUM(headgate), 2) FROM year_months),
           (SELECT round(SUM(diverted_af), 2) FROM year_stored)
    UNION ALL SELECT 'FIG-surface-014', 'WY total: evaporation', 'WY',
           (SELECT round(SUM(evaporation), 2) FROM year_months),
           (SELECT round(SUM(evaporation_af), 2) FROM year_stored)
    UNION ALL SELECT 'FIG-surface-015', 'WY total: seepage', 'WY',
           (SELECT round(SUM(seepage), 2) FROM year_months),
           (SELECT round(SUM(seepage_af), 2) FROM year_stored)
    UNION ALL SELECT 'FIG-surface-016', 'WY total: spill', 'WY',
           (SELECT round(SUM(spill), 2) FROM year_months),
           (SELECT round(SUM(spill_af), 2) FROM year_stored)
    UNION ALL SELECT 'FIG-surface-017', 'WY total: fields'' own records', 'WY',
           (SELECT round(SUM(own), 2) FROM year_months),
           (SELECT round(SUM(own_af), 2) FROM year_stored)
    UNION ALL SELECT 'FIG-surface-018', 'WY total: divided up among the other fields', 'WY',
           (SELECT round(SUM(divided), 2) FROM year_months), NULL
    UNION ALL SELECT 'FIG-surface-019', 'WY total: beyond what the crops could use', 'WY',
           (SELECT round(SUM(beyond), 2) FROM year_months), NULL
)
SELECT id, what, scope, recomputed, stored FROM figures ORDER BY id, scope;

-- Cross-check 1: does the month add up the way the page claims? headgate minus
-- (the three losses + own + divided + beyond), for every month of the pin's
-- water year, from the recomputed figures. The page flags a month at more than
-- 0.0001.
\echo '--- XC-1: headgate minus the four parts, every month of the water year'
WITH pin AS (SELECT 3::bigint AS pod_id, 2::bigint AS period_id),
hg AS (
    SELECT date_trunc('month', d.month)::date AS m, SUM(abs(d.volume_acre_feet) - d.returned_af) AS h
    FROM surface_diversionrecord d JOIN pin ON d.point_of_diversion_id = pin.pod_id
    WHERE d.diversion_type = 'direct_use' GROUP BY 1
),
dv AS (
    SELECT date_trunc('month', l.effective_date)::date AS m, SUM(abs(l.amount_acre_feet)) AS x
    FROM parcels_parcelledger l JOIN pin ON l.divided_from_point_pk = pin.pod_id
    WHERE l.divided_from_headgate AND l.source_type = 'surface_diversion' GROUP BY 1
),
bd AS (
    SELECT date_trunc('month', u.month)::date AS m, SUM(u.amount_acre_feet) AS x
    FROM surface_unallocateddelivery u JOIN pin ON u.point_of_diversion_id = pin.pod_id GROUP BY 1
)
SELECT to_char(hg.m, 'YYYY-MM') AS month,
       round(hg.h - round(hg.h * p.evaporation_fraction, 4) - round(hg.h * p.seepage_fraction, 4)
             - round(hg.h * p.spill_fraction, 4) - COALESCE(dv.x, 0) - COALESCE(bd.x, 0), 4) AS unexplained_af
FROM hg CROSS JOIN pin
JOIN surface_pointofdiversion p ON p.id = pin.pod_id
JOIN accounting_reportingperiod rp ON rp.id = pin.period_id
LEFT JOIN dv ON dv.m = hg.m LEFT JOIN bd ON bd.m = hg.m
WHERE hg.m >= rp.start_date AND hg.m <= rp.end_date
ORDER BY hg.m;

-- Cross-check 2: whole-column. Every month of every point on file: does the
-- stored canal-loss headgate figure equal the records it was built from, and
-- does the stored evaporation equal that figure times the point's fraction?
-- Expect evaporation_differs = 2, and both are one rounding rule, not an error:
-- point 5, Oct 2024 and Oct 2025, is 104.2850 x 0.0100 = 1.04285 exactly. The
-- platform stores 1.0428 (round half to even, Python's Decimal default) and
-- PostgreSQL's round() gives 1.0429 (half away from zero). Point 3, the pin,
-- has no such tie in any month.
\echo '--- XC-2: stored canal-loss rows against the diversion records, all points'
SELECT count(*) AS stored_rows,
       sum((abs(c.diverted_af - COALESCE(h.hg, 0)) > 0.00005)::int) AS headgate_differs,
       sum((abs(c.evaporation_af - round(COALESCE(h.hg, 0) * p.evaporation_fraction, 4)) > 0.00005)::int) AS evaporation_differs
FROM surface_canalmonthloss c
JOIN surface_pointofdiversion p ON p.id = c.point_of_diversion_id
LEFT JOIN (
    SELECT point_of_diversion_id AS pod, date_trunc('month', month)::date AS m,
           SUM(abs(volume_acre_feet) - returned_af) AS hg
    FROM surface_diversionrecord WHERE diversion_type = 'direct_use' GROUP BY 1, 2
) h ON h.pod = c.point_of_diversion_id AND h.m = c.month;
