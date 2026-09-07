-- FIG-wells-001 .. FIG-wells-004
--
-- The well page's Measurement history card (ISS-145, Plan 137-03). The card
-- was added after section D's remaining_subsystems.sql was written, ahead of
-- the four wells figures already in that file, which is why it is renumbered
-- FIG-wells-005..008 there and these four take 001..004 here instead of being
-- folded into that file.
--
-- SCREEN AND PIN (recorded in audit/figure_ledger/screens-d.json and
-- audit/figure_ledger/screens.json):
--   /wells/10/   Well id 10, registration MER-W-001. Pinned meter read: the
--                newest, 30 September 2026, on meter MTR-MER-W-001 (meter id
--                1, the well's one current WellMeter link). Pinned
--                water-level month: the newest, September 2026. This well has
--                no Sensor row, so its water-level digest reads the
--                hand-entered WaterMeasurement record
--                (wells/measurement_history.py:96-100, _hand_entered_points),
--                24 monthly rows, observed property groundwater_level_depth
--                (standards_observedproperty.key, id 4 on this database).
--
-- EVIDENCE, not a ledger figure: /wells/13/, MER-W-004, the transducer well
-- ISS-145's cited dry-year decline lives on (Sensor id 2, 730 daily
-- SensorMeasurement rows, 4 marked anomalous and dropped because that
-- sensor's own exclude_anomalies flag is set). Recomputed below as the
-- September 2025 and September 2026 monthly closes, so the two-year movement
-- the finding names has a number behind it. No FIG- row cites this well; it
-- rides along on the same query shape.
--
-- INDEPENDENCE. This file names tables and columns only. It imports nothing,
-- calls no project function, and runs on the host through
-- audit/figure_ledger/run_sql.sh, outside the process that owns the
-- object-relational mapper.
--
-- INDEPENDENCE CLASS, stated per row in the ledger's Notes column:
--   * TRANSCRIPTION — FIG-wells-001, the Totalizer: one stored column
--     (measurements_meterreading.current_value) read back and rounded the
--     same way the template does.
--   * DIFFERENT IDENTITY — FIG-wells-002, the Delta: recomputed two ways that
--     could disagree with each other and with the stored calculated_volume —
--     current_value minus THIS ROW'S OWN previous_value, and current_value
--     minus the PRIOR READ'S current_value, a chained cross-row identity the
--     stored column has no obligation to respect if a read is ever missed,
--     backdated, or entered out of order. Cross-check X1 states both figures
--     and their difference from the stored column across all 24 reads, not
--     only the pinned one.
--   * RESTATEMENT — FIG-wells-003 and FIG-wells-004, Close and Change: no
--     stored column holds either value — wells/measurement_history.py derives
--     both in Python — so the check re-derives the same selection rule the
--     view applies (the month's last reading, and that value minus the
--     previous month's) rather than reading a number back. A mistake in the
--     selection rule itself, not only in arithmetic on top of it, would
--     reproduce here rather than be caught by it.
--
-- Selection rules transcribed from source, read 2026-09-06:
--   wells/measurement_history.py:62      a well's meter history comes from its
--       current (is_current=True) WellMeter links only.
--   wells/measurement_history.py:55-56   _local_date(when) converts to the
--       application's configured time zone before taking the date,
--       America/Los_Angeles (config/settings/base.py:194), not UTC. Every
--       month boundary below is taken the same way, AT TIME ZONE
--       'America/Los_Angeles'.
--   wells/measurement_history.py:81-93   the water-level digest reads Sensor
--       measurements where the well has a Sensor row (_logger_points), and
--       the hand-entered WaterMeasurement record only where it does not
--       (_hand_entered_points, :96-100). The two sources are never mixed for
--       one well.
--   wells/measurement_history.py:90-91   a sensor's anomalous row is dropped
--       only when that sensor's own exclude_anomalies flag is set.
--   wells/measurement_history.py:119-126 a month's close is the value of the
--       LAST reading in that month by measurement_date, in ascending
--       iteration order (each new reading in the month overwrites the
--       month's "close").
--   wells/measurement_history.py:128-132 change is close minus the previous
--       entry's close, walked chronologically month to month; the earliest
--       month on record has no change.

\set ON_ERROR_STOP on

WITH pin AS (
    SELECT 10::bigint AS well_id,          -- MER-W-001
           1::bigint  AS meter_id,         -- MTR-MER-W-001, the well's one current meter
           13::bigint AS decline_well_id,  -- MER-W-004, evidence only
           2::bigint  AS decline_sensor_id
),

-- ── Meter reads: Totalizer and Delta ─────────────────────────────────────────
meter_reads AS (
    SELECT mr.id, mr.reading_date, mr.previous_value, mr.current_value,
           mr.calculated_volume,
           lag(mr.current_value) OVER (ORDER BY mr.reading_date) AS prior_read_current_value
      FROM measurements_meterreading mr
      JOIN pin ON mr.meter_id = pin.meter_id
),
pinned_read AS (
    SELECT * FROM meter_reads ORDER BY reading_date DESC LIMIT 1
),

-- ── Water-level digest: Close and Change ─────────────────────────────────────
-- Well 10 carries no Sensor row (asserted by X2 below), so the digest source
-- is the hand-entered WaterMeasurement record, exactly the branch
-- water_level_history() takes when _logger_points(well) returns empty.
water_level_points AS (
    SELECT wm.measurement_date,
           (wm.measurement_date AT TIME ZONE 'America/Los_Angeles') AS local_ts,
           wm.value
      FROM measurements_watermeasurement wm
      JOIN pin ON wm.well_id = pin.well_id
     WHERE wm.observed_property_id = 4  -- groundwater_level_depth
),
water_level_months AS (
    SELECT date_trunc('month', local_ts)::date AS month,
           (array_agg(value ORDER BY local_ts DESC))[1] AS close
      FROM water_level_points
     GROUP BY 1
),
water_level_digest AS (
    SELECT month, close,
           close - lag(close) OVER (ORDER BY month) AS change
      FROM water_level_months
),
pinned_month AS (
    SELECT * FROM water_level_digest ORDER BY month DESC LIMIT 1
),

-- ── Evidence only: MER-W-004's transducer record, September closes ──────────
decline_points AS (
    SELECT sm.measurement_date,
           (sm.measurement_date AT TIME ZONE 'America/Los_Angeles') AS local_ts,
           sm.value
      FROM measurements_sensormeasurement sm
      JOIN measurements_sensor s ON s.id = sm.sensor_id
      JOIN pin ON sm.sensor_id = pin.decline_sensor_id
     WHERE sm.observed_property_id = 4
       AND NOT (sm.is_anomalous AND s.exclude_anomalies)
),
decline_months AS (
    SELECT date_trunc('month', local_ts)::date AS month,
           (array_agg(value ORDER BY local_ts DESC))[1] AS close
      FROM decline_points
     GROUP BY 1
),

-- ── The four figures ─────────────────────────────────────────────────────────
figures AS (
    SELECT 'FIG-wells-001' AS id,
           'Well MER-W-001 newest meter read, Totalizer' AS label,
           round(current_value, 2) AS recomputed
      FROM pinned_read
    UNION ALL SELECT 'FIG-wells-002',
           'Well MER-W-001 newest meter read, Delta (AF)',
           round(current_value - previous_value, 2)
      FROM pinned_read
    UNION ALL SELECT 'FIG-wells-003',
           'Well MER-W-001 newest water-level month, Close (ft)',
           round(close, 2)
      FROM pinned_month
    UNION ALL SELECT 'FIG-wells-004',
           'Well MER-W-001 newest water-level month, Change (ft)',
           round(change, 2)
      FROM pinned_month
),

-- ── Cross-checks: these start somewhere the view does not ───────────────────
crosschecks AS (
    -- X1. THE ONE THAT COULD DISAGREE. Same-row delta (what the template
    -- shows via calculated_volume) against the chained cross-row delta, and
    -- both against the stored calculated_volume column, on the pinned read.
    SELECT 'X1-delta-same-row' AS id,
           'Pinned read: current_value minus THIS ROW''S previous_value' AS label,
           (SELECT round(current_value - previous_value, 4) FROM pinned_read) AS recomputed
    UNION ALL SELECT 'X1-delta-cross-row',
           'Pinned read: current_value minus the PRIOR READ''S current_value',
           (SELECT round(current_value - prior_read_current_value, 4) FROM pinned_read)
    UNION ALL SELECT 'X1-delta-stored',
           'Pinned read: stored calculated_volume',
           (SELECT round(calculated_volume, 4) FROM pinned_read)
    UNION ALL SELECT 'X1-chain-breaks-whole-column',
           'Reads on this meter where previous_value <> the prior read''s current_value',
           (SELECT count(*)::numeric FROM meter_reads
             WHERE prior_read_current_value IS NOT NULL
               AND previous_value <> prior_read_current_value)
    UNION ALL SELECT 'X1-reads-total',
           'Total reads on the pinned meter',
           (SELECT count(*)::numeric FROM meter_reads)

    -- X2. The pin is unambiguous: well 10 has no Sensor row, so the digest
    -- source really is the hand-entered branch, not a silent fallback.
    UNION ALL SELECT 'X2-well-10-sensor-rows', 'Sensor rows on well 10 (expect 0)',
           (SELECT count(*)::numeric FROM measurements_sensor s JOIN pin ON s.well_id = pin.well_id)
    UNION ALL SELECT 'X2-well-10-watermeasurement-rows',
           'WaterMeasurement rows on well 10, groundwater_level_depth (expect 24)',
           (SELECT count(*)::numeric FROM water_level_points)

    -- X3. MER-W-004 (well 13), evidence for the ISS-145 dry-year decline:
    -- the two September closes the finding names, and their difference.
    UNION ALL SELECT 'X3-well-13-sept-2025-close', 'Well MER-W-004 September 2025 close (ft)',
           (SELECT round(close, 4) FROM decline_months WHERE month = '2025-09-01')
    UNION ALL SELECT 'X3-well-13-sept-2026-close', 'Well MER-W-004 September 2026 close (ft)',
           (SELECT round(close, 4) FROM decline_months WHERE month = '2026-09-01')
    UNION ALL SELECT 'X3-well-13-two-year-decline',
           'Well MER-W-004 September 2026 close minus September 2025 close (ft)',
           (SELECT round(
               (SELECT close FROM decline_months WHERE month = '2026-09-01')
             - (SELECT close FROM decline_months WHERE month = '2025-09-01'), 4))
    UNION ALL SELECT 'X3-well-13-sensor-rows-total',
           'SensorMeasurement rows on well 13''s sensor, groundwater_level_depth (expect 730)',
           (SELECT count(*)::numeric FROM measurements_sensormeasurement sm
             JOIN pin ON sm.sensor_id = pin.decline_sensor_id
            WHERE sm.observed_property_id = 4)
    UNION ALL SELECT 'X3-well-13-anomalous-excluded',
           'Of those, rows marked anomalous and dropped (expect 4)',
           (SELECT count(*)::numeric FROM measurements_sensormeasurement sm
             JOIN measurements_sensor s ON s.id = sm.sensor_id
             JOIN pin ON sm.sensor_id = pin.decline_sensor_id
            WHERE sm.observed_property_id = 4 AND sm.is_anomalous AND s.exclude_anomalies)
)

SELECT id, label, recomputed FROM figures
UNION ALL
SELECT id, label, recomputed FROM crosschecks
ORDER BY id;
