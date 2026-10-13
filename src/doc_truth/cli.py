import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from functools import partial
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from doc_truth.collect import CollectError, collect
from doc_truth.compare import InvalidAnswerError, compare
from doc_truth.config import DEFAULT_CONFIG_NAME, Config, ConfigError, load_config, resolve_docs
from doc_truth.evidence import Evidence, ProbeResult, evidence_markdown
from doc_truth.model import ModelError, ask_claude
from doc_truth.prompt import PromptError, build_prompt, read_docs
from doc_truth.report import Report, summary
from doc_truth.runs import (
    DEFAULT_OUTPUT_DIR_NAME,
    RunsError,
    prepare_runs_dir,
    write_report,
    write_run,
)
from doc_truth.verify import verify


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    commands: dict[str, Callable[[argparse.Namespace], int]] = {
        "validate": _validate,
        "collect": _collect,
        "check": _check,
    }
    try:
        return commands[args.command](args)
    except (
        ConfigError,
        CollectError,
        RunsError,
        PromptError,
        ModelError,
        InvalidAnswerError,
    ) as error:
        print(f"doc-truth: error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("doc-truth: interrupted", file=sys.stderr)
        return 130


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doc-truth",
        description=(
            "Check what your operations docs claim against what your systems actually run."
        ),
        suggest_on_error=True,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version()}")
    commands = parser.add_subparsers(
        dest="command", title="commands", metavar="<command>", required=True
    )
    validate = commands.add_parser(
        "validate",
        help="check the config file and list the docs and probes it resolves to",
        description=(
            "Check the config file and list the docs and probes it resolves to. "
            "Exits with 0 when the config is valid and 2 when it isn't."
        ),
    )
    _add_config_argument(validate)
    collect = commands.add_parser(
        "collect",
        help="run the probes and write the evidence, without calling a model",
        description=(
            "Run every probe in the config file and write what they print to a new run "
            "folder, whose path is printed on standard output. No model is called. "
            "Exits with 0 when every probe succeeded and 2 when any failed."
        ),
    )
    _add_config_argument(collect)
    _add_output_dir_argument(collect)
    check = commands.add_parser(
        "check",
        help="compare the docs with fresh evidence and write a report",
        description=(
            "Run every probe, ask the model to compare the docs with the evidence, check "
            "every quote it gives and write a report next to the evidence in a new run "
            "folder, whose path is printed on standard output. Exits with 0 when there are "
            "no confirmed findings, 1 when there are, and 2 when a probe or doc-truth failed."
        ),
    )
    _add_config_argument(check)
    _add_output_dir_argument(check)
    return parser


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path(DEFAULT_CONFIG_NAME),
        metavar="PATH",
        help=f"the config file to read (default: {DEFAULT_CONFIG_NAME})",
    )


def _add_output_dir_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        metavar="PATH",
        help=(
            "the directory to keep runs in "
            f"(default: {DEFAULT_OUTPUT_DIR_NAME} next to the config file)"
        ),
    )


def _validate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    docs = resolve_docs(config)
    name_width = max(len(probe.name) for probe in config.probes)
    print(f"{config.path} is valid.")
    print()
    print(f"Docs ({len(docs)}):")
    for doc in docs:
        print(f"  {doc.display_path}")
    print()
    print(f"Probes ({len(config.probes)}):")
    for probe in config.probes:
        print(f"  {probe.name:<{name_width}}  timeout {probe.timeout:g}s")
    return 0


def _collect(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    runs = prepare_runs_dir(config, args.output_dir)
    evidence = _run_probes(config)
    print(write_run(evidence, runs))
    return 2 if any(result.failed for result in evidence.results) else 0


def _check(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    docs = read_docs(resolve_docs(config))
    runs = prepare_runs_dir(config, args.output_dir)
    evidence = _run_probes(config)
    run = write_run(evidence, runs)
    print(run, flush=True)
    prompt = build_prompt(docs, evidence_markdown(evidence))
    print(
        f"Asking {config.model.name} to compare the docs with the evidence.",
        file=sys.stderr,
        flush=True,
    )
    comparison = compare(prompt, partial(ask_claude, settings=config.model))
    verification = verify(comparison.findings, docs, evidence.results)
    report = Report(
        evidence=evidence,
        docs=tuple(text.doc.display_path for text in docs),
        prompt_version=prompt.version,
        requested_model=config.model.name,
        answers=comparison.answers,
        findings=verification.findings,
        dropped=verification.dropped,
        finished_at=datetime.now(UTC),
    )
    write_report(report, run)
    print(summary(report), file=sys.stderr)
    if report.failed_probes:
        return 2
    return 1 if report.confirmed else 0


def _run_probes(config: Config) -> Evidence:
    total = len(config.probes)
    name_width = max(len(probe.name) for probe in config.probes)
    finished = 0

    def progress(result: ProbeResult) -> None:
        nonlocal finished
        finished += 1
        status = "failed" if result.failed else "ok"
        line = (
            f"[{finished:>{len(str(total))}}/{total}] {result.probe.name:<{name_width}}  "
            f"{status:<6}  {result.duration:.2f}s"
        )
        if result.failure is not None:
            line += f"  {result.failure}"
        print(line, file=sys.stderr, flush=True)

    evidence = collect(config, tool_version=_version(), on_result=progress)
    failed = sum(result.failed for result in evidence.results)
    print(f"Probes: {total - failed} ok, {failed} failed.", file=sys.stderr, flush=True)
    return evidence


def _version() -> str:
    try:
        return version("doc-truth")
    except PackageNotFoundError:
        return "unknown"
