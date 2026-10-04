# Decisions

## 2026-03: Ubuntu 24.04 instead of Proxmox

One machine and a handful of containers: a hypervisor would add a layer
without adding anything we need. Revisit if we ever want Home Assistant OS.

## 2026-04: restic instead of Duplicati

Duplicati's local database corrupted twice in 2025, and each restore test took
hours. restic's repository format is simple and `restic check` is fast. The
old Duplicati backups were deleted in June after three months of overlap.

## 2026-05: Jellyfin instead of Plex

Plex started requiring an account for local streaming. Jellyfin does
everything we used Plex for, without an account.

## 2026-06: Media and monitoring stay off the internet

Jellyfin and Uptime Kuma are only reachable on the tailnet, through
`tailscale serve`. Nothing about them needs to be public, and every public
service is one more thing to keep patched.

## 2026-08: Timeshift for the system disk

restic covers `/srv`, but a broken update on `/` still meant a reinstall.
Timeshift keeps 3 daily snapshots of `/` and a boot snapshot. Its hourly check
only runs between 09:00 and 21:00, so it never overlaps the night jobs.

## 2026-09: Offsite copy to Backblaze B2

A fire or a theft would take both disks. `restic-offsite.timer` has copied the
repository to B2 every Sunday since 2026-09-13. Storage costs about 6 EUR a
month.
