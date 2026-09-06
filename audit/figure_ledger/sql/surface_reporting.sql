-- FIG-surface-001..009, FIG-reporting-001..005: surface water and state reporting,
-- all 14 rendered figures in section C of the figure ledger.
--
-- SCREENS AND PINS (each also recorded in audit/figure_ledger/screens-c.json):
--   /surface/diversion/9/                            FIG-surface-001..005
--       MER-POD-011-DEMO Snelling Re-Diversion, point of diversion id 9.
--       Diversion-records row pinned to 2026-05-15, the ONLY record in the
--       demonstration whose return flow is neither zero nor the whole volume
--       (250.0000 diverted, 100.0000 returned, 150.0000 consumed), so the three
--       columns are three distinct numbers and a wrong subtraction can fail.
--       Everywhere else consumed equals diverted and a zero column would match
--       any formula at all.
--   /surface/rights/7/                               FIG-surface-007..009
--       MER-WR-010-DEMO, Halvern Hydroelectric Co. Points of diversion order by
--       name, so the pinned Max rate is MER-POD-010-DEMO's. Recent diversion
--       records order by month descending; the pinned first row is 2026-09-15,
--       unambiguous because the right's other diversion point has no September
--       2026 record.
--   /surface/rights/                                 FIG-surface-006
--       Ordered by right identifier, so the pinned Face Value is the first row,
--       MER-WR-004-DEMO. All six rights are also checked whole-column below.
--   /reporting/reports/4/calwatrs-worksheet/         FIG-reporting-001..002
--       Submission 4, CalWATRS To Storage (report type calwatrs_a2), reporting
--       period 2 = WY 2025-2026, the dry year. Blocks order by diversion point
--       name, so the first block is MER-BPOD-001 El Nido Canal Recharge Intake
--       and its first row is 2026-01-15.
--   /reporting/reports/shared-supply-check/?period=2 FIG-reporting-003..005
--       WY 2025-2026, matching section 1's pin. Groups sort by kind then source
--       name, so the first group is the point of diversion MER-POD-004-DEMO
--       Atwater Canal Headgate. Pinned row: use area MER-APN-058, parcel id 58,
--       the first row of that group in the captured page.
--
-- INDEPENDENCE. This file references tables and columns only. It does not reach
-- into any project module, and it runs on the host through
-- audit/figure_ledger/run_sql.sh, outside the process that owns the
-- object-relational mapper. Rules the application owns are transcribed as
-- literals with the source line beside them.
--
-- INDEPENDENCE CLASS, stated per row in the ledger's Notes column:
--   * DIFFERENT IDENTITY. FIG-surface-001, 002, 003, 004, 006, 007, 008, 009
--     and FIG-reporting-001, 002 are stored column values selected by the
--     screen's own ordering rule. The recomputation reaches them by a different
--     route (a join and an ORDER BY over base tables) than the page does, and
--     would disagree if the page picked a different row than it claims to.
--     FIG-surface-005 restates one subtraction but is cross-checked platform-wide.
--   * RESTATEMENT. FIG-reporting-003, 004, 005 re-derive the four-rung
--     apportionment ladder, including which rung fires and where the rounding
--     residual lands. That can catch a coding mistake; it cannot catch a wrong
--     idea about what a share should mean. A different-identity cross-check
--     accompanies them at the foot of this file.
--
-- RULES TRANSCRIBED FROM SOURCE, read 2026-09-05:
--   surface/models.py:170   consumed magnitude = abs(volume_acre_feet) minus
--       returned_af. Surface diversions are stored negative by production
--       convention, hence the absolute value; the demonstration stores these
--       particular rows positive, and abs() is written in regardless because the
--       platform's own rule says so.
--   surface/models.py:160   unique_together on (point_of_diversion, month,
--       diversion_type). A diversion record is MONTHLY by design, and the only
--       two types are direct_use and to_storage.
--   surface/views.py:104-108  the diversion point's own records table is every
--       record for that point, ordered by month descending, with NO period
--       filter. So no ?period= choice changes it.
--   surface/views.py:309    a right's points of diversion order by name.
--   surface/views.py:312-316  a right's recent diversion records are its points'
--       records ordered by month descending, capped at 12. The order names ONLY
--       month, so two points sharing a month are in an unspecified order; the pin
--       above sits on a month only one point has.
--   surface/views.py:272    the rights list orders by right_id.
--   reporting/views.py:411-418  the worksheet selects diversion records on the
--       reporting-period foreign key ALONE (strict equality, no month span) AND
--       on diversion_type, ordered by point-of-diversion name then month. This
--       is NOT the selector at surface/services.py:89, which matches the foreign
--       key OR the month span and does not filter on type at all. See the
--       cross-checks at the foot of this file.
--   reporting/views.py:409  report type calwatrs_a1 selects direct_use,
--       calwatrs_a2 selects to_storage.
--   reporting/generators.py:573-578  ISS-031b: the GENERATED CalWATRS file
--       withholds every row whose Water Right ID is blank, because a blank key is
--       one the state portal rejects. The worksheet screen shows the block
--       anyway, labelled "No linked water right".
--   accounting/services.py:642-646  which calculation runs belong to a period:
--       period_start on or after the FIRST OF THE PERIOD'S OPENING MONTH and on
--       or before the period's end date. A whole month that merely overlaps is
--       in; monthly runs are not pro-rated.
--   reporting/generators.py:103-108  a parcel's demand for a period is the SUM of
--       net_consumptive_use_af over that period's runs.
--   accounting/allocation_math.py:211  RUNG 2. If ANY of a shared source's link
--       fractions differs from the 1.0 sentinel, the whole group is hand-set and
--       the weights are the stored fractions.
--   accounting/allocation_math.py:214-218  RUNG 3. Otherwise, if total demand is
--       above zero the weights are the demands; RUNG 4, otherwise an even split.
--   accounting/allocation_math.py:230  weights are normalized by their total, then
--       quantized to 4 decimal places (the _Q constant, Decimal("0.0001")).
--   accounting/allocation_math.py:87-90  the quantization residual is added to the
--       LAST key by sorted str(key). For integer parcel ids that is TEXT order,
--       not numeric order.
--   reporting/generators.py:211-217  the ET-implied share calls the same ladder
--       with every fraction forced to the 1.0 sentinel, which drops it to rung 3.
--       Where total demand is zero the share is undefined (shown as "Not
--       recorded"), never a misleading even split.
--   reporting/generators.py:225  the gap is the ABSOLUTE difference of the two
--       shares, not re-quantized.
--   reporting/generators.py:36   0.15, the flag threshold, 15 percentage points.
--
-- ⚠ ROUNDING. Python's Decimal quantize defaults to half-to-even; this database's
-- round() is half-away-from-zero. They can only differ on an EXACT tie at the
-- fifth decimal place. Cross-check 6 at the foot of this file counts those ties
-- across every shared source; it returns 0 on this data, so the two rules cannot
-- disagree here.

\set ON_ERROR_STOP on

WITH
-- The three things this section pins, named once so a reader can change them
-- in one place: the dry year, the water right, the diversion point.
pin AS (
    SELECT 2::bigint  AS period_id,      -- WY 2025-2026
           7::bigint  AS water_right_id, -- MER-WR-010-DEMO, Halvern Hydroelectric Co.
           9::bigint  AS pod_id,         -- MER-POD-011-DEMO Snelling Re-Diversion
           DATE '2026-05-15' AS pod_record_month,
           4::bigint  AS submission_id,  -- CalWATRS To Storage, period 2
           58::bigint AS shared_parcel_id -- MER-APN-058, first row of the first group
),
period AS (
    SELECT rp.id, rp.name, rp.start_date, rp.end_date,
           date_trunc('month', rp.start_date)::date AS first_month
      FROM accounting_reportingperiod rp JOIN pin ON rp.id = pin.period_id
),

-- ── Surface: the pinned diversion point and its pinned record ────────────────
pinned_pod AS (
    SELECT p.id, p.name, p.stream_name, p.max_rate_cfs, p.water_right_id
      FROM surface_pointofdiversion p JOIN pin ON p.id = pin.pod_id
),
pinned_pod_right AS (
    SELECT wr.id, wr.right_id, wr.holder_name, wr.face_value_acre_feet
      FROM surface_waterright wr
      JOIN pinned_pod pp ON pp.water_right_id = wr.id
),
pinned_pod_record AS (
    SELECT d.id, d.month, d.volume_acre_feet, d.returned_af,
           -- surface/models.py:170, transcribed.
           abs(d.volume_acre_feet) - d.returned_af AS consumed_acre_feet
      FROM surface_diversionrecord d
      JOIN pin ON d.point_of_diversion_id = pin.pod_id
                AND d.month = pin.pod_record_month
),

-- ── Surface: the pinned water right, its first point, its newest record ──────
pinned_right AS (
    SELECT wr.id, wr.right_id, wr.holder_name, wr.face_value_acre_feet
      FROM surface_waterright wr JOIN pin ON wr.id = pin.water_right_id
),
-- surface/views.py:309, ordered by name; the pane shows the max rate of each,
-- and the pinned figure is the first.
pinned_right_first_pod AS (
    SELECT p.id, p.name, p.max_rate_cfs
      FROM surface_pointofdiversion p JOIN pin ON p.water_right_id = pin.water_right_id
     ORDER BY p.name
     LIMIT 1
),
-- surface/views.py:312-316, every record on every point of the right, newest
-- month first, capped at 12; the pinned figure is the first row's volume.
pinned_right_newest_record AS (
    SELECT d.month, d.volume_acre_feet, p.name AS pod_name
      FROM surface_diversionrecord d
      JOIN surface_pointofdiversion p ON p.id = d.point_of_diversion_id
      JOIN pin ON p.water_right_id = pin.water_right_id
     ORDER BY d.month DESC, p.name
     LIMIT 1
),
-- surface/views.py:272, the list orders by right identifier; the pinned Face
-- Value is the first row's, shown to zero decimal places.
first_right_by_id AS (
    SELECT wr.right_id, wr.face_value_acre_feet
      FROM surface_waterright wr ORDER BY wr.right_id LIMIT 1
),

-- ── Reporting: the CalWATRS transcription worksheet ──────────────────────────
-- reporting/views.py:409-418, transcribed: the submission's period, its type's
-- diversion type, blocks ordered by point-of-diversion name, rows by month.
submission AS (
    SELECT rs.id, rs.reporting_period_id, rt.report_type,
           CASE WHEN rt.report_type = 'calwatrs_a1' THEN 'direct_use'
                ELSE 'to_storage' END AS diversion_type
      FROM reporting_reportsubmission rs
      JOIN reporting_reporttemplate rt ON rt.id = rs.report_template_id
      JOIN pin ON rs.id = pin.submission_id
),
worksheet_rows AS (
    SELECT p.name AS pod_name, p.water_right_id, d.month,
           d.volume_acre_feet, d.max_flow_rate_cfs
      FROM surface_diversionrecord d
      JOIN surface_pointofdiversion p ON p.id = d.point_of_diversion_id
      JOIN submission s ON d.reporting_period_id = s.reporting_period_id
                       AND d.diversion_type = s.diversion_type
),
worksheet_first_row AS (
    SELECT * FROM worksheet_rows ORDER BY pod_name, month LIMIT 1
),

-- ── Reporting: the shared-supply check, pinned group ─────────────────────────
-- The group is the point of diversion whose name sorts first among the hand-set
-- shared points of diversion. reporting/generators.py:300-313: a candidate has
-- two or more links and at least one fraction off the 1.0 sentinel; groups sort
-- by kind then source name, and "Point of diversion" sorts before "Well".
pod_links AS (
    SELECT pp.point_of_diversion_id AS pod_id, p.name AS pod_name,
           pp.parcel_id, pp.fraction
      FROM surface_pointofdiversionparcel pp
      JOIN surface_pointofdiversion p ON p.id = pp.point_of_diversion_id
),
handset_pods AS (
    SELECT pod_id, pod_name
      FROM pod_links
     GROUP BY pod_id, pod_name
    HAVING count(*) >= 2 AND count(*) FILTER (WHERE fraction <> 1.0) > 0
),
first_group AS (
    SELECT pod_id, pod_name FROM handset_pods ORDER BY pod_name LIMIT 1
),
group_links AS (
    SELECT l.parcel_id, l.fraction
      FROM pod_links l JOIN first_group g ON g.pod_id = l.pod_id
),
-- reporting/generators.py:103-108 with accounting/services.py:642-646's
-- membership rule, transcribed: sum of net consumptive use over the period's runs.
group_demand AS (
    SELECT gl.parcel_id,
           COALESCE((SELECT SUM(cr.net_consumptive_use_af)
                       FROM accounting_calculationrun cr
                       JOIN period pd ON cr.period_start >= pd.first_month
                                     AND cr.period_start <= pd.end_date
                      WHERE cr.parcel_id = gl.parcel_id), 0) AS demand,
           gl.fraction
      FROM group_links gl
),
group_totals AS (
    SELECT SUM(fraction) AS total_fraction, SUM(demand) AS total_demand,
           -- accounting/allocation_math.py:211, rung 2 fires if ANY fraction is
           -- off the sentinel. It does here; the ET column forces every fraction
           -- to the sentinel and so falls to rung 3.
           bool_or(fraction <> 1.0) AS handset
      FROM group_demand
),
-- Quantize to 4dp, then place the residual on the LAST parcel id BY TEXT ORDER
-- (accounting/allocation_math.py:87-90).
group_quantized AS (
    SELECT gd.parcel_id,
           round(gd.fraction / NULLIF(gt.total_fraction, 0), 4) AS your_raw,
           CASE WHEN gt.total_demand > 0
                THEN round(gd.demand / gt.total_demand, 4) END   AS et_raw,
           gt.total_demand
      FROM group_demand gd CROSS JOIN group_totals gt
),
group_residual AS (
    SELECT (SELECT parcel_id FROM group_quantized
             ORDER BY parcel_id::text DESC LIMIT 1)            AS last_parcel_id,
           1.0000 - SUM(your_raw)                              AS your_residual,
           CASE WHEN bool_and(et_raw IS NOT NULL)
                THEN 1.0000 - SUM(et_raw) END                  AS et_residual
      FROM group_quantized
),
group_weights AS (
    SELECT q.parcel_id, pa.parcel_number,
           q.your_raw + CASE WHEN q.parcel_id = r.last_parcel_id
                             THEN r.your_residual ELSE 0 END AS your_weight,
           CASE WHEN q.et_raw IS NULL THEN NULL
                ELSE q.et_raw + CASE WHEN q.parcel_id = r.last_parcel_id
                                     THEN COALESCE(r.et_residual, 0) ELSE 0 END
           END                                                AS et_weight
      FROM group_quantized q
      CROSS JOIN group_residual r
      JOIN parcels_parcel pa ON pa.id = q.parcel_id
),
pinned_share AS (
    SELECT w.parcel_number, w.your_weight, w.et_weight,
           -- reporting/generators.py:225, the absolute difference, not re-rounded.
           abs(w.your_weight - w.et_weight) AS divergence
      FROM group_weights w JOIN pin ON w.parcel_id = pin.shared_parcel_id
),

-- ── The 14 figures ───────────────────────────────────────────────────────────
figures AS (
    SELECT 'FIG-surface-001' AS id,
           'Diversion point Max rate (CFS)' AS label,
           round(max_rate_cfs, 2)::text AS recomputed FROM pinned_pod
    UNION ALL SELECT 'FIG-surface-002', 'Diversion point, linked right Face value (AF)',
           round(face_value_acre_feet, 2)::text FROM pinned_pod_right
    UNION ALL SELECT 'FIG-surface-003', 'Diversion records Diverted (AF)',
           round(volume_acre_feet, 2)::text FROM pinned_pod_record
    UNION ALL SELECT 'FIG-surface-004', 'Diversion records Return Flow (AF)',
           round(returned_af, 2)::text FROM pinned_pod_record
    UNION ALL SELECT 'FIG-surface-005', 'Diversion records Consumptive Use (AF)',
           round(consumed_acre_feet, 2)::text FROM pinned_pod_record
    UNION ALL SELECT 'FIG-surface-006', 'Rights list Face Value',
           round(face_value_acre_feet, 0)::text FROM first_right_by_id
    UNION ALL SELECT 'FIG-surface-007', 'Water right Face value (AF)',
           round(face_value_acre_feet, 2)::text FROM pinned_right
    UNION ALL SELECT 'FIG-surface-008', 'Water right, first point of diversion Max rate',
           round(max_rate_cfs, 2)::text FROM pinned_right_first_pod
    UNION ALL SELECT 'FIG-surface-009', 'Water right Recent diversion records Volume (AF)',
           round(volume_acre_feet, 2)::text FROM pinned_right_newest_record

    UNION ALL SELECT 'FIG-reporting-001', 'CalWATRS worksheet Volume (AF)',
           round(volume_acre_feet, 2)::text FROM worksheet_first_row
    UNION ALL SELECT 'FIG-reporting-002', 'CalWATRS worksheet Max Rate (CFS)',
           round(max_flow_rate_cfs, 2)::text FROM worksheet_first_row
    UNION ALL SELECT 'FIG-reporting-003', 'Shared-supply Your share',
           to_char(your_weight, 'FM0.0000') FROM pinned_share
    UNION ALL SELECT 'FIG-reporting-004', 'Shared-supply ET-implied share',
           to_char(et_weight, 'FM0.0000') FROM pinned_share
    UNION ALL SELECT 'FIG-reporting-005', 'Shared-supply Gap',
           to_char(divergence, 'FM0.0000') FROM pinned_share
)
SELECT id, label, recomputed FROM figures ORDER BY id;


-- ═══════════════════════════════════════════════════════════════════════════
-- CROSS-CHECKS. Each starts somewhere the screens do not, and CAN disagree.
-- ═══════════════════════════════════════════════════════════════════════════

\echo '--- XC-1: consumed = abs(volume) - returned, on EVERY record, not just the pin'
SELECT count(*)                                                        AS records_total,
       count(*) FILTER (WHERE abs(volume_acre_feet) - returned_af
                              <> abs(volume_acre_feet) - returned_af)  AS arithmetic_breaks,
       count(*) FILTER (WHERE returned_af > abs(volume_acre_feet))     AS return_exceeds_volume,
       count(*) FILTER (WHERE returned_af = 0)                         AS zero_return,
       count(*) FILTER (WHERE returned_af = abs(volume_acre_feet))     AS full_return,
       count(*) FILTER (WHERE returned_af > 0
                          AND returned_af < abs(volume_acre_feet))     AS partial_return
  FROM surface_diversionrecord;

\echo '--- XC-2: whole-column Face Value, all six rights (FIG-surface-006/007)'
SELECT wr.right_id, wr.holder_name,
       round(wr.face_value_acre_feet, 0)::text AS list_face_value,
       round(wr.face_value_acre_feet, 2)::text AS detail_face_value
  FROM surface_waterright wr ORDER BY wr.right_id;

\echo '--- XC-3: whole-column diversion records for the pinned point (FIG-surface-003/004/005)'
SELECT d.month::text,
       round(d.volume_acre_feet, 2)::text                    AS diverted,
       round(d.returned_af, 2)::text                         AS return_flow,
       round(abs(d.volume_acre_feet) - d.returned_af, 2)::text AS consumptive_use,
       rp.name                                               AS period
  FROM surface_diversionrecord d
  LEFT JOIN accounting_reportingperiod rp ON rp.id = d.reporting_period_id
 WHERE d.point_of_diversion_id = 9
 ORDER BY d.month DESC;

\echo '--- XC-4: the worksheet screen vs the file the state actually receives'
-- The worksheet shows every block. The generated file withholds any row whose
-- Water Right ID is blank (reporting/generators.py:573-578). These two totals
-- therefore differ LEGITIMATELY, and this measures by how much.
SELECT rp.name                                                         AS period,
       round(SUM(d.volume_acre_feet), 2)                               AS worksheet_total_af,
       round(SUM(d.volume_acre_feet)
             FILTER (WHERE p.water_right_id IS NOT NULL), 2)           AS generated_file_total_af,
       round(SUM(d.volume_acre_feet)
             FILTER (WHERE p.water_right_id IS NULL), 2)               AS withheld_af,
       string_agg(DISTINCT p.name, '; ')
             FILTER (WHERE p.water_right_id IS NULL)                   AS withheld_points
  FROM surface_diversionrecord d
  JOIN surface_pointofdiversion p ON p.id = d.point_of_diversion_id
  JOIN accounting_reportingperiod rp ON rp.id = d.reporting_period_id
 WHERE d.diversion_type = 'to_storage' AND d.reporting_period_id = 2
 GROUP BY rp.name;

\echo '--- XC-5: does the period foreign key ever disagree with the month span?'
-- The worksheet selects on the foreign key ALONE (reporting/views.py:412-415);
-- the allocation selector at surface/services.py:99-105 matches the foreign key
-- OR the month span and does NOT filter on diversion type. Where every record
-- carries a foreign key that agrees with its own month, the two selectors differ
-- only by that type filter. This measures whether that holds.
SELECT count(*)                                                  AS records_total,
       count(*) FILTER (WHERE d.reporting_period_id IS NULL)     AS no_period_fk,
       count(*) FILTER (WHERE rp.id IS NOT NULL
                          AND (d.month < rp.start_date
                               OR d.month > rp.end_date))        AS fk_disagrees_with_month,
       count(*) FILTER (WHERE d.diversion_type = 'to_storage')   AS to_storage_rows
  FROM surface_diversionrecord d
  LEFT JOIN accounting_reportingperiod rp ON rp.id = d.reporting_period_id;

\echo '--- XC-6: rounding ties: would half-even and half-up ever differ here?'
-- A tie exists only when a share, scaled by 10000, lands exactly on .5. Zero
-- ties means this database's half-away-from-zero round() cannot disagree with
-- the application's half-to-even quantization on this data.
WITH links AS (
    SELECT pp.point_of_diversion_id AS src, pp.parcel_id, pp.fraction
      FROM surface_pointofdiversionparcel pp
    UNION ALL
    SELECT -wip.well_id, wip.parcel_id, wip.fraction
      FROM wells_wellirrigatedparcel wip
),
demand AS (
    SELECT l.src, l.parcel_id, l.fraction,
           COALESCE((SELECT SUM(cr.net_consumptive_use_af)
                       FROM accounting_calculationrun cr
                      WHERE cr.parcel_id = l.parcel_id
                        AND cr.period_start >= DATE '2025-10-01'
                        AND cr.period_start <= DATE '2026-09-30'), 0) AS demand
      FROM links l
),
tot AS (
    SELECT src, SUM(fraction) AS tf, SUM(demand) AS td FROM demand GROUP BY src
)
SELECT count(*) AS shares_examined,
       count(*) FILTER (WHERE (d.fraction / NULLIF(t.tf, 0)) * 10000
                              - floor((d.fraction / NULLIF(t.tf, 0)) * 10000) = 0.5)
                                                        AS your_share_ties,
       count(*) FILTER (WHERE t.td > 0
                          AND (d.demand / t.td) * 10000
                              - floor((d.demand / t.td) * 10000) = 0.5)
                                                        AS et_share_ties
  FROM demand d JOIN tot t ON t.src = d.src;

\echo '--- XC-7: every hand-set group -- do the two share columns each sum to 1.0000?'
-- accounting/allocation_math.py:186 claims the weights sum to EXACTLY 1.0000.
-- This is a different identity from any single row and can disagree with it.
WITH links AS (
    SELECT p.name AS source_name, pp.point_of_diversion_id AS src,
           pp.parcel_id, pp.fraction
      FROM surface_pointofdiversionparcel pp
      JOIN surface_pointofdiversion p ON p.id = pp.point_of_diversion_id
    UNION ALL
    SELECT w.name, -w.id, wip.parcel_id, wip.fraction
      FROM wells_wellirrigatedparcel wip JOIN wells_well w ON w.id = wip.well_id
),
handset AS (
    SELECT src, source_name FROM links GROUP BY src, source_name
    HAVING count(*) >= 2 AND count(*) FILTER (WHERE fraction <> 1.0) > 0
),
d AS (
    SELECT l.src, h.source_name, l.parcel_id, l.fraction,
           COALESCE((SELECT SUM(cr.net_consumptive_use_af)
                       FROM accounting_calculationrun cr
                      WHERE cr.parcel_id = l.parcel_id
                        AND cr.period_start >= DATE '2025-10-01'
                        AND cr.period_start <= DATE '2026-09-30'), 0) AS demand
      FROM links l JOIN handset h ON h.src = l.src
),
t AS (SELECT src, SUM(fraction) AS tf, SUM(demand) AS td FROM d GROUP BY src),
q AS (
    SELECT d.src, d.source_name, d.parcel_id,
           round(d.fraction / NULLIF(t.tf, 0), 4) AS your_raw,
           CASE WHEN t.td > 0 THEN round(d.demand / t.td, 4) END AS et_raw
      FROM d JOIN t ON t.src = d.src
),
r AS (
    SELECT src,
           (array_agg(parcel_id ORDER BY parcel_id::text DESC))[1] AS last_parcel_id,
           1.0000 - SUM(your_raw) AS your_residual,
           CASE WHEN bool_and(et_raw IS NOT NULL) THEN 1.0000 - SUM(et_raw) END
                                  AS et_residual
      FROM q GROUP BY src
),
w AS (
    SELECT q.src, q.source_name,
           q.your_raw + CASE WHEN q.parcel_id = r.last_parcel_id
                             THEN r.your_residual ELSE 0 END AS your_weight,
           CASE WHEN q.et_raw IS NULL THEN NULL
                ELSE q.et_raw + CASE WHEN q.parcel_id = r.last_parcel_id
                                     THEN COALESCE(r.et_residual, 0) ELSE 0 END
           END AS et_weight
      FROM q JOIN r ON r.src = q.src
)
SELECT source_name,
       count(*)                     AS use_areas,
       SUM(your_weight)             AS your_share_sum,
       SUM(et_weight)               AS et_share_sum,
       count(*) FILTER (WHERE et_weight IS NOT NULL
                          AND abs(your_weight - et_weight) >= 0.15) AS flagged_rows
  FROM w GROUP BY source_name ORDER BY source_name;
