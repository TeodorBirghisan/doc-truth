import argparse
import sys
from collections.abc import Callable, Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from doc_truth.config import DEFAULT_CONFIG_NAME, ConfigError, load_config, resolve_docs


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    commands: dict[str, Callable[[argparse.Namespace], int]] = {"validate": _validate}
    try:
        return commands[args.command](args)
    except ConfigError as error:
        print(f"doc-truth: error: {error}", file=sys.stderr)
        return 2


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
    validate.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path(DEFAULT_CONFIG_NAME),
        metavar="PATH",
        help=f"the config file to read (default: {DEFAULT_CONFIG_NAME})",
    )
    return parser


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


def _version() -> str:
    try:
        return version("doc-truth")
    except PackageNotFoundError:
        return "unknown"
