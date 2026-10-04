# Runbook: replacing a disk

Use this when the SMART report shows reallocated or pending sectors, or when a
disk has failed.

## The data disk (`/srv`)

1. Make sure last night's backup succeeded:
   `cat /var/lib/restic-backup/last-success` should show today's date.
2. Stop the services: `cd /srv/compose && docker compose down`.
3. Shut down, swap the disk and boot.
4. Partition and format the new disk as ext4 with the label `srv`; the
   `/etc/fstab` entry mounts it at `/srv` by that label.
5. Restore: `restic restore latest --target / --include /srv`.
6. Start the services with `docker compose up -d`, then check every public
   address.

## The backup disk (`/mnt/backup`)

The offsite copy in Backblaze B2 holds the same snapshots, so nothing is lost
while the backup disk is out.

1. Swap the disk and format it as ext4 with the label `backup`.
2. Copy the repository back from B2 with `restic copy`.
3. Run `restic check` before the next scheduled backup.

## The system disk

Reinstall Ubuntu 24.04, restore `/etc` from the latest snapshot, and follow
`docs/runbooks/setup.md` from step 4.
