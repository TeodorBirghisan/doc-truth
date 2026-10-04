import errno
import shutil
import tempfile
from datetime import UTC
from pathlib import Path

from doc_truth.config import Config
from doc_truth.evidence import Evidence, evidence_json, evidence_markdown

DEFAULT_OUTPUT_DIR_NAME = ".doc-truth"
RUNS_DIR_NAME = "runs"
EVIDENCE_JSON = "evidence.json"
EVIDENCE_MARKDOWN = "evidence.md"

_GITIGNORE = "# Created by doc-truth. Run folders can contain sensitive probe output.\n*\n"


class RunsError(Exception):
    pass


def prepare_runs_dir(config: Config, output_dir: Path | None) -> Path:
    if output_dir is None:
        output_dir = config.base_dir / DEFAULT_OUTPUT_DIR_NAME
        ignore_in_git = not output_dir.exists()
    else:
        ignore_in_git = False
    runs = output_dir.absolute() / RUNS_DIR_NAME
    try:
        runs.mkdir(parents=True, exist_ok=True)
        if ignore_in_git:
            (output_dir / ".gitignore").write_text(_GITIGNORE, encoding="utf-8")
    except OSError as error:
        raise RunsError(_cannot_write(output_dir, error)) from None
    return runs


def write_run(evidence: Evidence, runs: Path) -> Path:
    try:
        staging = Path(tempfile.mkdtemp(prefix=".incomplete-", dir=runs))
    except OSError as error:
        raise RunsError(_cannot_write(runs, error)) from None
    try:
        (staging / EVIDENCE_JSON).write_text(evidence_json(evidence), encoding="utf-8")
        (staging / EVIDENCE_MARKDOWN).write_text(evidence_markdown(evidence), encoding="utf-8")
        return _publish(staging, runs / _run_name(evidence))
    except OSError as error:
        raise RunsError(_cannot_write(runs, error)) from None
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


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


def _cannot_write(directory: Path, error: OSError) -> str:
    return f"cannot write the evidence to {directory}: {error.strerror or error}"
