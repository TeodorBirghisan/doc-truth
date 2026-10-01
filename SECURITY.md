# Security policy

## Supported versions

doc-truth is pre-alpha and has no releases yet. Security fixes go to the
`main` branch. Once there are releases, fixes will go to the latest one.

## Reporting a vulnerability

Please don't report security problems in public issues, discussions or pull
requests. Report them privately through GitHub instead:
[report a vulnerability](https://github.com/TeodorBirghisan/doc-truth/security/advisories/new).

Include as much of this as you can:

- the affected version or commit
- steps to reproduce, or a proof of concept
- the impact: what an attacker could do
- a suggested fix, if you have one

doc-truth is maintained by one person. The aim is to acknowledge a report
within 7 days, keep you updated while it's investigated, and agree a
disclosure date with you. You'll be credited in the advisory unless you'd
rather not be.

## Scope

doc-truth is designed so that only the probe commands in your config file
touch the host, and so that the model it calls has no tools. A vulnerability
is anything that breaks those guarantees, for example:

- content in a doc or in probe output that makes doc-truth run a command,
  write outside its output location, or send data anywhere other than the
  configured model backend;
- evidence or doc content reaching a destination the user didn't configure.

These are expected behavior, not vulnerabilities:

- **Probe commands run with the privileges of the user who runs doc-truth.**
  The config file is trusted input. Review it like a script before you run it.
- **The evidence and the docs are sent to the model backend you configure.**
  With a hosted model, that data leaves your machine. See the
  [Privacy section](README.md#privacy) of the README.
- **Prompt injection that only changes the report's content.** The model
  can't act on anything. If injected text gets a fabricated finding past quote
  verification, please report it as a bug.
