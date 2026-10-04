import argparse
import sys
from collections.abc import Callable, Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from doc_truth.collect import CollectError, collect
from doc_truth.config import DEFAULT_CONFIG_NAME, ConfigError, load_config, resolve_docs
from doc_truth.evidence import ProbeResult
from doc_truth.runs import DEFAULT_OUTPUT_DIR_NAME, RunsError, prepare_runs_dir, write_run


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    commands: dict[str, Callable[[argparse.Namespace], int]] = {
        "validate": _validate,
        "collect": _collect,
    }
    try:
        return commands[args.command](args)
    except (ConfigError, CollectError, RunsError) as error:
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
    collect.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        metavar="PATH",
        help=(
            "the directory to keep runs in "
            f"(default: {DEFAULT_OUTPUT_DIR_NAME} next to the config file)"
        ),
    )
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
    total = len(config.probes)
    name_width = max(len(probe.name) for probe in config.probes)
    finished = 0

    def report(result: ProbeResult) -> None:
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

    evidence = collect(config, tool_version=_version(), on_result=report)
    run = write_run(evidence, runs)
    failed = sum(result.failed for result in evidence.results)
    print(f"Probes: {total - failed} ok, {failed} failed.", file=sys.stderr)
    print(run)
    return 2 if failed else 0


def _version() -> str:
    try:
        return version("doc-truth")
    except PackageNotFoundError:
        return "unknown"
