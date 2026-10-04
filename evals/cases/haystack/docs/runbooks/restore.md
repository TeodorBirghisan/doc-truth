# Runbook: restoring data

All restores come from the restic repository on `/mnt/backup/restic`. If the
backup disk is gone, use the copy in Backblaze B2 instead: it has the same
snapshots, up to the last Sunday.

Load the repository settings first: `sudo -i`, then
`set -a; . /etc/restic/env; set +a`.

## A single file

1. Run `restic snapshots --path /srv` and pick a snapshot.
2. Run `restic restore <snapshot> --target /tmp/restore --include /srv/path/to/file`.
3. Copy the file back and fix its owner.

## The Nextcloud database

1. Run `docker compose stop nextcloud`.
2. Restore `/srv/dumps/nextcloud.sql.gz` from the snapshot you want.
3. Run `gunzip -c nextcloud.sql.gz | docker compose exec -T nextcloud-db psql -U nextcloud`.
4. Run `docker compose start nextcloud`, then
   `docker compose exec -u www-data nextcloud php occ maintenance:data-fingerprint`.

## The Immich database

The same as for Nextcloud, with `/srv/dumps/immich.sql.gz` and the `immich-db`
container. Stop `immich-server` first.

## Vaultwarden

1. Run `docker compose stop vaultwarden`.
2. Restore `/srv/vaultwarden/data` from the snapshot you want.
3. Run `docker compose start vaultwarden` and log in to check.

Restores are tested once a quarter. The last test, on 2026-09-06, restored the
Vaultwarden data and one Nextcloud folder.
