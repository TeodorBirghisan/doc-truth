# Operations manual: homeserver

## 1. This host

An Ubuntu 24.04 server at home. It runs file sync and photo backup for the
family, and keeps its own backups on a second disk. Everything in this manual
describes this host.

## 2. Access

Log in over SSH as `ops`. Password login and root login are disabled.

## 3. What runs automatically

| When | Job | Mechanism | Check |
|---|---|---|---|
| daily 03:00 | Back up `/srv` to the restic repository on `/mnt/backup` | `restic-backup.timer` | `systemctl list-timers restic-backup.timer` |
| Sundays 04:30 | Reboot, only if an update needs it | `maintenance-reboot.timer` | `last reboot` |
| Sundays 05:00 | Check the restic repository | `restic-check.timer` | `journalctl -u restic-check.service` |
| daily 20:45 | Install security updates (`noble-security` and ESM) with unattended-upgrades; other updates are installed by hand | `apt-daily-upgrade.timer`, moved to 20:45 by a drop-in | `less /var/log/unattended-upgrades/unattended-upgrades.log` |

## 4. Restoring a file

Mount the latest snapshot with `restic mount /mnt/restore` and copy the file
out. The repository password is in `/etc/restic/env`.
