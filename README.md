# doc-truth

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
   is exactly what will be sent to one.
2. **Check.** It puts the evidence and your docs, with line numbers, into one
   prompt. The model answers with structured findings. It gets no tools, so it
   cannot run commands, read other files or change anything.
3. **Verify.** Before a finding reaches the report, doc-truth checks that the
   quoted doc line exists at the cited location and that the quoted evidence
   exists in the named probe's output. Findings whose quotes don't check out
   are dropped or downgraded.

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

## Planned usage (v0.1)

A config file names the docs to check and the probes to run:

```toml
[[docs]]
path = "docs/operations.md"

[[probes]]
name = "systemd-timers"
command = "systemctl list-timers --all --no-pager"

[[probes]]
name = "sitemap"
command = "curl -s -o /dev/null -w '%{http_code} %{content_type}' https://example.com/sitemap.xml"
caveats = "Reports the HTTP status and content type only, not the body."
```

```sh
doc-truth collect    # run the probes and write the evidence; no model call
doc-truth check      # compare the docs with the evidence and write the report
```

A finding in the report looks like this:

```markdown
## Backup timer runs at 03:00, not 02:00
- Doc says: docs/operations.md:42: "restic backs up nightly at 02:00"
- Evidence says: systemd-timers: "restic-backup.timer ... *-*-* 03:00:00"
- Confidence: CONFIRMED
- Fix: doc edit
```

`check` exits with `0` when there is nothing new, `1` when there are new
confirmed findings, and `2` when a probe or doc-truth itself failed. This
makes it easy to run from cron or a systemd timer and alert on failure.

## Privacy

The evidence and your docs go into the prompt. With a hosted model, they
leave your machine. Run `doc-truth collect` first and read the evidence file:
it is exactly what will be sent. Keep secrets out of probe output. Support for
local models through OpenAI-compatible endpoints (Ollama, llama.cpp, vLLM) is
planned for v0.2, along with redaction.

## Requirements

- Python 3.14 or newer
- Linux. Probes are shell commands; the examples use systemd and cron.
- For `check` in v0.1: [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
  installed and logged in. doc-truth calls the `claude` CLI with all tools
  disabled.

## Roadmap

- **v0.1:** `collect`, `check`, quote verification, Markdown and JSON reports,
  exit codes, example probes for systemd, cron and HTTP.
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
