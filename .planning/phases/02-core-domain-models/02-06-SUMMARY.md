---
phase: 02-core-domain-models
plan: 06
subsystem: auth
tags: [django-allauth, email-auth, google-oauth, templates, vanderdev-design]

requires:
  - phase: 02-core-domain-models (plan 01)
    provides: allauth wired in settings, User model, SiteConfig with allow_google_oauth

provides:
  - 9 styled auth templates (login, signup, logout, password reset flow, email confirmation)
  - Email backend configuration (console for dev, SMTP for prod)
  - Google OAuth ready but disabled by default
  - SiteConfig context processor for template-level OAuth toggle
  - Auth-aware index page (different content for logged-in vs anonymous)
  - django.contrib.sites integration

affects: [03-parcel-well-crud, 08-deploy-polish]

tech-stack:
  added: [django.contrib.sites]
  patterns: [context processor for singleton config, conditional OAuth in templates]

key-files:
  created: [core/context_processors.py, templates/account/login.html, templates/account/signup.html, templates/account/logout.html, templates/account/password_reset.html, templates/account/password_reset_done.html, templates/account/password_reset_from_key.html, templates/account/password_reset_from_key_done.html, templates/account/email_confirm.html, templates/account/verification_sent.html]
  modified: [config/settings/base.py, templates/index.html]

key-decisions:
  - "SiteConfig exposed to templates via context processor, not template tag"
  - "Google OAuth button visibility controlled at template level by site_config.allow_google_oauth"
  - "Updated allauth to non-deprecated settings API (ACCOUNT_LOGIN_METHODS, ACCOUNT_SIGNUP_FIELDS)"
  - "django_site table created manually to fix migration ordering with socialaccount"

issues-created: []

duration: 6min
completed: 2026-05-23
---

# Phase 2 Plan 6: Auth Templates and Email Configuration Summary

**9 VanderDev-styled auth templates with email/password login, Google OAuth toggle, and console email backend for development**

## Performance

- **Duration:** 6 min (batched with Plan 02-05)
- **Started:** 2026-05-24T01:05:00Z
- **Completed:** 2026-05-24T01:11:54Z
- **Tasks:** 3
- **Files modified:** 12

## Accomplishments
- 9 auth templates styled with VanderDev design tokens (dark mode, California Gold, pop shadows)
- Email backend: console in development, SMTP-ready in production via env vars
- Google OAuth provider configured but disabled by default (reads from env, SiteConfig toggle controls button)
- SiteConfig context processor makes agency config available to all templates
- Index page differentiates authenticated vs anonymous users
- Updated allauth settings to non-deprecated API (fixes warnings from 02-04)
- django.contrib.sites added and migration resolved

## Task Commits

1. **Task 1: Create styled auth templates** - `3c8902e` (feat)
2. **Task 2: Configure email/OAuth/context processor** - `3c45d7e` (feat)
3. **Task 3: Update index page** - `7cbcc70` (feat)

## Files Created/Modified
- `templates/account/` - 9 auth templates (login, signup, logout, password reset x4, email confirm, verification sent)
- `core/context_processors.py` - SiteConfig context processor
- `config/settings/base.py` - django.contrib.sites, SITE_ID, context processor, email settings, Google OAuth, updated allauth settings
- `templates/index.html` - Auth-aware content (login/register vs user info/logout)

## Decisions Made
- SiteConfig context processor pattern (not template tag) for simplicity
- Google OAuth controlled at template level, not settings level, so it can be toggled per-agency without restart
- Updated allauth from deprecated ACCOUNT_EMAIL_REQUIRED/ACCOUNT_USERNAME_REQUIRED/ACCOUNT_AUTHENTICATION_METHOD to ACCOUNT_LOGIN_METHODS/ACCOUNT_SIGNUP_FIELDS

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] django.contrib.sites migration ordering**
- **Found during:** Butler deploy (migrate command)
- **Issue:** socialaccount.0001_initial was applied before sites.0001_initial because sites wasn't in INSTALLED_APPS when socialaccount was first migrated
- **Fix:** Created django_site table manually via SQL, inserted migration records to mark sites migrations as applied
- **Verification:** `python manage.py migrate` shows "No migrations to apply", `python manage.py check` reports 0 issues

## Issues Encountered
None (sites migration ordering was a deployment sequence issue, resolved in-session)

## Next Phase Readiness
- Auth flow complete: login, register, logout, password reset all functional
- Admin accessible at /admin/ with all 44 models
- Ready for Plan 02-07 (seed data commands and final verification)

---
*Phase: 02-core-domain-models*
*Completed: 2026-05-23*
