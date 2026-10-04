# Timeshift

Timeshift keeps 3 daily snapshots and takes a boot snapshot 10 minutes after
every boot.

## History

- Until 2026-09-12 the hourly check ran every hour, `0 * * * *`.
- 2026-09-12: restricted to `0 9-21 * * *` by editing
  `/etc/cron.d/timeshift-hourly`.
- 2026-09-19: found back at `0 * * * *`. Timeshift rewrites its own cron file
  on every `--check`, so editing the file could never stick.
- 2026-10-01: fixed in Timeshift's own settings. The cron file has been
  `0 9-21 * * *` since.
