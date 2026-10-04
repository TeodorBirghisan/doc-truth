# Evidence from host `core`

Collected 2026-10-04 12:04:19 UTC by doc-truth 0.1.0, running as user `teo`. The host's local time zone is EEST (UTC+03:00).

Each section below shows a read-only command from the config file and what it printed on this host. A probe marked PROBE FAILED produced no usable evidence: nothing can be concluded from it, least of all that something is missing.

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

## user-timers

**PROBE FAILED — not evidence of absence:** exit code 1 is not in success-exit-codes [0].

```sh
systemctl --user list-timers
```

Exit code 1.

Standard output was empty.

Standard error:

```text
Failed to connect to bus: No medium found
```

## slow

**PROBE FAILED — not evidence of absence:** timed out after 30s.

```sh
find / -name '*.timer'
```

Ended by SIGTERM.

Standard output:

```text
/etc/systemd/system/a.timer
```

## flood

**PROBE FAILED — not evidence of absence:** printed more than 1 MiB on standard output.

```sh
journalctl
```

Exit code 0.

Standard output:

```text
line
```

Standard output was cut off here; the rest was dropped.

Standard error:

```text
warning
```

Standard error was cut off here; the rest was dropped.

## missing

**PROBE FAILED — not evidence of absence:** could not start: No such file or directory.

```sh
true
```

## fenced

````sh
printf '```'
````

Exit code 0.

Standard output:

`````text
```
``x````
`````
