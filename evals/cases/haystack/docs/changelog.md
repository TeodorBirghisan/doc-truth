# Changelog

Newest first. Each line records a change on the day it was made.

- 2026-10-01: Timeshift's hourly check fixed at the source, in Timeshift's own
  settings. `/etc/cron.d/timeshift-hourly` now stays at `0 9-21 * * *`.
- 2026-09-27: Vaultwarden 1.34.1 to 1.34.3.
- 2026-09-20: Immich v1.141.0 to v1.142.1.
- 2026-09-19: Timeshift's hourly cron found back at `0 * * * *`. Timeshift
  rewrites its own cron file on every check.
- 2026-09-14: Tailscale 1.86.2 to 1.88.3.
- 2026-09-13: First offsite copy to Backblaze B2; `restic-offsite.timer`
  enabled for Sundays at 06:00.
- 2026-09-12: Timeshift's hourly check restricted to 09:00–21:00.
- 2026-09-06: Caddy 2.10.0 to 2.10.2.
- 2026-09-05: Nextcloud 31.0.7 to 31.0.9.
- 2026-08-30: SMART report moved from Sundays to Mondays at 08:00, so it
  arrives on a workday.
- 2026-08-29: `notify-failure@.service` added; the backup, dump, import and
  Nextcloud jobs alert on failure.
- 2026-08-23: Docker Engine 28.3.3 to 28.4.0.
- 2026-08-22: restic 0.18.0 to 0.18.1.
- 2026-08-16: Timeshift installed for the system disk: 3 daily snapshots and a
  boot snapshot.
- 2026-08-09: `restic-prune.timer` moved to Saturdays at 05:00, away from the
  Sunday check.
- 2026-08-02: restic backup moved from 01:00 to 03:00, after the database
  dumps.
- 2026-07-26: Database dumps added: Nextcloud at 02:30, Immich at 02:40.
- 2026-07-19: Uptime Kuma 1.23.13 to 1.23.16.
- 2026-07-12: Jellyfin 10.10.3 to 10.10.7.
- 2026-07-05: Nextcloud 30 to 31 (31.0.7).
- 2026-06-28: PostgreSQL 16.9 to 16.10 for Nextcloud.
- 2026-06-21: Redis 7.4.4 to 7.4.6.
- 2026-06-14: The old Duplicati backups deleted after three months of overlap
  with restic.
- 2026-06-07: `tailscale serve` set up for Jellyfin and Uptime Kuma; their
  ports are no longer published on all interfaces.
- 2026-05-31: Jellyfin replaces Plex.
- 2026-05-24: `photo-import.timer` added, daily at 07:00.
- 2026-05-17: Immich added at `https://photos.example.org`.
- 2026-05-10: Uptime Kuma added.
- 2026-05-03: Vaultwarden added at `https://vault.example.org`.
- 2026-04-26: restic 0.18.0 installed from the GitHub release binary.
- 2026-04-19: restic replaces Duplicati for `/srv`.
- 2026-04-12: The second 4 TB disk installed as `/mnt/backup`.
- 2026-04-05: Nextcloud moved from the snap to Docker.
- 2026-03-29: Caddy replaces nginx as the reverse proxy.
- 2026-03-22: Ubuntu 24.04 installed; the old Debian 11 install retired.
- 2026-03-15: New hardware: an ASRock N100DC-ITX board with 32 GB of memory.
