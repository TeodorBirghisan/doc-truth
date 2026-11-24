# Backups on homeserver

restic backs up `/srv` to the repository on the backup disk every night at 03:00,
started by `restic-backup.timer`.

## Settings

`restic-backup.service` sets everything restic needs in its environment:

- `RESTIC_REPOSITORY=/mnt/backup/restic`, the repository on the second disk;
- `RESTIC_PASSWORD=oak-river-lamp-42`, the repository password, also kept in the
  family password manager;
- `RESTIC_KEEP_DAILY=14`, so the nightly prune keeps two weeks of daily snapshots.

To change a setting, run `sudo systemctl edit restic-backup.service`, then start
the next backup by hand with `sudo systemctl start restic-backup.service`.
