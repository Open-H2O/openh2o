-- FIG-datasync-001 .. FIG-datasync-004
-- FIG-geography-001 .. FIG-geography-004
-- FIG-recharge-001 .. FIG-recharge-004
-- FIG-setup-001 .. FIG-setup-002
-- FIG-wells-001 .. FIG-wells-004
--
-- Section D of the figure ledger: the long tail. Eighteen figures across ten
-- templates and five subsystems, most of them one or two to a screen.
--
-- SCREENS AND PINS (each also recorded in audit/figure_ledger/screens-d.json):
--   /map/zones/2/     Halvern Irrigation-Urban GSA, the same zone section 1
--                     pinned on the accounting dashboard. The page takes no
--                     period parameter; its Allocation vs. use table lists every
--                     period newest-first, so the pinned row is the first:
--                     WY 2025-2026 (reporting period id 2, the dry year), GW.
--                     Pinned parcel row: MER-APN-026 (parcel id 26), first by
--                     parcel number among the zone's 23.
--   /wells/32/        Well id 32, registration MER-W-001. One screen carries all
--                     four wells figures.
--   /recharge/6/      El Nido Recharge Basin 1, first by name on the list page.
--                     Pinned measurement: the newest, 2026-02-18 water quality.
--                     Pinned event: the newest by start date, 2026-02-15.
--   /recharge/        The list; ordered by name, every site on one page, so the
--                     pinned row is El Nido Recharge Basin 1 again.
--   /setup/           Boundary id 1, Merced Subbasin, the only Boundary row.
--   /datasync/stations/1/   404. See the datasync block below.
--   /setup/confirm/         302. See the setup block below.
--
-- INDEPENDENCE. This file names tables and columns only. It imports nothing,
-- calls no project function, and runs on the host through
-- audit/figure_ledger/run_sql.sh, outside the process that owns the
-- object-relational mapper. Selection rules the application owns are
-- transcribed as literals with the source line beside them.
--
-- INDEPENDENCE CLASS, stated per row in the ledger's Notes column:
--   * TRANSCRIPTION — the figure is one stored column rendered through a display
--     formatter. The check reads that column and applies the same rounding. It
--     proves the screen reports the row faithfully. It proves nothing about
--     whether the stored number is right, because nothing in the platform
--     derives it. Twelve of this section's eighteen figures are of this kind.
--   * RESTATEMENT — the check re-derives the same chain the view performs.
--   * DIFFERENT IDENTITY — the cross-checks at the end start somewhere the view
--     does not and CAN disagree with it. One of them does.
--
-- Selection rules transcribed from source, read 2026-09-05:
--   geography/views.py:163-170  a zone's parcels are its ParcelZone rows,
--       ordered by parcel number.
--   geography/views.py:173-179  a zone's allocations are every AllocationPlan
--       for the zone, ANY period, newest reporting-period start first.
--   geography/views.py:188      the ledger rows in scope are those of the zone's
--       parcels in THAT allocation's reporting period.
--   geography/views.py:196-201  where the allocation's water type code upper-cases
--       to 'GW', "used" is the ABSOLUTE VALUE OF THE SUM OF EVERY NEGATIVE
--       BILLABLE ROW, whatever its source type, and the screen labels it
--       "pumped". The comment at geography/views.py:181-186 says this figure is
--       "metered/estimated PUMPING (the magnitude of the negative extraction
--       rows)". The code applies no source-type filter, and surface canal
--       deliveries are stored negative, so they fall inside it. Transcribed as
--       WRITTEN, and decomposed in cross-check X2 below.
--   geography/views.py:217-223  remaining = allocation − used.
--   accounting/services.py:377  billable_ledger — an `et_estimate` row is
--       suppressed where a `calculated` row exists for the same
--       (parcel, effective_date), or a `meter_reading` row exists for the same
--       (parcel, first-of-that-month). Stated below as its own predicate, and
--       scoped to the same rows the view scopes it to.
--   recharge/views.py:82-84     a site's events are every RechargeEvent for the
--       site, newest start date first, unpaginated.
--   recharge/views.py:95-97     recent measurements are the newest TEN by
--       measurement date.
--   recharge/views.py:45,57     the site list is ordered by name, 100 to a page.
--   wells/views.py:157          a well's irrigated parcels are its
--       WellIrrigatedParcel rows in default (primary key) order.
--   wells/views.py:158          the monitoring card reads the well's one
--       MonitoringWell row, or renders nothing.
--   wells/views.py:173-182      every editable field is `getattr(well, name)` —
--       a stored column, with no derivation of any kind behind it.
--   setup/boundaries.py:120-126 area_sq_miles is TAKEN FROM THE UPLOADED FILE'S
--       OWN PROPERTIES and is deliberately NOT computed from the polygon:
--       "an area computed from the polygon would be a number OpenH2O invented
--       (decided 2026-08-05)". Cross-check X4 computes it from the polygon
--       anyway, precisely because the platform will not.
--
-- Constants:
--   2589988.110336  square metres in a square mile. Definitional, not the
--       application's: 1 international mile = 1609.344 m exactly, so
--       1609.344^2 = 2589988.110336. Used only in cross-check X4.

