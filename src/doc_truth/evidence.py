import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from doc_truth.config import Probe

EVIDENCE_FORMAT = 1
FAILED_LABEL = "PROBE FAILED"
FAILED_MARKER = f"{FAILED_LABEL} — not evidence of absence"

_BACKTICK_RUNS = re.compile(r"`+")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProbeResult:
    probe: Probe
    stdout: str
    stderr: str
    exit_code: int | None
    signal: str | None
    duration: float
    timed_out: bool
    stdout_truncated: bool
    stderr_truncated: bool
    failure: str | None

    @property
    def failed(self) -> bool:
        return self.failure is not None


@dataclass(frozen=True, slots=True, kw_only=True)
class Evidence:
    tool_version: str
    host: str
    user: str
    timezone: str
    utc_offset: str
    started_at: datetime
    finished_at: datetime
    config_path: Path
    results: tuple[ProbeResult, ...]


def evidence_json(evidence: Evidence) -> str:
    data = {
        "format": EVIDENCE_FORMAT,
        "doc_truth_version": evidence.tool_version,
        "host": evidence.host,
        "user": evidence.user,
        "timezone": evidence.timezone,
        "utc_offset": evidence.utc_offset,
        "started_at": _utc_timestamp(evidence.started_at),
        "finished_at": _utc_timestamp(evidence.finished_at),
        "config": str(evidence.config_path),
        "probes": [_probe_json(result) for result in evidence.results],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def evidence_markdown(evidence: Evidence) -> str:
    started = evidence.started_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    blocks = [
        f"# Evidence from host `{evidence.host}`",
        f"Collected {started} by doc-truth {evidence.tool_version}, running as user "
        f"`{evidence.user}`. The host's local time zone is {evidence.timezone} "
        f"(UTC{evidence.utc_offset}).",
        "Each section below shows a read-only command from the config file and what it "
        f"printed on this host. A probe marked {FAILED_LABEL} produced no "
        "usable evidence: nothing can be concluded from it, least of all that something "
        "is missing.",
    ]
    for result in evidence.results:
        blocks.extend(_probe_blocks(result))
    return "\n\n".join(blocks) + "\n"


def format_size(size: int) -> str:
    for unit, factor in (("MiB", 1024 * 1024), ("KiB", 1024)):
        if size >= factor and size % factor == 0:
            return f"{size // factor} {unit}"
    return "1 byte" if size == 1 else f"{size} bytes"


def _probe_json(result: ProbeResult) -> dict[str, object]:
    probe = result.probe
    return {
        "name": probe.name,
        "command": probe.command,
        "timeout": probe.timeout,
        "success_exit_codes": sorted(probe.success_exit_codes),
        "notes": probe.notes,
        "status": "failed" if result.failed else "ok",
        "failure": result.failure,
        "exit_code": result.exit_code,
        "signal": result.signal,
        "timed_out": result.timed_out,
        "stdout_truncated": result.stdout_truncated,
        "stderr_truncated": result.stderr_truncated,
        "duration": round(result.duration, 3),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _probe_blocks(result: ProbeResult) -> list[str]:
    probe = result.probe
    blocks = [f"## {probe.name}"]
    if result.failure is not None:
        blocks.append(f"**{FAILED_MARKER}:** {result.failure}.")
    blocks.append(_fence(probe.command, "sh"))
    if probe.notes is not None:
        blocks.append("Notes:\n\n" + _blockquote(probe.notes))
    if result.exit_code is not None:
        blocks.append(f"Exit code {result.exit_code}.")
    elif result.signal is not None:
        blocks.append(f"Ended by {result.signal}.")
    if result.stdout or result.stdout_truncated:
        blocks.append("Standard output:")
        blocks.append(_fence(result.stdout, "text"))
        if result.stdout_truncated:
            blocks.append("Standard output was cut off here; the rest was dropped.")
    elif result.exit_code is not None or result.signal is not None:
        blocks.append("Standard output was empty.")
    if result.stderr or result.stderr_truncated:
        blocks.append("Standard error:")
        blocks.append(_fence(result.stderr, "text"))
        if result.stderr_truncated:
            blocks.append("Standard error was cut off here; the rest was dropped.")
    return blocks


def _fence(text: str, info: str) -> str:
    longest = max((len(run) for run in _BACKTICK_RUNS.findall(text)), default=0)
    fence = "`" * max(3, longest + 1)
    body = text if text.endswith("\n") or not text else text + "\n"
    return f"{fence}{info}\n{body}{fence}"


def _blockquote(text: str) -> str:
    return "\n".join(f"> {line}".rstrip() for line in text.splitlines())


def _utc_timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
