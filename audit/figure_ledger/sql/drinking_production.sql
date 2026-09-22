-- FIG-drinking-002, FIG-drinking-003
--
-- 146-04 Task 2 (D7, ISS-184): the production year table's Acre-feet row
-- (per type-code column, FIG-drinking-002) and the page's own grand-total
-- sentence ("N gallons (M acre-feet) across every source this year",
-- FIG-drinking-003). Both go through `floatformat:2` in
-- templates/drinking/production.html; the gallons figures beside them stay
-- plain Python `int()` (the state's own unit, always a whole number in both
-- layouts the platform reads) and carry no ledger row of their own.
--
-- SCREEN AND PIN: /drinking/production/?year=2022, Le Grand Community
-- Services District (PWSID CA2410011), the real 2022 eAR export
-- (`~/Documents/Vadose/Products/openh2o/six-shapes-2026-09/datasets/
-- shape-2-small-water-system/ear-2022-production.csv`, the same file
-- `tests/test_production_import.py::EAR_CSV_TEXT` carries verbatim). Twelve
-- GW months, SW all zero.
--
-- THE STANDING DEPLOYMENT CARRIES NO PRODUCTION ROWS as of this writing
-- (`drinking_systemproduction` is empty; the human-verify step of this plan
-- expects the page's own empty state for exactly that reason). The rendered
-- and recomputed values below were captured together on 2026-09-22 by
-- temporarily importing the fixture above against the deployment's one
-- WaterSystem (CA2410009, City of Merced -- its `pwsid` was swapped to
-- CA2410011 only for the length of the import, since the eAR importer
-- checks the row PWSID against `system.pwsid` and stores nothing PWSID-
-- shaped on the row itself, `drinking/production_import.py:160-166`),
-- reading the page with a real HTTP request, then deleting the imported
-- rows and restoring the system's real pwsid. This file reproduces the
-- independent half of that same measurement: point it at a deployment that
-- carries this fixture (or any system's real production year) and it
-- recomputes the same two totals from the base table alone.
--
-- INDEPENDENCE. This file names tables and columns only. It imports
-- nothing and calls no project function, and it runs on the host through
-- audit/figure_ledger/run_sql.sh, outside the process that owns the
-- object-relational mapper. TWO INDEPENDENCE CLASSES, both shown:
--   (a) TRANSCRIPTION -- SUM(volume_acre_feet), the same stored, per-row
--       column the view sums in Python (drinking/views.py:1743-1744).
--   (b) A DIFFERENT IDENTITY -- SUM(volume_gallons) / 325851, the literal
--       conversion constant the application owns
--       (drinking/models.py:694, PRODUCTION_GALLONS_PER_ACRE_FOOT), applied
--       ONCE to the gallons total rather than sixty times to a raw quantity
--       and rounded twice, thirteen times, along the way. On this
--       particular file the two methods agree to the cent (see the notes
--       column in the ledger); they need not, in general, since (a) rounds
--       twelve times before summing and (b) rounds once after.

\set ON_ERROR_STOP on

WITH pin AS (
    SELECT s.id AS system_id, 2022::smallint AS pin_year
      FROM drinking_watersystem s
     WHERE s.pwsid IN ('CA2410011', 'CA2410009')  -- Le Grand, or Merced while borrowing its pwsid for the probe
     ORDER BY s.id
     LIMIT 1
),
gw_rows AS (
    SELECT sp.volume_gallons, sp.volume_acre_feet
      FROM drinking_systemproduction sp
      JOIN pin ON sp.system_id = pin.system_id AND sp.year = pin.pin_year
     WHERE sp.type_code = 'GW'
),
totals AS (
    SELECT
        count(*)                                          AS n_months,
        sum(volume_gallons)                                AS gallons_total,
        round(sum(volume_acre_feet), 2)                    AS af_sum_of_stored_rows,
        round(sum(volume_gallons) / 325851, 2)              AS af_from_gallons_total
      FROM gw_rows
)
SELECT
    'FIG-drinking-002/003' AS id,
    'GW column, year 2022, ' || n_months || ' months' AS label,
    gallons_total,
    af_sum_of_stored_rows  AS recomputed_transcription,
    af_from_gallons_total  AS recomputed_different_identity
FROM totals;
