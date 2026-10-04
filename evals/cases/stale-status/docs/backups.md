# Backups

## Local

restic backs up `/srv` every night at 03:00 to the repository on the second
disk, `/mnt/backup/restic`. The repository is checked on Sundays at 05:00.

## Offsite (planned)

Not set up yet. The plan is to copy the local repository to Backblaze B2
every Sunday at 06:00 with `restic copy`, started by `restic-offsite.timer`.
Until then, losing both disks at once loses every backup.