\set ON_ERROR_STOP on

WITH pin AS (
    SELECT 2::bigint  AS zone_id,
           2::bigint  AS period_id,
           26::bigint AS parcel_id,
           32::bigint AS well_id,
           6::bigint  AS recharge_site_id,
           1::bigint  AS boundary_id
),

-- ── Geography: the zone page's Allocation vs. use table ──────────────────────
-- The pinned row is the newest allocation for the pinned zone.
zone_alloc AS (
    SELECT ap.id,
           ap.zone_id,
           ap.reporting_period_id,
           ap.allocation_acre_feet,
           upper(coalesce(wt.code, '')) AS wt_code,
           rp.start_date
      FROM accounting_allocationplan ap
      JOIN pin ON ap.zone_id = pin.zone_id
      JOIN accounting_watertype wt ON wt.id = ap.water_type_id
      JOIN accounting_reportingperiod rp ON rp.id = ap.reporting_period_id
),
pinned_alloc AS (
    SELECT * FROM zone_alloc
     WHERE reporting_period_id = (SELECT period_id FROM pin)
),

-- Every ledger row for the zone's parcels in the pinned allocation's period.
zone_ledger AS (
    SELECT pl.id, pl.parcel_id, pl.effective_date, pl.source_type,
           pl.amount_acre_feet
      FROM parcels_parcelledger pl
      JOIN geography_parcelzone pz ON pz.parcel_id = pl.parcel_id
      JOIN pin ON pz.zone_id = pin.zone_id
     WHERE pl.reporting_period_id = (SELECT reporting_period_id FROM pinned_alloc)
),
-- The suppression keys, scoped to exactly those rows.
zone_suppression AS (
    SELECT DISTINCT parcel_id, effective_date AS key_date
      FROM zone_ledger WHERE source_type = 'calculated'
    UNION
    SELECT DISTINCT parcel_id, date_trunc('month', effective_date)::date
      FROM zone_ledger WHERE source_type = 'meter_reading'
),
zone_billable AS (
    SELECT l.* FROM zone_ledger l
     WHERE NOT (
        l.source_type = 'et_estimate'
        AND EXISTS (SELECT 1 FROM zone_suppression s
                     WHERE s.parcel_id = l.parcel_id
                       AND s.key_date  = l.effective_date)
     )
),
zone_used AS (
    -- Transcribed as written: EVERY negative billable row, no source-type filter.
    SELECT abs(coalesce(SUM(amount_acre_feet)
               FILTER (WHERE amount_acre_feet < 0), 0)) AS used,
           -- The decomposition the screen's own label implies, for X2.
           abs(coalesce(SUM(amount_acre_feet)
               FILTER (WHERE amount_acre_feet < 0
                         AND source_type <> 'surface_diversion'), 0)) AS used_gw_only,
           abs(coalesce(SUM(amount_acre_feet)
               FILTER (WHERE source_type = 'surface_diversion'), 0)) AS used_surface
      FROM zone_billable
),

-- ── Wells ───────────────────────────────────────────────────────────────────
pinned_well AS (
    SELECT w.id, w.year_pumping_began, w.capacity_gpm, w.depth_ft
      FROM wells_well w JOIN pin ON w.id = pin.well_id
),
pinned_wip AS (
    -- Default model ordering is the primary key; this well has exactly one row,
    -- asserted by the count in X5 so "first" cannot silently become ambiguous.
    SELECT wip.fraction
      FROM wells_wellirrigatedparcel wip
      JOIN pin ON wip.well_id = pin.well_id
     ORDER BY wip.id LIMIT 1
),
pinned_monitoring AS (
    SELECT mw.reference_elevation_ft
      FROM wells_monitoringwell mw JOIN pin ON mw.well_id = pin.well_id
),

