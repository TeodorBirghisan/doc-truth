# Probe recipes

Ready-made `[[probes]]` tables for the claims ops docs make most often: when
jobs run, what happens when they fail, what a URL returns and which version
of a tool is installed. Copy the ones you need into your `doc-truth.toml`
and adjust the names, patterns and URLs. The
[configuration reference](configuration.md#probes) describes every key.

Each recipe has `notes` that tell the model what the output means and what
it can't show. Keep them when you copy a recipe, and add what's specific to
your host.

The recipes are written for Linux with systemd, and the cron recipe for
Debian and Ubuntu. doc-truth's test suite runs every recipe and checks the
shape of its output: the HTTP recipe against a local web server, the others
on the host the tests run on. A recipe the host can't run, such as
`restic-version` without restic installed, is skipped.

## Scheduled jobs

### systemd timers: last and next runs

```toml
[[probes]]
name = "systemd-timers"
command = "systemctl list-timers --all --no-pager"
notes = """
System timers only; user timers need their own probe.
LEFT and PASSED are relative to when the probe ran.
"""
```

`--all` includes timers that are loaded but not running, which have no next
run. The NEXT column shows when a timer fires, not the rule behind it: a
`RandomizedDelaySec` moves it, and a doc that says "daily at 06:00" can't
be checked against a single date. Add the next recipe for the rules.

### systemd timers: schedules

```toml
[[probes]]
name = "timer-schedules"
command = '''
systemctl list-units --type=timer --all --state=loaded --plain --no-legend --no-pager \
  | while read -r timer _ active state _; do
      triggers=$(systemctl show "$timer" -p TimersCalendar -p TimersMonotonic --value) || exit
      printf '%s %s %s %s\n' "$timer" "$active" "$state" "${triggers//$'\n'/ }"
    done \
  | sed 's/ ; next_elapse=[^}]*}/ }/g'
'''
notes = """
One line per loaded system timer: its name, its state, then each of its triggers
in braces. A waiting or running timer fires again. An elapsed one has no trigger
left until the next boot, and an inactive one is stopped: neither fires, whatever
its triggers say. OnCalendar is a calendar schedule, in the host's time zone unless
it names another. OnBootUSec, OnStartupUSec, OnActiveUSec, OnUnitActiveUSec and
OnUnitInactiveUSec are delays. A timer that isn't loaded isn't listed, and can't fire.
"""
```

It prints lines such as:

```text
apt-daily.timer active waiting { OnCalendar=*-*-* 06,18:00:00 }
fstrim.timer inactive dead { OnCalendar=Mon *-*-* 00:00:00 }
motd-news.timer active waiting { OnStartupUSec=1min } { OnCalendar=*-*-* 00,12:00:00 }
```

`systemctl show '*.timer' -p Id -p TimersCalendar` is shorter, but it prints
the properties in its own order, each on a line of its own, with the
schedule above the name of its timer. A finding that quotes the schedule
would then not show which timer it belongs to. The loop puts both on one
line.

`systemctl show` gives the schedule systemd actually uses, after every
drop-in. Reading the unit files would mean working out which file wins.

The `|| exit` matters. Without it, a `systemctl show` that fails inside the
loop leaves a timer with no triggers, and the probe still succeeds. The
`sed` drops systemd's `next_elapse`, which for a delay counts from boot
rather than giving a date, and would only mislead.

The state is the ACTIVE and SUB columns of `systemctl list-units`. A timer
with only `OnBootSec=` that has already fired is `active elapsed`: still
active, but it won't fire again until the next boot.

### systemd user timers

```toml
[[probes]]
name = "user-timers"
command = "XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user list-timers --all --no-pager"
notes = """
Timers of the user doc-truth runs as, not of other users.
LEFT and PASSED are relative to when the probe ran.
"""
```

`systemctl --user` finds the user's systemd instance through
`XDG_RUNTIME_DIR`, which a login session sets but a cron job or a system
service doesn't. Without it, the probe fails with
`Failed to connect to bus: No medium found`. Setting it in the command fixes
that, as long as the user's systemd instance is running: it runs while the
user is logged in, and all the time after `loginctl enable-linger <user>`.
If it isn't running, the probe fails, and doc-truth reports a failed probe,
not a host without user timers.

The schedules of user timers need `XDG_RUNTIME_DIR` for every `systemctl`
in the loop, so the command exports it first:

```toml
[[probes]]
name = "user-timer-schedules"
command = '''
export XDG_RUNTIME_DIR=/run/user/$(id -u)
systemctl --user list-units --type=timer --all --state=loaded --plain --no-legend --no-pager \
  | while read -r timer _ active state _; do
      triggers=$(systemctl --user show "$timer" -p TimersCalendar -p TimersMonotonic --value) || exit
      printf '%s %s %s %s\n' "$timer" "$active" "$state" "${triggers//$'\n'/ }"
    done \
  | sed 's/ ; next_elapse=[^}]*}/ }/g'
'''
notes = """
One line per loaded timer of the user doc-truth runs as: its name, its state, then
each of its triggers in braces. A waiting or running timer fires again. An elapsed
one has no trigger left until the next boot, and an inactive one is stopped: neither
fires, whatever its triggers say. OnCalendar is a calendar schedule, in the host's
time zone unless it names another. OnBootUSec, OnStartupUSec, OnActiveUSec,
OnUnitActiveUSec and OnUnitInactiveUSec are delays. A timer that isn't loaded isn't
listed, and can't fire.
"""
```

### What runs when a service fails

```toml
[[probes]]
name = "on-failure"
command = '''
systemctl list-units --type=service --all --state=loaded --plain --no-legend --no-pager \
  | while read -r service _; do
      on_failure=$(systemctl show "$service" -p OnFailure --value) || exit
      printf '%s OnFailure=%s\n' "$service" "$on_failure"
    done
'''
notes = """
One line per loaded system service, with the units systemd starts when it fails.
An empty OnFailure= means nothing is started. Restart= isn't shown: a service can
restart itself after a failure with an empty OnFailure=.
"""
```

Use `systemctl show`, not `systemctl cat`. `cat` prints the unit file and
its drop-ins as text, and an `OnFailure=` in a drop-in adds to the one in
the unit file, so no single file has the whole list. `show` prints the list
systemd ended up with.

`--state=loaded` keeps the loop to services that exist and aren't masked.
`--all` alone also lists names that other units mention but that have no
unit file, and `systemctl show` on such a name exits with 0 and an empty
`OnFailure=`. That reads like "nothing happens on failure" when the truth
is "no such service". For the same reason, `|| exit` fails the probe when
`systemctl show` fails, instead of printing an empty `OnFailure=`.

To keep the evidence short, list only the services your docs talk about
with a pattern after `--no-pager`, such as `'restic-*'`.

### cron

```toml
[[probes]]
name = "cron"
command = "grep -RHv -e '^[[:space:]]*#' -e '^[[:space:]]*$' /etc/crontab /etc/cron.d"
success-exit-codes = [0, 1]
notes = """
Every line of /etc/crontab and of the files in /etc/cron.d except comments and
blank lines, after the name of its file. Exit code 1 means there are no such lines.
cron skips a file in /etc/cron.d whose name has anything but letters, digits,
underscores and hyphens in it, such as a dot, a file not owned by root, a file
that group or others can write to, and files in subdirectories: their lines are
listed but never run. So is a last line with no newline at its end. File owners,
modes and missing final newlines aren't shown.
Not listed: the scripts in /etc/cron.hourly, cron.daily, cron.weekly and
cron.monthly, which the run-parts lines above or anacron run, and users' own crontabs.
"""
```

On Debian and Ubuntu, cron skips `/etc/cron.d/backup.cron` without a
word, because of the dot. A file a package or a person named that way is
easy to read as a live job. Other distributions have other rules; change the
notes to match yours.

`-R` follows symbolic links, which cron does too; `-r` would skip a job file
that's a link. `grep` exits with 1 when it finds no lines and 2 when it
can't read a file, so a missing or unreadable `/etc/cron.d` fails the probe
instead of looking like a host with no cron jobs. On hardened hosts where
only root can read `/etc/cron.d`, that's what happens unless doc-truth runs
as root.

User crontabs need a probe of their own, run as the user: `crontab -l`,
which exits with 1 when the user has no crontab.

## HTTP endpoints

```toml
[[probes]]
name = "sitemap"
command = "curl -q -sS -o /dev/null --max-time 10 -w 'status=%{http_code} type=%{content_type} redirect=%{redirect_url}' https://example.com/sitemap.xml"
timeout = 15
notes = "Status, content type and redirect target of a GET request. The body isn't recorded."
```

It prints a line such as `status=200 type=application/xml redirect=`.

Leave out `-f`. Without it, curl exits with 0 for any HTTP answer, so a 404
or a 500 is recorded as the evidence it is. With `-f`, curl exits with 22,
the probe fails, and the 404 never reaches the model. When there's no HTTP
answer at all, because the name doesn't resolve, the connection is refused
or it times out, curl exits with another code and the probe fails, as it
should. `-sS` keeps the progress bar out but still says on standard error
why curl failed.

`-q` has to come first: it makes curl ignore `~/.curlrc`, so a `--fail` or a
`--location` there can't change what the probe reports. `--max-time` sits
under the probe's `timeout`, so curl gives up and says why before doc-truth
stops it. It covers the whole answer, body included: a page that takes
longer to download fails the probe even after a 200, so raise both for big
files. A redirect is reported, not followed; add `-L` and
`%{url_effective}` to check the page it ends up on.

## Tool versions

One probe per tool, so a tool that's missing fails its own probe only.

```toml
[[probes]]
name = "restic-version"
command = "restic version"
notes = "The version of the restic found on PATH."
```

```toml
[[probes]]
name = "kubectl-version"
command = "kubectl version --client"
notes = "The version of the kubectl client, not of the cluster it talks to."
```

```toml
[[probes]]
name = "docker-version"
command = "docker --version"
notes = "The version of the docker client, not of the Docker Engine daemon."
```

Each tool has its own way to say its version:

- restic uses a `version` command.
- `kubectl version` without `--client` also asks the cluster for its
  version and fails when the cluster can't be reached.
- `docker version` also asks the Docker daemon and fails when it isn't
  running. `docker --version` only reports the client.

### Which binary?

doc-truth runs probes with the `PATH` it was started with. Under a systemd
service that's systemd's short default, without `~/.local/bin` and the other
directories a login shell adds. Under cron it's shorter still: `/usr/bin:/bin`,
without `/usr/local/bin`. A command that isn't found exits with 127,
and the probe fails. A failed probe is never evidence that the tool is
missing, because a missing `PATH` entry looks exactly the same.

When a tool is installed twice, the version your shell finds may not be the
one a job runs. Probe the binary the job uses, by its full path:

```toml
[[probes]]
name = "backup-restic-version"
command = "/usr/local/bin/restic version"
notes = "The restic binary that restic-backup.service runs."
```
