---
phase: 02-core-domain-models
plan: 01
subsystem: database
tags: [django, django-allauth, geodjango, postgis, rbac]

requires:
  - phase: 01-infrastructure-scaffold
    provides: Django project skeleton with core.User stub, PostGIS, split settings

provides:
  - User model with agency_admin, phone, title fields
  - Role and UserRole RBAC tables
  - SiteConfig singleton with OAuth toggle
  - Boundary, Zone, ZoneGroup, ParcelZone geography models
  - django-allauth wired for email and Google OAuth

affects: [02-core-domain-models, 03-parcel-well-crud, 04-water-accounting]

tech-stack:
  added: [django-allauth (account, socialaccount, google provider)]
  patterns: [singleton model with save() override, cross-app FK via string reference, GeoDjango spatial fields]

key-files:
  created: [geography/__init__.py, geography/apps.py, geography/admin.py, geography/models.py]
  modified: [core/models.py, config/settings/base.py, config/urls.py]

key-decisions:
  - "SiteConfig singleton enforced via save() ValidationError, not metaclass"
  - "ParcelZone uses string FK 'parcels.Parcel' for cross-app resolution at migration time"
  - "Zone uses choices tuple for zone_type (management_area/subbasin/custom)"

patterns-established:
  - "Singleton pattern: raise ValidationError in save() if pk is None and objects exist"
  - "Cross-app ForeignKey: always use string reference for deferred resolution"
  - "GeoDjango: MultiPolygonField(srid=4326) for all boundary/zone geometries"

issues-created: []

duration: 2min
completed: 2026-05-23
---

# Phase 2 Plan 1: Core and Geography Models Summary

**8 foundation models (4 core + 4 geography) with django-allauth email/OAuth auth wired into settings, middleware, and URLs**

## Performance

- **Duration:** 2 min
- **Started:** 2026-05-24T00:00:03Z
- **Completed:** 2026-05-24T00:01:40Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Expanded User model with agency_admin, phone, title fields on top of AbstractUser
- Created Role + UserRole for role-based access control with unique constraint
- SiteConfig singleton stores per-agency settings (name, timezone, SRID, OAuth toggle)
- Geography app: Boundary, Zone, ZoneGroup, ParcelZone with GeoDjango spatial fields
- django-allauth fully wired: email auth, Google OAuth provider, AccountMiddleware

## Task Commits

Each task was committed atomically:

1. **Task 1: Expand core app models and wire allauth** - `6b289b3` (feat)
2. **Task 2: Create geography app with spatial models** - `066aea9` (feat)

## Files Created/Modified
- `core/models.py` - User, Role, UserRole, SiteConfig models
- `config/settings/base.py` - allauth + geography in INSTALLED_APPS, middleware, auth backends, allauth settings
- `config/urls.py` - allauth URLs at /accounts/
- `geography/__init__.py` - App package init
- `geography/apps.py` - GeographyConfig with BigAutoField
- `geography/admin.py` - Empty admin (registration deferred to 02-05)
- `geography/models.py` - Boundary, Zone, ZoneGroup, ParcelZone with spatial fields

## Decisions Made
- SiteConfig singleton uses save() override with ValidationError rather than a metaclass or database constraint
- ParcelZone FK to parcels.Parcel uses string reference so Django resolves it when the parcels app exists at migration time
- Zone zone_type uses CharField with choices (management_area, subbasin, custom) rather than a separate lookup table

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- All 8 foundation models defined and ready for dependent apps in plans 02-02 through 02-03
- Migrations deferred to 02-04 so all cross-app ForeignKeys resolve in a single pass
- django-allauth ready for template styling in 02-06

---
*Phase: 02-core-domain-models*
*Completed: 2026-05-23*
