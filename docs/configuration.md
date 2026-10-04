# Configuration reference

doc-truth reads its settings from a TOML file, `doc-truth.toml` in the
current directory unless you pass `--config PATH`.

> [!NOTE]
> `doc-truth validate` checks this format and `doc-truth collect` runs the
> probes. `check`, which compares the docs with the evidence, is still being
> built. Where a setting only matters to it, this page says what it will do
> with it.

## Example

```toml
[[docs]]
path = "docs/operations.md"
notes = "Section 3 lists every scheduled job on this host."

[[docs]]
path = "runbooks/**/*.md"

[[probes]]
name = "systemd-timers"
command = "systemctl list-timers --all --no-pager"

[[probes]]
name = "backup-service"
command = "systemctl is-active restic-backup.service"
success-exit-codes = [0, 3]
notes = """
Exit code 3 means the service is inactive, its normal state between backups.
Exit code 4 means the unit doesn't exist, and still counts as a failure.
"""

[[probes]]
name = "sitemap"
command = "curl -s -o /dev/null -w '%{http_code} %{content_type}' https://example.com/sitemap.xml"
timeout = 15
notes = "Reports the HTTP status and content type only, not the body."
```

## Checking the file

```sh
doc-truth validate
```

`validate` reports every problem in the file together, each with its
location, such as `[[probes]] #2 "sitemap"`. Once the file itself is valid,
it checks that every `[[docs]]` path matches at least one file, and lists the
documents and probes it found. It exits with 0 when everything is valid and 2
when it isn't.

Keys are strict: an unknown key is an error, so a typo such as `timout` is
caught instead of silently ignored, with a suggestion for the key you probably
meant.

## `[[docs]]`

Each `[[docs]]` table names documents to check. At least one is required.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `path` | string | required | A file path or a glob pattern. |
| `notes` | string | none | Context for the model about these documents. |

### Paths and patterns

- Relative paths are resolved against the directory that contains the config
  file, not the directory you run doc-truth from. Absolute paths work too,
  and a leading `~` expands to the home directory of the user running
  doc-truth.
- A path without `*`, `?` or `[` must name a file that exists. Naming a
  directory is an error; use a pattern such as `docs/**/*.md` instead.
- In patterns, `*` matches any characters except `/`, `?` matches one
  character, `[abc]` matches one character from the set, and `**` matches any
  number of directories, including none: `runbooks/**/*.md` matches both
  `runbooks/backup.md` and `runbooks/dr/restore.md`.
- A pattern must match at least one file. Directories it matches are ignored.
- Hidden files and directories, whose names start with `.`, only match when
  the pattern spells out the dot, as in `.github/*.md`.
- Files matched by one pattern are taken in sorted order. A file matched by
  several entries is checked once and gets the notes of all of them.

### `notes`

`check` will give your notes to the model alongside the documents. Use them
for what the model can't work out by itself:

- Which document is meant to be complete, so that something missing from it
  counts as a finding: *"Section 3 lists every scheduled job on this host."*
- Which claims describe another machine, so they aren't checked against this
  one: *"Paths under ~/projects are on the workstation, not on this server."*

Notes can span several lines. Indentation that all lines share, and blank
lines at the start and end, are removed.

## `[[probes]]`

Each `[[probes]]` table is a command that collects evidence from the host. At
least one is required.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | required | Identifies the probe in the evidence and in findings. |
| `command` | string | required | The shell command to run. |
| `timeout` | number | `30` | Seconds to wait for the command before stopping it. |
| `success-exit-codes` | array of integers | `[0]` | Exit codes that mean the command worked. |
| `notes` | string | none | Context for the model about this probe's output. |

### `name`

1 to 64 characters: lowercase letters, digits, `.`, `_` and `-`, starting
with a letter or digit. Every probe needs its own name.

### `command`

`collect` runs the command on the host and records its output, its exit
code and anything it writes to standard error. [How probes run](#how-probes-run)
describes the shell and the environment it runs in.

> [!WARNING]
> The command runs with the permissions of the user who runs doc-truth, with
> no sandbox. Write commands that only read state, and review the config file
> the way you would review a script.

### `timeout` and `success-exit-codes`

A probe fails when it runs longer than `timeout`, which can be at most 3600
seconds, or exits with a code that isn't in `success-exit-codes`. A failed
probe is not evidence: `check` will tell the model that nothing can be
concluded from it, so a broken probe can't turn into a false "missing"
finding.

Some commands answer with their exit code. `grep` exits with 1 when nothing
matches, and `systemctl is-active` exits with 3 when a unit exists but isn't
running. List those codes in `success-exit-codes` when they are a valid
answer rather than a failure.

### `notes`

Tell the model what the output can't show, so it doesn't read an absence as
proof: *"Lists system timers only; user timers need their own probe."*

## How probes run

`doc-truth collect` runs the probes one at a time, in the order they appear
in the file. Each one runs:

- **With `bash -o pipefail`.** bash must be on `PATH`. With `pipefail`, a
  pipeline fails when any command in it fails, so in
  `systemctl list-timers | grep backup` a broken `systemctl` can't hide
  behind a working `grep`. The catch: a command that stops reading early,
  such as `head`, can make the command feeding it fail with exit code 141.
  Use `sed -n 1p` rather than `head -n 1`; it reads all of its input.
- **In the directory that contains the config file,** so relative paths in
  commands mean the same as relative paths in the config.
- **With your environment and three changes:**
  - `LC_ALL=C.UTF-8`, so messages are in English whatever the host's
    language, and UTF-8 text stays intact;
  - `LANGUAGE` removed, so translated messages can't come back through it;
  - `BASH_ENV` removed, so no startup file runs commands that aren't in the
    config.

  `TZ` is left alone, because docs give times in the host's local time. The
  evidence records the time zone.
- **With nothing on standard input,** so a command that waits for input gets
  end-of-file instead of hanging until its timeout.

A probe that runs longer than its `timeout` is stopped with `SIGTERM`, along
with every process it started, and whatever is still running 2 seconds later
gets `SIGKILL`. Processes a probe leaves running in the background are
stopped the same way when it finishes.

doc-truth keeps the first 1 MiB of a probe's standard output and the first
64 KiB of its standard error. A probe that prints more than 1 MiB is stopped
and fails, because a listing that was cut off can't show what's missing.
Standard error that was cut off is marked as such but doesn't fail the probe.
