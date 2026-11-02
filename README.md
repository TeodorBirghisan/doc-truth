# doc-truth

[![CI](https://github.com/TeodorBirghisan/doc-truth/actions/workflows/ci.yml/badge.svg)](https://github.com/TeodorBirghisan/doc-truth/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Check what your operations docs claim against what your systems actually run.

> [!WARNING]
> **Pre-alpha. Nothing is released yet.** What this README describes works when
> installed from GitHub, but it hasn't finished its first long test on a real
> server, and the config and report formats can change before the first release.

Runbooks, ops manuals, READMEs and agent files such as `CLAUDE.md` make claims
about running systems: the backup runs nightly at 02:00, the service pages on
failure, the key lives at `~/.config/sops/age/keys.txt`, `/sitemap.xml` returns
XML. Systems change, and docs fall behind without anyone noticing. Reading the
docs again won't catch it. Only checking them against the live system will.

doc-truth runs read-only commands you declare to collect evidence from a host,
has a language model compare that evidence with the claims in your docs, and
writes a report of every place where the two disagree. It never changes your
docs or your system.

## Quick start

You need:

- Linux with bash. Probes run as bash commands; the examples use systemd and
  cron.
- [uv](https://docs.astral.sh/uv/), to install doc-truth. It downloads
  Python 3.14 or newer if your system doesn't have it.
- For `check` in v0.1: [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
  installed and logged in. doc-truth calls the `claude` CLI with all tools
  disabled.

doc-truth isn't on PyPI yet, so install it from GitHub:

```sh
uv tool install git+https://github.com/TeodorBirghisan/doc-truth
```

Write a small doc with a mistake in it, and a config with one probe that can
catch the mistake:

```sh
mkdir -p doc-truth-demo && cd doc-truth-demo

cat > operations.md <<'EOF'
# Operations

This host runs bash 3.2.
EOF

cat > doc-truth.toml <<'EOF'
[[docs]]
path = "operations.md"

[[probes]]
name = "bash-version"
command = "bash --version"
EOF
```

Check the config, then look at the evidence the model will get. Neither step
calls a model:

```sh
doc-truth validate
run=$(doc-truth collect)
cat "$run/evidence.md"
```

Now compare the doc with the host. This sends the doc and the evidence to the
model through your Claude Code login, and a check this small costs a cent or
two:

```sh
run=$(doc-truth check)
echo "exit code: $?"
cat "$run/report.md"
```

It should print `exit code: 1`, which means confirmed findings, and a report
with one finding: the probe printed a much newer bash than the doc claims.

To check your own docs, point `[[docs]]` at them and add probes for what they
claim. [Usage](#usage) explains the config and the commands, and the
[probe recipes](docs/probes.md) have tested probes for systemd timers, cron,
failure hooks, HTTP endpoints and tool versions.

## How it works

```
probes (doc-truth.toml) ──collect──▶ evidence ──┐
                                                ├──check──▶ findings ──verify──▶ report
your docs (Markdown) ───────────────────────────┘
```

1. **Collect.** doc-truth runs the probes from your config file: plain
   read-only shell commands such as `systemctl list-timers` or
   `docker --version`. It records each probe's output, exit code
   and errors in an evidence file. No model is involved, and the evidence file
   is in exactly the form a model sees.
2. **Check.** It puts the evidence and your docs, with line numbers, into one
   prompt. The model answers with structured findings. It gets no tools, so it
   cannot run commands, read other files or change anything.
3. **Verify.** Before a finding reaches the report, doc-truth checks that the
   doc quote is in the lines it cites and that the evidence quote is in the
   named probe's output. Runs of whitespace and curly quotes are ignored;
   everything else must match exactly. A finding whose quotes don't check out,
   or that rests on a failed probe, is dropped and listed separately with the
   reason.
4. **Report.** It writes the findings that survive, confirmed ones first, to
   a Markdown report for people and a JSON report for scripts.

## Design principles

- **It reports and never fixes.** Only a human can tell whether the doc is
  wrong or the system is.
- **The collector is the only part that touches the host.** Every command it
  runs is in a config file you can review.
- **A failed probe is not evidence.** A probe that errors or times out is
  marked as failed, and the model is told it can't conclude that something
  is missing from it.
- **Every finding is grounded.** Each one quotes the doc and the evidence,
  and both quotes are checked mechanically.
- **No runtime dependencies.** Only the Python standard library.

## What counts as a finding

| Kind | Example |
|---|---|
| Contradiction | The doc says the backup runs at 02:00; the timer says 03:00. |
| Cross-doc contradiction | Two docs state the same fact differently. |
| Omission | A scheduled job that no doc mentions. |
| Stale status | A doc calls something planned that is already running, or the reverse. |

Each finding is marked **CONFIRMED** (the evidence contradicts the doc) or
**SUSPECT** (it looks wrong, but the evidence can't settle it), and says
whether the likely fix is a doc edit or a change on the host.

Not findings: wording, style or structure, anything that can't be tied to a
line of evidence, and notes that record history ("was X until 2026-09-12").

## Usage

A config file, `doc-truth.toml`, names the docs to check and the probes to run:

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
name = "sitemap"
command = "curl -q -sS -o /dev/null --max-time 10 -w 'status=%{http_code} type=%{content_type} redirect=%{redirect_url}' https://example.com/sitemap.xml"
timeout = 15
notes = "Status, content type and redirect target of a GET request. The body isn't recorded."
```

Paths are relative to the config file. The
[configuration reference](docs/configuration.md) describes every setting,
and the [probe recipes](docs/probes.md) cover systemd timers, cron, failure
hooks, HTTP endpoints and tool versions, each with the trap it avoids.

```sh
doc-truth validate   # check the config and list the docs and probes it resolves to
doc-truth collect    # run the probes and write the evidence; no model call
doc-truth check      # run the probes, compare the docs with the evidence, write the report
```

`collect` runs the probes one at a time and writes what they print to a new
folder, `.doc-truth/runs/<UTC time>/` next to the config file, whose path it
prints:

- `evidence.md` is the evidence as the model will see it. Read it before you
  run `check`.
- `evidence.json` has the same results with durations and other details, for
  scripts.

`check` runs the probes the same way, into a run folder of its own, and
sends your docs and that run's `evidence.md` to the model in one prompt. It
checks every quote in the answer, then writes the report next to the
evidence:

- `report.md` lists the confirmed findings, then the suspect ones, each with
  both quotes and the likely fix. Failed probes and dropped findings get
  sections of their own.
- `report.json` has the same report for scripts, with a format version.

Both commands print the run folder's path on standard output. `check` also
prints a one-line summary on standard error.

`--output-dir PATH` keeps runs somewhere else, such as a systemd
`StateDirectory`. The default `.doc-truth` folder gets its own `.gitignore`,
so evidence doesn't end up in your docs repository by accident. The
[configuration reference](docs/configuration.md#how-probes-run) explains how
probes run: the shell, the environment, timeouts and output limits.

This is a `report.md` from a real run on a test machine, with only its title
line, which names the host, left out. The doc had one planted error, and a claim
about the restic version on a machine with no restic. That probe failed, so the
claim went unchecked instead of becoming a finding:

````markdown
**1 finding: 1 confirmed, 0 suspect.** 1 probe failed.

Checked 2026-11-02 18:26:34 UTC by doc-truth 0.1.0.dev0: 1 doc, 2 probes.
Model: claude-sonnet-5-5 (1 call, 3,872 tokens in, 290 out, $0.02 as reported by Claude Code).

## Confirmed

### dpkg-db-backup.timer runs daily, not weekly

Contradiction · likely fix: edit the doc

`docs/operations.md:6` says:

> `dpkg-db-backup.timer` backs up the package database once a week.

Probe `timer-schedules` printed:

```text
dpkg-db-backup.timer active waiting { OnCalendar=*-*-* 00:00:00 }
```

Why: The timer is active and its calendar is every day at 00:00:00, with no weekday restriction. The document says it runs once a week.

## Failed probes

A failed probe is no evidence, so no finding rests on one. Claims that only these probes could check went unchecked.

- `restic-version`: exit code 127 is not in success-exit-codes [0]

## Docs checked

- `docs/operations.md`
````

`validate` exits with `0` when the config is valid and `2` when it isn't.
`collect` exits with `0` when every probe succeeded and `2` when any failed;
it writes the evidence either way. `check` exits with `0` when there are no
confirmed findings, `1` when there is at least one, and `2` when a probe or
doc-truth itself failed; `2` wins over `1`. Suspect and dropped findings
don't change the exit code. When a probe fails, `check` still writes the
report, from the probes that worked. If the model can't be reached or its
answer is unusable twice, `check` keeps the evidence and writes no report.
A cron job or systemd timer can alert on these exit codes.

## Troubleshooting

Errors go to standard error, and the exit code is `2`. Once the probes have run,
their evidence is in the run folder, even if `check` couldn't write a report.

### `the claude command was not found on PATH`

Claude Code isn't installed, or it isn't on the `PATH` doc-truth runs with. Its
installer usually puts it in `~/.local/bin`, which isn't on the default `PATH`
of a cron job or a systemd service. Set `PATH` in the crontab or the unit, with
your home directory spelled out.

### `claude failed: Not logged in · Please run /login`

Run `claude` as the user who runs doc-truth, and log in. A job that runs as
another user, or with another `HOME`, doesn't see your login.

### A probe failed with `timed out after 30s`

Raise that probe's `timeout`. The evidence marks it `PROBE FAILED`, the report
lists it, and nothing is concluded from it, but `check` exits with `2` until it
works.

### A probe works in your terminal but fails from a timer

A timer has no login session and a shorter `PATH`. The
[probe recipes](docs/probes.md) show what user timers need, and how to name the
binary a job really runs.

### `claude did not answer within 600 seconds`

Raise `timeout` in `[model]`. Larger sets of docs take longer.

### `Prompt is too long`

The docs and the evidence don't fit in the model's context window. Check fewer
docs at a time, with a config file for each set, or make the probes print less.

### `the model's answer was unusable 2 times in a row`

The message lists what was wrong with the last answer, and no report is written.
Try again. If it keeps happening, please
[report a bug](https://github.com/TeodorBirghisan/doc-truth/issues/new?template=bug_report.yml)
with that list.

## Privacy

The evidence and your docs go into the prompt. With a hosted model, they
leave your machine. Run `doc-truth collect` first and read `evidence.md`: it
shows what `check` sends, in exactly the form the model sees. `check` runs
the probes again, so output that changes between runs can differ; the
`evidence.md` in its own run folder is exactly what it sent. Keep secrets out
of probe output.
Run folders are readable only by the user who ran doc-truth. Support for
local models through OpenAI-compatible endpoints (Ollama, llama.cpp, vLLM) is
planned for v0.2, along with redaction.

## Where it came from

doc-truth started as a weekly script checking the docs of a homelab against
the server they describe. A manual pass before the script existed had already
found drift that no amount of re-reading would have caught:

- The table of scheduled jobs in the ops manual had no row for the daily
  backup job.
- Two notes claimed a cron schedule restriction that the installed cron file
  did not have. A third note had recorded the correct value all along.

Once automated, the check kept finding the same kinds of drift:

- **Cross-doc contradictions:** the ops manual described an apt job's scope
  differently from three other notes that had recorded a change to it.
- **A recurring regression:** a cron restriction marked as fixed reverted
  every week. Flagging it repeatedly led to the real cause: Timeshift rewrites
  its own cron file on every check, so the fix could never stick.

It also showed how a check like this goes wrong. Most of its false alarms came
from a probe that could not see something and was read as "it isn't there."
doc-truth is designed around that lesson.

## Roadmap

- **v0.1:** the config format and `validate` (done), `collect` (done),
  `check` with quote verification, Markdown and JSON reports and exit codes
  (done), [probe recipes](docs/probes.md) for systemd, cron, HTTP and tool
  versions (done). Still planned: a few weeks on a real server next to the
  script it replaces, a tested timer example, and the first release on PyPI.
- **v0.2:** local models via OpenAI-compatible endpoints, a baseline file to
  acknowledge known findings, automatic checks for paths cited in the docs,
  redaction of secrets in evidence.
- **v0.3:** a Claude Code plugin with an interactive command for running the
  check and working through its findings.

## Contributing

Bug reports, ideas and pull requests are welcome. Read the
[contributing guide](CONTRIBUTING.md) first; it covers the development setup,
the design principles and how pull requests are merged. Questions go to
[Discussions](https://github.com/TeodorBirghisan/doc-truth/discussions).
Report security problems privately, as described in the
[security policy](SECURITY.md).

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).