-- ── Recharge ────────────────────────────────────────────────────────────────
pinned_site AS (
    SELECT rs.id, rs.name, rs.capacity_acre_feet
      FROM recharge_rechargesite rs JOIN pin ON rs.id = pin.recharge_site_id
),
pinned_measurement AS (
    SELECT m.value
      FROM recharge_rechargemeasurement m
      JOIN pin ON m.recharge_site_id = pin.recharge_site_id
     ORDER BY m.measurement_date DESC LIMIT 1
),
pinned_event AS (
    SELECT e.volume_acre_feet
      FROM recharge_rechargeevent e
      JOIN pin ON e.recharge_site_id = pin.recharge_site_id
     ORDER BY e.start_date DESC LIMIT 1
),
first_site_by_name AS (
    SELECT rs.capacity_acre_feet
      FROM recharge_rechargesite rs ORDER BY rs.name LIMIT 1
),

-- ── Setup ───────────────────────────────────────────────────────────────────
pinned_boundary AS (
    SELECT b.id, b.name, b.area_sq_miles, b.geometry
      FROM geography_boundary b JOIN pin ON b.id = pin.boundary_id
),

-- ── Datasync ────────────────────────────────────────────────────────────────
-- There is nothing to recompute: the tables behind the station detail pane are
-- empty, so the pane has no instance and the four figures never render. These
-- rows carry the COUNTS instead of a value, which is the finding itself.
datasync_shape AS (
    SELECT (SELECT count(*) FROM datasync_monitoredstation)  AS stations,
           (SELECT count(*) FROM datasync_datarecordstaging) AS records,
           (SELECT count(*) FROM datasync_datasource)        AS sources
),

-- ── The eighteen figures ────────────────────────────────────────────────────
figures AS (
    -- Datasync: four figures with no instance to render. `recomputed` is the
    -- number of station rows that exist, which is zero.
    SELECT 'FIG-datasync-001' AS id,
           'Station location, latitude (no station exists)' AS label,
           stations::numeric AS recomputed FROM datasync_shape
    UNION ALL SELECT 'FIG-datasync-002',
           'Station location, longitude (no station exists)',
           stations::numeric FROM datasync_shape
    UNION ALL SELECT 'FIG-datasync-003',
           'Current reading value (no station exists)',
           stations::numeric FROM datasync_shape
    UNION ALL SELECT 'FIG-datasync-004',
           'Recent record value (no published record exists)',
           records::numeric FROM datasync_shape

    -- Geography
    UNION ALL SELECT 'FIG-geography-001',
           'Zone 2 WY 2025-2026 Allocation (AF)',
           round(allocation_acre_feet, 2) FROM pinned_alloc
    UNION ALL SELECT 'FIG-geography-002',
           'Zone 2 WY 2025-2026 Used (AF), labelled pumped',
           round(used, 2) FROM zone_used
    UNION ALL SELECT 'FIG-geography-003',
           'Zone 2 WY 2025-2026 Remaining (AF)',
           round((SELECT allocation_acre_feet FROM pinned_alloc) - used, 2)
      FROM zone_used
    UNION ALL SELECT 'FIG-geography-004',
           'Zone 2 parcel MER-APN-026 Area (acres)',
           round(p.area_acres, 2)
      FROM parcels_parcel p JOIN pin ON p.id = pin.parcel_id

    -- Recharge
    UNION ALL SELECT 'FIG-recharge-001',
           'El Nido Recharge Basin 1 Capacity (AF)',
           round(capacity_acre_feet, 2) FROM pinned_site
    UNION ALL SELECT 'FIG-recharge-002',
           'El Nido Recharge Basin 1 newest measurement Value',
           round(value, 2) FROM pinned_measurement
    UNION ALL SELECT 'FIG-recharge-003',
           'El Nido Recharge Basin 1 newest event Volume (AF)',
           round(volume_acre_feet, 2) FROM pinned_event
    UNION ALL SELECT 'FIG-recharge-004',
           'Recharge list first row Capacity, whole AF',
           round(capacity_acre_feet, 0) FROM first_site_by_name

    -- Setup
    UNION ALL SELECT 'FIG-setup-001',
           'Confirmation page Area, square miles (page not reachable)',
           round(area_sq_miles::numeric, 1) FROM pinned_boundary
    UNION ALL SELECT 'FIG-setup-002',
           'Wizard boundary option Area, square miles',
           round(area_sq_miles::numeric, 1) FROM pinned_boundary

    -- Wells
    UNION ALL SELECT 'FIG-wells-001',
           'Well MER-W-001 irrigated parcel Fraction',
           round(fraction, 2) FROM pinned_wip
    UNION ALL SELECT 'FIG-wells-002',
           'Well MER-W-001 Reference elevation (ft)',
           round(reference_elevation_ft, 1) FROM pinned_monitoring
    UNION ALL SELECT 'FIG-wells-003',
           'Well MER-W-001 Year Pumping Began',
           round(year_pumping_began::numeric, 0) FROM pinned_well
    UNION ALL SELECT 'FIG-wells-004',
           'Well MER-W-001 Capacity (gpm)',
           round(capacity_gpm, 2) FROM pinned_well
),

