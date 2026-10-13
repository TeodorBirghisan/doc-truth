# doc-truth report for `homeserver`

**4 findings: 3 confirmed, 1 suspect.** 2 probes failed. 2 findings dropped.

Checked 2026-10-13 07:05:09 UTC by doc-truth 0.1.0: 2 docs, 4 probes.
Models: claude-sonnet-5-5, claude-haiku-5-5 (2 calls, 15,210 tokens in, 1,020 out, $0.04 as reported by Claude Code).

## Confirmed

### Backup timer runs at 03:00, not 02:00

Contradiction · likely fix: edit the doc

`docs/operations.md:3` says:

> restic backs up nightly at 02:00

Probe `systemd-timers` printed:

```text
*-*-* 03:00:00
```

Why: The evidence shows otherwise.

### node_exporter is version 1.9.1, not 1.8.2

Contradiction · likely fix: edit the doc

`docs/operations.md:12-13` says:

> Monitoring uses `node_exporter`
> 1.8.2.

Probe `exporter` printed:

````text
node_exporter, version 1.9.1 ```
````

Why: ```json The doc pins 1.8.2; the binary reports 1.9.1.

### The apt notes still call noble-updates manual

Cross-doc contradiction · likely fix: edit the doc

`docs/apt.md:4` says:

> noble-updates is installed by hand

`docs/operations.md:20-21` says:

> Since 2026-08-24 it also installs
> noble-updates.

Why: The evidence shows otherwise.

## Suspect

### Unattended upgrades may run on another schedule

Stale status · likely fix: change the host

`docs/operations.md:9` says:

> Upgrades run every Sunday.

Probe `apt-timers` printed:

```text
apt-daily-upgrade.timer
```

Why: The timer exists, but its schedule isn't shown.

## Failed probes

A failed probe is no evidence, so no finding rests on one. Claims that only these probes could check went unchecked.

- `user-timers`: exit code 1 is not in success-exit-codes [0]
- `sitemap`: timed out after 15s

## Dropped findings

The model reported these too, but their quotes didn't check out, so they are left out of the counts and the exit code.

### No user timers are set up

- evidence: probe "user-timers" failed, so it is no evidence

The model's doc quote, for "docs/operations.md:30":

```text
User timers back up the laptop.
```

The model's evidence quote, for probe "user-timers":

```text
0 timers listed.
```

### Caddy listens on 8443

- doc: "docs/net`work.md" is not one of the checked docs
- evidence: no probe is called "caddy\n\"ports\""

The model's doc quote, for "docs/net`work.md:2":

```text
Caddy listens on 443
```

The model's evidence quote, for probe "caddy\n\"ports\"":

````text
```
:8443
````

## Docs checked

- `docs/operations.md`
- `docs/apt.md`
