# Operations manual: homeserver

This manual describes `homeserver`, the family's home server. It is the first
place to look when something breaks. Whoever changes the server updates this
manual in the same sitting.

## 1. Hardware

| Part | Model | Notes |
|---|---|---|
| Board and CPU | ASRock N100DC-ITX, Intel N100 | 4 cores, about 6 W at idle |
| Memory | 32 GB DDR4 SO-DIMM | one module; the second slot is free |
| System disk | 250 GB NVMe | mounted at `/` |
| Data disk | 4 TB WD Red Plus | mounted at `/srv` |
| Backup disk | 4 TB Seagate IronWolf | mounted at `/mnt/backup` |
| UPS | APC Back-UPS 700 | about 20 minutes of runtime |

The case sits in the hallway cupboard, with the UPS on the shelf under it.
`apcupsd` shuts the server down cleanly when the UPS reports 5 minutes of
runtime left.

## 2. Operating system and access

- Ubuntu 24.04 LTS, installed in March 2026.
- Log in over SSH as `ops`, from the tailnet only. Password login and root
  login are disabled; `ops` uses `sudo`.
- Only SSH (22), HTTP (80) and HTTPS (443) listen on all interfaces.
  Everything else listens on loopback addresses only.
- The firewall is ufw. Incoming traffic is denied except on 22, 80 and 443,
  and 22 only accepts connections from the tailnet.

## 3. Services

Every service runs in Docker, from the compose file in `/srv/compose`. Caddy
terminates TLS for the public addresses and reaches the other containers over
the `web` Docker network. Their ports are also published on 127.0.0.1, for
local debugging and for `tailscale serve`.

| Service | Image | Local port | Public address |
|---|---|---|---|
| Caddy | `caddy:2.10.2` | 80, 443 | serves the addresses below |
| Nextcloud | `nextcloud:31.0.9-apache` | 8080 | `https://cloud.example.org` |
| Nextcloud database | `postgres:16.10` | 5432 | none |
| Nextcloud cache | `redis:7.4.6` | 6379 | none |
| Immich | `ghcr.io/immich-app/immich-server:v1.142.1` | 2283 | `https://photos.example.org` |
| Immich database | `ghcr.io/immich-app/postgres:16-vectorchord0.4.3` | none | none |
| Jellyfin | `jellyfin/jellyfin:10.10.7` | 8096 | none; tailnet only, through `tailscale serve` |
| Vaultwarden | `vaultwarden/server:1.34.3` | 8222 | `https://vault.example.org` |
| Uptime Kuma | `louislam/uptime-kuma:1.23.16` | 3001 | none; tailnet only, through `tailscale serve` |

Images are pinned to exact versions in the compose file. Updating one is a
deliberate change: edit the tag, run `docker compose pull` and
`docker compose up -d`, then update this table.

Uptime Kuma checks the three public addresses every minute and sends a
Telegram message when one fails twice in a row.

## 4. What runs automatically

Every job runs as a systemd timer from `/etc/systemd/system` or from a file in
`/etc/cron.d`. Times are local, Europe/Berlin.

| When | Job | Unit or file | Alerts on failure |
|---|---|---|---|
| daily 02:30 | Dump the Nextcloud database to `/srv/dumps/nextcloud.sql.gz` | `db-dump.timer` | yes |
| daily 02:40 | Dump the Immich database to `/srv/dumps/immich.sql.gz` | `immich-db-dump.timer` | yes |
| daily 03:00 | Back up `/srv` to the restic repository on `/mnt/backup` | `restic-backup.timer` | yes |
| Sundays 03:30 | Remove unused Docker images | `docker-image-prune.timer` | no |
| Sundays 04:30 | Reboot, only if an update needs it | `maintenance-reboot.timer` | no |
| Sundays 05:00 | Check the restic repository | `restic-check.timer` | yes |
| Saturdays 05:00 | Forget old snapshots and prune (7 daily, 4 weekly, 12 monthly) | `restic-prune.timer` | yes |
| Sundays 06:00 | Copy the restic repository to Backblaze B2 | `restic-offsite.timer` | yes |
| daily 07:00 | Import photos from the shared upload folder into Immich | `photo-import.timer` | yes |
| every 5 minutes | Nextcloud background jobs (`cron.php`) | `nextcloud-cron.timer` | yes |
| Mondays 08:00 | Mail a SMART report for all three disks | `smart-report.timer` | yes |
| hourly, 09:00–21:00 | Timeshift snapshot check (3 daily snapshots kept) | `/etc/cron.d/timeshift-hourly` | no |
| at boot, after 10 minutes | Timeshift boot snapshot | `/etc/cron.d/timeshift-boot` | no |

`/etc/cron.d/e2scrub_all` also exists. It ships with e2fsprogs and does nothing
on a systemd host, so it isn't listed.

"Alerts on failure" means the job's service has
`OnFailure=notify-failure@%n.service`, which sends a Telegram message.

## 5. Backups

- **What:** everything under `/srv`: the Docker volumes, the database dumps
  and the family's files.
- **Where:** a restic repository at `/mnt/backup/restic`, copied to Backblaze
  B2 every Sunday.
- **Proof it ran:** `restic-backup.service` writes the time of its last
  successful run to `/var/lib/restic-backup/last-success`.
- **Password:** in `/etc/restic/env`, and on paper in the fire safe.

Uptime Kuma alerts when `last-success` is more than 26 hours old.

## 6. Disks

| Mount | Size | Filesystem |
|---|---|---|
| `/` | 250 GB | ext4 |
| `/srv` | 4 TB | ext4 |
| `/mnt/backup` | 4 TB | ext4 |

The SMART report arrives every Monday morning. A reallocated sector count
above zero means: order a replacement disk and follow
`docs/runbooks/disk-replacement.md`.

## 7. Updates

- Ubuntu: unattended-upgrades installs security updates every evening.
  Kernel updates wait for the Sunday reboot.
- Docker images: by hand, as section 3 describes.
- restic comes from its GitHub release binary; Docker and Tailscale come from
  their own apt repositories. Their versions are in section 8.

## 8. Tool versions

| Tool | Version | Installed from |
|---|---|---|
| restic | 0.18.1 | GitHub release binary |
| Docker Engine | 28.4.0 | Docker's apt repository |
| Tailscale | 1.88.3 | Tailscale's apt repository |

## 9. When something breaks

1. Open Uptime Kuma, on the tailnet, to see what is down.
2. Run `docker compose ps` in `/srv/compose` to see which container stopped.
3. Run `journalctl -u <unit> -n 100` to see why a scheduled job failed.
4. If the server doesn't come back after a reboot, plug in a monitor: the
   board has HDMI on the back panel.