-- ── Cross-checks: these start somewhere the views do not ─────────────────────
crosschecks AS (
    -- X1. Double membership. 76 parcels, 135 ParcelZone rows. This is the other
    -- end of section 1's finding that the dashboard's zone table sums to
    -- 31,223.56 AF against the panel's 17,458.35 AF.
    SELECT 'X1-parcels-total' AS id,
           'Parcels in the district' AS label,
           (SELECT count(*)::numeric FROM parcels_parcel) AS recomputed
    UNION ALL SELECT 'X1-memberships', 'Parcel-to-zone membership rows',
           (SELECT count(*)::numeric FROM geography_parcelzone)
    UNION ALL SELECT 'X1-parcels-in-two-zones', 'Parcels belonging to two zones or more',
           (SELECT count(*)::numeric FROM (
                SELECT parcel_id FROM geography_parcelzone
                 GROUP BY parcel_id HAVING count(*) > 1) t)

    -- X2. THE ONE THAT DISAGREES. The zone page labels FIG-geography-002
    -- "pumped". If that label were true the figure would equal the groundwater
    -- component alone. Decompose it and see.
    UNION ALL SELECT 'X2-used-as-rendered', 'Zone 2 Used, as the page computes it',
           (SELECT round(used, 2) FROM zone_used)
    UNION ALL SELECT 'X2-used-groundwater-only', 'Zone 2 Used, groundwater rows only',
           (SELECT round(used_gw_only, 2) FROM zone_used)
    UNION ALL SELECT 'X2-used-surface-deliveries', 'Zone 2 surface canal deliveries inside that figure',
           (SELECT round(used_surface, 2) FROM zone_used)
    UNION ALL SELECT 'X2-remaining-if-groundwater-only', 'Zone 2 Remaining if Used meant groundwater',
           (SELECT round((SELECT allocation_acre_feet FROM pinned_alloc) - used_gw_only, 2)
              FROM zone_used)

    -- X3. The suppression guard again, on this section's rows. Section 1 found
    -- it inert on the account and zone tables; this is the same question asked
    -- of the zone page's own ledger slice.
    UNION ALL SELECT 'X3-et-estimate-rows', 'et_estimate rows in the zone page slice',
           (SELECT count(*)::numeric FROM zone_ledger WHERE source_type = 'et_estimate')
    UNION ALL SELECT 'X3-rows-suppressed', 'Rows the authority ladder actually suppressed',
           ((SELECT count(*) FROM zone_ledger)::numeric - (SELECT count(*) FROM zone_billable))

    -- X4. The boundary's stated area against its own polygon. The platform
    -- refuses to compute this (setup/boundaries.py:120-126); the database can.
    -- Geodesic area on the WGS84 spheroid, divided by square metres per square
    -- mile.
    UNION ALL SELECT 'X4-area-stated', 'Boundary area as the file states it, sq mi',
           (SELECT round(area_sq_miles::numeric, 3) FROM pinned_boundary)
    UNION ALL SELECT 'X4-area-from-polygon', 'Boundary area computed from the stored polygon, sq mi',
           (SELECT round((ST_Area(geometry::geography) / 2589988.110336)::numeric, 3)
              FROM pinned_boundary)

    -- X5. The pins are unambiguous. A "first row" pin is only reproducible if
    -- the ordering has no tie at the top.
    UNION ALL SELECT 'X5-well-32-irrigated-parcels', 'Irrigated-parcel rows on the pinned well',
           (SELECT count(*)::numeric FROM wells_wellirrigatedparcel wip
             JOIN pin ON wip.well_id = pin.well_id)
    UNION ALL SELECT 'X5-site-6-events-newest-tie', 'Events sharing the newest start date on site 6',
           (SELECT count(*)::numeric FROM recharge_rechargeevent e JOIN pin ON e.recharge_site_id = pin.recharge_site_id
             WHERE e.start_date = (SELECT max(e2.start_date) FROM recharge_rechargeevent e2
                                    JOIN pin p2 ON e2.recharge_site_id = p2.recharge_site_id))
    UNION ALL SELECT 'X5-site-6-measurements-newest-tie', 'Measurements sharing the newest timestamp on site 6',
           (SELECT count(*)::numeric FROM recharge_rechargemeasurement m JOIN pin ON m.recharge_site_id = pin.recharge_site_id
             WHERE m.measurement_date = (SELECT max(m2.measurement_date) FROM recharge_rechargemeasurement m2
                                          JOIN pin p2 ON m2.recharge_site_id = p2.recharge_site_id))
    UNION ALL SELECT 'X5-boundary-rows', 'Boundary rows the wizard dropdown can offer',
           (SELECT count(*)::numeric FROM geography_boundary)

    -- X6. Datasync, stated plainly. The demonstration shape file pins
    -- MonitoredStation at 335 and DataRecordStaging at 30217, both tolerance
    -- zero (data/demo/expected_shape.json). This is what the database holds.
    UNION ALL SELECT 'X6-stations', 'MonitoredStation rows (shape file pins 335)',
           (SELECT stations::numeric FROM datasync_shape)
    UNION ALL SELECT 'X6-records', 'DataRecordStaging rows (shape file pins 30217)',
           (SELECT records::numeric FROM datasync_shape)
    UNION ALL SELECT 'X6-sources', 'DataSource rows (shape file pins 8)',
           (SELECT sources::numeric FROM datasync_shape)

    -- X7. The second row of the zone page's table, so the pin's neighbour is on
    -- the record too and the wet year can be compared without re-deriving it.
    UNION ALL SELECT 'X7-zone2-wy2025-used', 'Zone 2 WY 2024-2025 Used (AF), as the page computes it',
           (SELECT abs(coalesce(SUM(pl.amount_acre_feet)
                       FILTER (WHERE pl.amount_acre_feet < 0), 0))
              FROM parcels_parcelledger pl
              JOIN geography_parcelzone pz ON pz.parcel_id = pl.parcel_id
             WHERE pz.zone_id = 2 AND pl.reporting_period_id = 1)
)

