# Contributing to doc-truth

Thanks for considering a contribution. doc-truth is pre-alpha: the commands,
the config format and the report format are still changing. For anything
bigger than a small fix, please open an issue first, so nobody spends time on
a change that conflicts with work in progress.

## Ways to help

- **Report a bug** with the
  [bug report form](https://github.com/TeodorBirghisan/doc-truth/issues/new?template=bug_report.yml).
- **Suggest a feature** with the
  [feature request form](https://github.com/TeodorBirghisan/doc-truth/issues/new?template=feature_request.yml).
  Describe the problem first; a concrete example of a doc and a system helps
  more than a finished design.
- **Ask a question** in
  [Discussions](https://github.com/TeodorBirghisan/doc-truth/discussions).
- **Report a security problem** privately, as described in the
  [security policy](SECURITY.md). Never in a public issue.
- **Fix docs or typos** directly in a pull request. No issue needed.

## Design principles

Pull requests that break these will be declined unless an issue has first
made the case for changing them:

1. **doc-truth reports and never fixes.** It doesn't edit docs or change the
   system it inspects.
2. **The collector is the only part that touches the host.** The model gets
   no tools.
3. **A failed probe is not evidence.** Nothing may conclude that something is
   missing from a probe that errored or timed out.
4. **Every finding is grounded.** Its quotes from the doc and the evidence
   are checked before it reaches the report.
5. **No runtime dependencies.** The core uses only the Python standard
   library. Development tools are fine.

## Development setup

You need Python 3.14 or newer and [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/TeodorBirghisan/doc-truth.git
cd doc-truth
uv sync
```

Run these before opening a pull request:

```sh
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy
```

## Code style

- `ruff format` decides formatting. `ruff check` and `mypy --strict` must pass
  with no warnings.
- Every function is fully type-annotated.
- New behavior needs a test. A bug fix needs a test that fails without the
  fix.
- Prefer clear names to comments. Write a comment only to explain *why*
  something is done a non-obvious way, never to restate what the code does.

## Pull requests

- Branch from `main` and keep each pull request to one topic.
- Pull requests are squash-merged, so **the pull request title becomes the
  commit message on `main`**. Write it in
  [Conventional Commits](https://www.conventionalcommits.org/) form,
  `type(scope): summary`, using one of these types: `feat`, `fix`, `docs`,
  `test`, `refactor`, `perf`, `build`, `ci`, `chore`. For example:
  `fix(collect): mark timed-out probes as failed`. Mark breaking changes with
  `!`, as in `feat(config)!: rename the probes table`.
- In the description, explain *why* the change is needed and link the issue
  it resolves (`Closes #12`). The commits on your branch don't need to be
  tidy; they're squashed on merge.
- The maintainer reviews every pull request. All review conversations must be
  resolved before it can be merged.

## License

By contributing, you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE), as described in section 5 of the license.

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).
By taking part, you agree to uphold it.
