# Incidents

What went wrong, what it cost and what changed. Newest first.

## 2026-09-19: Timeshift ran at night again

The hourly Timeshift check was back at `0 * * * *`, a week after it was
restricted to 09:00–21:00. Timeshift rewrites `/etc/cron.d/timeshift-hourly`
on every check, so editing the file could never stick. Fixed on 2026-10-01
in Timeshift's own settings.

## 2026-08-28: Three nights without a backup

`/mnt/backup` came back read-only after a power cut, because of a filesystem
error. restic failed on 08-26, 08-27 and 08-28, and nobody noticed: failures
only went to the journal. `fsck` fixed the disk. Since 2026-08-29 the backup,
dump, import and Nextcloud jobs alert on failure through
`notify-failure@.service`.

## 2026-08-14: Nextcloud stuck in maintenance mode

An app update failed halfway and left Nextcloud in maintenance mode for a
morning. `occ maintenance:mode --off` fixed it. Uptime Kuma caught it within
two minutes, because `status.php` reports maintenance mode.

## 2026-07-30: The UPS battery

The UPS beeped for a day. Its battery was four years old and held 3 minutes
instead of 20. With a new battery, `apcupsd` reports about 20 minutes of
runtime again.

## 2026-06-02: Jellyfin was public for two days

A Caddyfile edit exposed Jellyfin at a public address by mistake. Nothing
suggests anyone found it. Since 2026-06-07, Jellyfin and Uptime Kuma are only
on the tailnet, through `tailscale serve`, and Caddy only serves cloud,
photos and vault.

## 2026-05-12: The data disk filled up

A manual Immich import duplicated a 300 GB folder and `/srv` reached 100%.
Nextcloud and Immich stopped accepting uploads until the duplicates were
removed. The automatic import added later, `photo-import.timer`, skips files
Immich already has.

## 2026-04-08: A restore test failed under Duplicati

Duplicati's database was corrupted again, and the restore test couldn't list
any backups. This was the reason for switching to restic (see the decisions,
2026-04).
