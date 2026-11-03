# Operations manual: homeserver

Start here. This manual describes how this host runs from day to day: what runs
by itself, how to tell it worked, and what to do when it didn't. Everything in it
describes this host.

## 1. This host

An Ubuntu 24.04 server at home. It keeps the family's files and notes, and its own
backups on a second disk mounted at `/mnt/backup`. It's reached over SSH as `ops`,
with password login and root login disabled.

## 2. The day at a glance

The backup runs first, in the small hours, so the morning summary can report on it.
The summary is ready before anyone reads it, and the health check comes after both,
so it can see whether they worked.

## 3. What runs automatically

| When | Job | Mechanism | Check |
|---|---|---|---|
| daily 03:00 | Back up `/srv` to the restic repository | `restic-backup.timer` | `journalctl -u restic-backup.service` |
| Sundays 04:30 | Reboot, only if an update needs it | `maintenance-reboot.timer` | `last reboot` |
| Sundays 05:00 | Check the restic repository | `restic-check.timer` | `journalctl -u restic-check.service` |
| daily 07:30 | Write the morning summary | `morning-summary.timer` | `ls -l /srv/notes/summary` |
| daily 10:07 | Freshness checks: summary age, backup age, disk space | `health-check.timer` | `journalctl -u health-check.service` |
| every 15 minutes | Sync the notes folder | `notes-sync.timer` | `journalctl -u notes-sync.service` |
| hourly, 09:00–21:00 | Timeshift snapshot check (keeps 3 daily snapshots) | `/etc/cron.d/timeshift-hourly` | `sudo timeshift --list` |
| at boot, after 10 minutes | Timeshift boot snapshot | `/etc/cron.d/timeshift-boot` | `sudo timeshift --list` |

## 4. The morning summary

The summary is written by a script at 07:30 and saved in `/srv/notes/summary`. It
lists what the backup did overnight, what's due today and anything left over from
yesterday. It makes one network call and needs a valid login, so an expired login is
the usual reason it fails.

To see how the last run went, read `journalctl -u morning-summary.service`. A very
fast run, around two seconds, means the script gave up early, most often because of
that login. Log in again as `ops` and start the service by hand.

The job exits non-zero on failure, which sends an alert, and the 10:00 health check is
the freshness backstop. The summary itself is never edited by the job after it's
written, so a change you make by hand stays.

## 5. Backups

The backup runs at 03:00 and copies `/srv` into the restic repository on
`/mnt/backup`. The repository password is in `/etc/restic/env`, readable only by root.
restic is version 0.18.1, installed from the GitHub release binary rather than from
apt, because apt's version is too old for `restic copy`.

On Sundays at 05:00 a second job checks the repository. The check takes a few minutes
and reads part of the data each week, so all of it is read over a few months.

Snapshots are kept for 30 days. Pruning is a manual step, done after reading the check
job's output, because it can't be undone.

## 6. Restoring a file

Mount the latest snapshot with `restic mount /mnt/restore`, copy the file out, then
unmount it. Restoring a whole folder works the same way. Don't restore into `/srv`
directly while the notes sync is running: stop `notes-sync.timer` first and start it
again afterwards.

## 7. Timeshift

Timeshift keeps system snapshots, separate from the restic backups of the data. Its
hourly check runs from 09:00 to 21:00, and it takes a boot snapshot 10 minutes after
each boot. Never schedule another job that reads Timeshift on the hour, because
Timeshift runs one instance at a time, and the other job gets no output.

## 8. Notes sync

The notes folder syncs every 15 minutes through `notes-sync.timer`. Conflicts leave
both copies in place, with the other device's name in the second file's name. Search
for those names once a week, and merge them by hand.

## 9. Updates and reboots

Updates install by themselves overnight. When one needs a reboot, the machine doesn't
reboot right away: `maintenance-reboot.timer` does it on Sundays at 04:30, after the
backup and before the repository check. A kernel update can therefore wait up to a
week to take effect.

## 10. Alerts

A failed job sends one message to the family chat, naming the job. The 10:07 health
check also warns when the morning summary is older than a day, when the last backup is
older than two days, or when a disk is over 90% full. It doesn't repeat a warning until
the next day.

A warning from the health check doesn't mean the job failed today. Read the job's own
journal first, using the command in section 3.

## 11. When something looks wrong

1. Read the alert, which names the job.
2. Read that job's journal, using the command in section 3.
3. Fix the cause, then start the service by hand once to confirm it works.
4. If the disk is full, look in `/srv/tmp` first, which is safe to empty.