SELECT id, label, recomputed FROM figures
UNION ALL
SELECT id, label, recomputed FROM crosschecks
ORDER BY id;

-- ── X8. The whole Used column, every zone, WY 2025-2026 ──────────────────
-- FIG-geography-002 renders once per zone per allocation, so the pinned row is
-- one of sixteen. This is the same figure computed for all eight zones in the
-- dry year, with the branch the view takes on each (GW at geography/views.py:197,
-- SW at :205) and, for the groundwater zones, how much of "pumped" is surface
-- canal delivery. Its own statement, because seven numbers a row do not fit the
-- three-column shape above.
WITH zone_all AS (
    SELECT z.id AS zone_id, z.name AS zone_name,
           upper(coalesce(wt.code, '')) AS wt_code,
           ap.allocation_acre_feet
      FROM geography_zone z
      JOIN accounting_allocationplan ap ON ap.zone_id = z.id
      JOIN accounting_watertype wt ON wt.id = ap.water_type_id
     WHERE ap.reporting_period_id = 2
),
zone_all_ledger AS (
    SELECT za.zone_id, pl.source_type, pl.amount_acre_feet
      FROM zone_all za
      JOIN geography_parcelzone pz ON pz.zone_id = za.zone_id
      JOIN parcels_parcelledger pl ON pl.parcel_id = pz.parcel_id
     WHERE pl.reporting_period_id = 2
),
zone_all_used AS (
    SELECT zone_id,
           abs(coalesce(SUM(amount_acre_feet)
               FILTER (WHERE amount_acre_feet < 0), 0)) AS gw_branch,
           abs(coalesce(SUM(amount_acre_feet)
               FILTER (WHERE source_type = 'surface_diversion'), 0)) AS sw_branch,
           abs(coalesce(SUM(amount_acre_feet)
               FILTER (WHERE amount_acre_feet < 0
                         AND source_type <> 'surface_diversion'), 0)) AS gw_rows_only
      FROM zone_all_ledger GROUP BY zone_id
)
SELECT za.zone_id,
       za.zone_name,
       za.wt_code AS branch,
       round(za.allocation_acre_feet, 2) AS allocation,
       round(CASE WHEN za.wt_code = 'GW' THEN u.gw_branch ELSE u.sw_branch END, 2) AS used_as_shown,
       round(za.allocation_acre_feet
             - CASE WHEN za.wt_code = 'GW' THEN u.gw_branch ELSE u.sw_branch END, 2) AS remaining_as_shown,
       round(CASE WHEN za.wt_code = 'GW' THEN u.sw_branch ELSE 0 END, 2) AS surface_inside_used,
       round(CASE WHEN za.wt_code = 'GW' THEN u.gw_rows_only ELSE 0 END, 2) AS groundwater_inside_used
  FROM zone_all za
  JOIN zone_all_used u ON u.zone_id = za.zone_id
 ORDER BY za.zone_id;
