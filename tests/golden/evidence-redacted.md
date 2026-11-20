# Evidence from host `homeserver`

Collected 2026-10-04 12:04:19 UTC by doc-truth 0.1.0, running as user `ops`. The host's local time zone is EEST (UTC+03:00).

Each section below shows a read-only command from the config file and what it printed on this host. A probe marked PROBE FAILED produced no usable evidence: nothing can be concluded from it, least of all that something is missing.

Text shown as `[REDACTED:…]` was hidden by doc-truth before you saw it, because it looked like a secret. It shows nothing about the value that was there: never report it as a value, and treat a claim that only the hidden text could check as unchecked, not contradicted.

## systemd-timers

```sh
systemctl list-timers --all --no-pager
```

Notes:

> Lists system timers only.
>
> User timers need their own probe.

Exit code 0.

Standard output:

```text
restic-backup.timer  *-*-* 03:00:00
```

## backup-unit

```sh
systemctl show -p Environment restic-backup.service
```

Exit code 0.

Standard output:

```text
Environment=RESTIC_REPOSITORY=/srv/restic RESTIC_PASSWORD=[REDACTED:assignment]
```

Standard error:

```text
Authorization: Bearer [REDACTED:authorization]
```
