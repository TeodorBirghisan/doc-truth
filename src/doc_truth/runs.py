import errno
import json
import os
import shutil
import tempfile
from datetime import UTC
from pathlib import Path

from doc_truth.config import Config
from doc_truth.evidence import Evidence, evidence_json, evidence_markdown
from doc_truth.known import Earlier, PreviousReport, earlier_from_json
from doc_truth.report import REPORT_FORMAT, Report, report_json, report_markdown

DEFAULT_OUTPUT_DIR_NAME = ".doc-truth"
RUNS_DIR_NAME = "runs"
EVIDENCE_JSON = "evidence.json"
EVIDENCE_MARKDOWN = "evidence.md"
REPORT_JSON = "report.json"
REPORT_MARKDOWN = "report.md"

_GITIGNORE = "# Created by doc-truth. Run folders can contain sensitive probe output.\n*\n"


class RunsError(Exception):
    pass


def runs_dir(config: Config, output_dir: Path | None) -> Path:
    base = config.base_dir / DEFAULT_OUTPUT_DIR_NAME if output_dir is None else output_dir
    return base.absolute() / RUNS_DIR_NAME


def prepare_runs_dir(config: Config, output_dir: Path | None) -> Path:
    ignore_in_git = output_dir is None and not runs_dir(config, None).parent.exists()
    runs = runs_dir(config, output_dir)
    try:
        runs.mkdir(parents=True, exist_ok=True)
        if ignore_in_git:
            (runs.parent / ".gitignore").write_text(_GITIGNORE, encoding="utf-8")
    except OSError as error:
        raise RunsError(_cannot_write("the evidence", runs.parent, error)) from None
    return runs


def latest_report(runs: Path, config: Config) -> PreviousReport | None:
    config_path = os.path.realpath(config.absolute_path)
    try:
        folders = sorted(
            (path for path in runs.iterdir() if not path.name.startswith(".")),
            key=lambda path: path.name,
            reverse=True,
        )
    except FileNotFoundError:
        return None
    except OSError as error:
        raise RunsError(f"cannot read {runs}: {error.strerror or error}") from None
    for folder in folders:
        path = folder / REPORT_JSON
        data = _read_report(path)
        if data is None:
            continue
        written_for = data.get("config")
        if not isinstance(written_for, str) or os.path.realpath(written_for) != config_path:
            continue
        if data.get("format") != REPORT_FORMAT:
            return None
        return PreviousReport(
            run=folder.name,
            findings=_earlier_findings(data, path, "findings", "not_rechecked"),
            no_longer_reported=_earlier_findings(data, path, "no_longer_reported"),
        )
    return None


def _read_report(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError, NotADirectoryError:
        return None
    except OSError as error:
        raise RunsError(f"cannot read {path}: {error.strerror or error}") from None
    except ValueError:
        raise RunsError(f"cannot read {path}: it isn't valid JSON") from None
    if not isinstance(data, dict):
        raise RunsError(f"cannot read {path}: it isn't a report")
    return data


def _earlier_findings(data: dict[str, object], path: Path, *keys: str) -> tuple[Earlier, ...]:
    try:
        return tuple(
            earlier_from_json(entry)
            for key in keys
            for entry in _entries(data[key])
            if entry.get("left_config") is not True
        )
    except KeyError, TypeError, ValueError:
        raise RunsError(f"cannot read {path}: its findings aren't in the expected form") from None


def _entries(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(entry, dict) for entry in value):
        raise ValueError("expected a list of objects")
    return value


def write_run(evidence: Evidence, runs: Path) -> Path:
    try:
        staging = Path(tempfile.mkdtemp(prefix=".incomplete-", dir=runs))
    except OSError as error:
        raise RunsError(_cannot_write("the evidence", runs, error)) from None
    try:
        (staging / EVIDENCE_JSON).write_text(evidence_json(evidence), encoding="utf-8")
        (staging / EVIDENCE_MARKDOWN).write_text(evidence_markdown(evidence), encoding="utf-8")
        return _publish(staging, runs / _run_name(evidence))
    except OSError as error:
        raise RunsError(_cannot_write("the evidence", runs, error)) from None
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def write_report(report: Report, run: Path) -> None:
    files = {REPORT_JSON: report_json(report), REPORT_MARKDOWN: report_markdown(report)}
    staged: list[tuple[Path, Path]] = []
    try:
        for name, text in files.items():
            staging = run / f".{name}.incomplete"
            staged.append((staging, run / name))
            staging.write_text(text, encoding="utf-8")
        for staging, target in staged:
            staging.rename(target)
    except OSError as error:
        raise RunsError(_cannot_write("the report", run, error)) from None
    finally:
        for staging, _ in staged:
            staging.unlink(missing_ok=True)


def _run_name(evidence: Evidence) -> str:
    return evidence.started_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _publish(staging: Path, run: Path) -> Path:
    attempt = 1
    while True:
        target = run if attempt == 1 else run.with_name(f"{run.name}-{attempt}")
        try:
            return staging.rename(target)
        except OSError as error:
            if error.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                raise
        attempt += 1


def _cannot_write(what: str, directory: Path, error: OSError) -> str:
    return f"cannot write {what} to {directory}: {error.strerror or error}"
