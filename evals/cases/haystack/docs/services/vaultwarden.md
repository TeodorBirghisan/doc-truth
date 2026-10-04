# Vaultwarden

Vaultwarden (`vaultwarden/server:1.34.3`) holds the family's passwords at
`https://vault.example.org`. Sign-ups are closed: new accounts are created by
invitation from the admin page.

- Data: `/srv/vaultwarden/data`, a SQLite database plus attachments.
- Admin page: `https://vault.example.org/admin`, protected by an Argon2 hash of
  the admin token in the compose file's environment.
- Health: `https://vault.example.org/alive` answers 200 with a JSON timestamp.
  Uptime Kuma checks it every minute.

## Backups

The SQLite database is backed up with the rest of `/srv` by the 03:00 restic
run. restic reads the file while Vaultwarden is running. Vaultwarden uses
SQLite's write-ahead log, and the restore test on 2026-09-06 opened the
database cleanly.

## Restoring

See `docs/runbooks/restore.md`.
