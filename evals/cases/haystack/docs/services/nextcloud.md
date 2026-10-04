# Nextcloud

Nextcloud 31 runs from the `nextcloud:31.0.9-apache` image, with PostgreSQL 16
and Redis 7 next to it. Its data directory is `/srv/nextcloud/data`.

## Background jobs

Nextcloud's background jobs run every 5 minutes: `nextcloud-cron.timer` starts
`nextcloud-cron.service`, which runs `php -f /var/www/html/cron.php` inside the
container as `www-data`. The admin page shows "Cron (recommended)" as the
background job mode.

## Database dumps

`db-dump.timer` dumps the database every night at 02:30, half an hour before
the restic backup, to `/srv/dumps/nextcloud.sql.gz`. Only the latest dump is
kept on disk; restic keeps the history.

## Upgrading

Nextcloud only supports upgrading one major version at a time. To go from 31
to 32:

1. Read the release notes and check which apps aren't compatible yet.
2. Change the image tag in `/srv/compose/compose.yaml`.
3. Run `docker compose pull nextcloud && docker compose up -d nextcloud`.
4. Watch `docker compose logs -f nextcloud` until the upgrade finishes.
5. Update the services table in the operations manual.

## Status

`https://cloud.example.org/status.php` returns JSON with the version and
whether maintenance mode is on. Uptime Kuma checks it every minute.
