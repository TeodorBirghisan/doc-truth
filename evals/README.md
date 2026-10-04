# Evaluation cases

These cases pin down how `doc-truth check` has to behave before its prompt is
written. Each one is a small set of docs, the evidence a host produced, and
the findings a good answer must and must not contain. They come from real
weekly runs of the script doc-truth grew out of, rewritten for a made-up host.

> [!NOTE]
> `check` is still being built. Today the test suite only checks that every
> case is valid and that its reference answer scores perfectly. Running the
> cases against a real model is planned for when `check` exists.

## The cases

| Case | A good answer |
|---|---|
| `timeshift-cron-contradiction` | finds, as CONFIRMED, that two docs claim a cron restriction the installed cron file doesn't have |
| `apt-scope-cross-doc` | finds that the operations manual and two notes disagree, with no probe to settle it |
| `omission-claimed-complete` | finds a cron job missing from a section the config's notes call complete |
| `omission-not-claimed` | reports nothing: the same job is missing, but nothing claims the section is complete |
| `failed-user-probe` | finds a real schedule drift and reports nothing from two probes that failed |
| `other-host-path` | finds a missing path, but doesn't CONFIRM paths the notes place on another machine |
| `history-note` | reports nothing from lines that record what used to be true |
| `stale-status` | finds a job described as planned that already runs |
| `clean` | reports nothing |
| `haystack` | finds one schedule drift among 12 docs and 14 probes that otherwise agree |

## What a case contains

```
cases/<name>/
├── doc-truth.toml   the docs and probes, as a user would write them
├── docs/ notes/     the documents
├── evidence.toml    what each probe printed
├── expected.toml    what a good answer must and must not contain
└── reference.json   a hand-written answer that meets expected.toml
```

### `evidence.toml`

One `[[results]]` table per probe in `doc-truth.toml`, giving `exit-code` (or
`timed-out = true`) and optionally `stdout` and `stderr`. The tests turn it
into the same evidence `doc-truth collect` writes, through the same code, so
the model sees exactly what it would see on a real host. A probe fails by the
same rules as in `collect`.

### `expected.toml`

Three kinds of entries, each with an `id` and an optional `note`:

- `[[must-find]]`: a finding the answer must contain. It gives the `doc`
  locations the finding may cite, as `FILE:LINE` or `FILE:START-END`, and
  optionally the `evidence` it must rest on: `probe:NAME` or another doc
  location. `confidence = "confirmed"` requires a CONFIRMED finding.
- `[[must-not-find]]`: a finding the answer must not contain, described by any
  of `doc`, `evidence` and `confidence`.
- `[[allowed]]`: findings that are acceptable but not required.

A finding matches an entry when its cited lines overlap one of the entry's
locations, its evidence is one of the entry's sources, and its confidence
matches. The kind of finding isn't compared, because "contradiction" and
"stale status" are often both fair descriptions. Any finding that matches no
entry is a false positive, and a case passes only with no false positives.

### `reference.json`

A complete answer in the findings format `check` will ask the model for
(`src/doc_truth/findings.py`). It shows that `expected.toml` can be met, and
every quote in it is checked against the docs and the evidence.

## Writing a case

- Use the made-up host: `homeserver`, user `ops`, the `example.org` and
  `example.com` domains, and documentation IP addresses (192.0.2.0/24,
  198.51.100.0/24, 203.0.113.0/24). The tests reject other public addresses.
- Everything except the planted problem must agree with the evidence. A case
  with an accidental contradiction punishes a model for being right.
- When doc-truth reports a false positive in real use, turn it into a case.
