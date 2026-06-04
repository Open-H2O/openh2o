# Data archives

Point-in-time snapshots taken before a destructive demo cleanup, so the removed
data is restorable and reviewable. These are NOT part of any seed path — they are
safety nets, not fixtures.

## monitored-stations-2026-06-03.json

A full `dumpdata` of every `datasync.MonitoredStation` (321 rows) plus the 8
`datasync.DataSource` definitions, captured during Phase 53-01 just before the
248 out-of-basin monitoring stations were removed from the Merced demonstration
(they were statewide-discovery artifacts from earlier testing, not part of the
Merced basin demo).

The out-of-basin stations are also re-discoverable live via the platform's own
loaders (`auto_populate --boundary <name> --steps stations`), so this archive is
a convenience, not the only path back.

**Restore (same database):**

```
docker compose exec web python manage.py loaddata \
    data/archives/monitored-stations-2026-06-03.json
```

This re-inserts the stations by their original primary keys and re-links them to
the DataSource rows. Run it only on a database where those pks are free (e.g. a
fresh restore), or expect existing rows with the same pk to be overwritten.
