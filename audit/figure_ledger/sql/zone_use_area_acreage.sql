-- FIG-geography-011: the Assigned use areas footer's acreage total on the
-- zone page (`templates/geography/partials/_zone_parcels.html`), 143-06 Task 4.
--
-- geography/views.py::_zone_parcels_context computes this with a `Sum`
-- aggregate over the zone's ParcelZone rows' `parcel__area_acres`, NULL
-- areas excluded by `Sum` itself. This file re-derives the same total from the
-- base tables, outside the ORM, so the two readings cannot share a bug.
--
-- INDEPENDENCE. Tables and columns only. Runs on the host through
-- audit/figure_ledger/run_sql.sh, outside the process that owns the ORM.
--
-- Pinned: zone_id = 2 (Halvern Irrigation-Urban GSA). Measured 2026-09-12:
-- 23 use areas, 375.16 acres, the same 23 and 375.16 the page's tfoot reads.
-- Also cross-checks against `zone_budget_basis.sql`'s `zone_size` CTE, which
-- computes the identical join for every zone (its own `acres` column for this
-- zone is 375.16 on both period rows, since acreage does not change by period).

\set ON_ERROR_STOP on

SELECT pz.zone_id,
       COUNT(*) AS use_areas,
       COUNT(pr.area_acres) AS use_areas_with_area,
       round(SUM(pr.area_acres), 2) AS acreage_total
  FROM geography_parcelzone pz
  JOIN parcels_parcel pr ON pr.id = pz.parcel_id
 WHERE pz.zone_id = 2
 GROUP BY pz.zone_id;
