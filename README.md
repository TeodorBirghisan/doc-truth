# doc-truth

[![CI](https://github.com/TeodorBirghisan/doc-truth/actions/workflows/ci.yml/badge.svg)](https://github.com/TeodorBirghisan/doc-truth/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Check what your operations docs claim against what your systems actually run.

> [!WARNING]
> **Pre-alpha. Nothing is released yet.** This README describes what v0.1 is
> being built to do. Commands, the config format and the report format will
> change before the first release.

Runbooks, ops manuals, READMEs and agent files such as `CLAUDE.md` make claims
about running systems: the backup runs nightly at 02:00, the service pages on
failure, the key lives at `~/.config/sops/age/keys.txt`, `/sitemap.xml` returns
XML. Systems change, and docs fall behind without anyone noticing. Reading the
docs again won't catch it. Only checking them against the live system will.

doc-truth runs read-only commands you declare to collect evidence from a host,
has a language model compare that evidence with the claims in your docs, and
writes a report of every place where the two disagree. It never changes your
docs or your system.

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

## How it works

```
probes (doc-truth.toml) ──collect──▶ evidence ──┐
                                                ├──check──▶ findings ──verify──▶ report
your docs (Markdown) ───────────────────────────┘
```

1. **Collect.** doc-truth runs the probes from your config file: plain
   read-only shell commands such as `systemctl list-timers` or
   `curl -sI https://example.com/`. It records each probe's output, exit code
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

## Install

doc-truth isn't on PyPI yet. To try what works so far, install it from
GitHub with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install git+https://github.com/TeodorBirghisan/doc-truth
```

You need:

- Python 3.14 or newer. uv downloads it if your system doesn't have it.
- Linux with bash. Probes run as bash commands; the examples use systemd
  and cron.
- For `check` in v0.1: [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
  installed and logged in. doc-truth calls the `claude` CLI with all tools
  disabled.

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

A finding in `report.md` looks like this:

````markdown
### Backup timer runs at 03:00, not 02:00

Contradiction · likely fix: edit the doc

`docs/operations.md:42` says:

> restic backs up nightly at 02:00

Probe `systemd-timers` printed:

```text
Sat 2026-10-17 03:00:00 EEST  14h left  Fri 2026-10-16 03:00:02 EEST  9h ago  restic-backup.timer
```

Why: The doc says the backup runs at 02:00, but the timer's last and next runs are at 03:00.
````

`validate` exits with `0` when the config is valid and `2` when it isn't.
`collect` exits with `0` when every probe succeeded and `2` when any failed;
it writes the evidence either way. `check` exits with `0` when there are no
confirmed findings, `1` when there is at least one, and `2` when a probe or
doc-truth itself failed; `2` wins over `1`. Suspect and dropped findings
don't change the exit code. When a probe fails, `check` still writes the
report, from the probes that worked. If the model can't be reached or its
answer is unusable twice, `check` keeps the evidence and writes no report.
The exit codes make it easy to run from cron or a systemd timer and alert on
failure.

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

## Roadmap

- **v0.1:** the config format and `validate` (done), `collect` (done),
  `check` with quote verification, Markdown and JSON reports and exit codes
  (done), [probe recipes](docs/probes.md) for systemd, cron, HTTP and tool
  versions (done).
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
