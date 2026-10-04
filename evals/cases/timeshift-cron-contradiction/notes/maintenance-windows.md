# Maintenance windows

The restic backup at 03:00 and the repository check on Sundays at 05:00 are
the heavy jobs of the night. Timeshift snapshots are kept away from them.

Timeshift's hourly check was restricted on 2026-09-12:
`/etc/cron.d/timeshift-hourly` is now `0 9-21 * * *`, so no snapshot starts
between 22:00 and 09:00.
