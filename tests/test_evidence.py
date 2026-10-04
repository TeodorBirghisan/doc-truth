import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from doc_truth.config import Probe
from doc_truth.evidence import (
    Evidence,
    ProbeResult,
    evidence_json,
    evidence_markdown,
    format_size,
)

GOLDEN = Path(__file__).parent / "golden"
EEST = timezone(timedelta(hours=3))


def result(
    name: str,
    command: str,
    *,
    notes: str | None = None,
    success_exit_codes: frozenset[int] = frozenset({0}),
    stdout: str = "",
    stderr: str = "",
    exit_code: int | None = 0,
    signal: str | None = None,
    timed_out: bool = False,
    stdout_truncated: bool = False,
    stderr_truncated: bool = False,
    failure: str | None = None,
) -> ProbeResult:
    return ProbeResult(
        probe=Probe(
            name=name,
            command=command,
            timeout=30.0,
            success_exit_codes=success_exit_codes,
            notes=notes,
        ),
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        signal=signal,
        duration=0.123456,
        timed_out=timed_out,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        failure=failure,
    )


def evidence(*results: ProbeResult) -> Evidence:
    return Evidence(
        tool_version="0.1.0",
        host="core",
        user="teo",
        timezone="EEST",
        utc_offset="+03:00",
        started_at=datetime(2026, 10, 4, 15, 4, 19, 512000, tzinfo=EEST),
        finished_at=datetime(2026, 10, 4, 12, 4, 21, tzinfo=UTC),
        config_path=Path("/etc/doc-truth/doc-truth.toml"),
        results=results,
    )


SUCCESS = result(
    "systemd-timers",
    "systemctl list-timers --all --no-pager",
    notes="Lists system timers only.\n\nUser timers need their own probe.",
    stdout="restic-backup.timer  *-*-* 03:00:00\n",
)
FAILURE = result(
    "user-timers",
    "systemctl --user list-timers",
    stderr="Failed to connect to bus: No medium found\n",
    exit_code=1,
    failure="exit code 1 is not in success-exit-codes [0]",
)


def test_the_markdown_is_what_the_model_will_see() -> None:
    timed_out = result(
        "slow",
        "find / -name '*.timer'",
        stdout="/etc/systemd/system/a.timer",
        exit_code=None,
        signal="SIGTERM",
        timed_out=True,
        failure="timed out after 30s",
    )
    flood = result(
        "flood",
        "journalctl",
        stdout="line\n",
        stderr="warning\n",
        stdout_truncated=True,
        stderr_truncated=True,
        failure="printed more than 1 MiB on standard output",
    )
    missing = result(
        "missing",
        "true",
        exit_code=None,
        failure="could not start: No such file or directory",
    )
    fenced = result("fenced", "printf '```'", stdout="```\n``x````")

    markdown = evidence_markdown(evidence(SUCCESS, FAILURE, timed_out, flood, missing, fenced))

    assert markdown == (GOLDEN / "evidence.md").read_text(encoding="utf-8")


def test_cut_off_output_is_shown_even_when_nothing_was_kept() -> None:
    markdown = evidence_markdown(
        evidence(result("quiet", "true", stdout_truncated=True, stderr_truncated=True))
    )

    assert "Standard output:\n\n```text\n```\n\nStandard output was cut off here" in markdown
    assert "Standard error:\n\n```text\n```\n\nStandard error was cut off here" in markdown
    assert "was empty" not in markdown


def test_the_json_has_every_detail_for_scripts() -> None:
    data = json.loads(evidence_json(evidence(SUCCESS, FAILURE)))

    assert data == {
        "format": 1,
        "doc_truth_version": "0.1.0",
        "host": "core",
        "user": "teo",
        "timezone": "EEST",
        "utc_offset": "+03:00",
        "started_at": "2026-10-04T12:04:19Z",
        "finished_at": "2026-10-04T12:04:21Z",
        "config": "/etc/doc-truth/doc-truth.toml",
        "probes": [
            {
                "name": "systemd-timers",
                "command": "systemctl list-timers --all --no-pager",
                "timeout": 30.0,
                "success_exit_codes": [0],
                "notes": "Lists system timers only.\n\nUser timers need their own probe.",
                "status": "ok",
                "failure": None,
                "exit_code": 0,
                "signal": None,
                "timed_out": False,
                "stdout_truncated": False,
                "stderr_truncated": False,
                "duration": 0.123,
                "stdout": "restic-backup.timer  *-*-* 03:00:00\n",
                "stderr": "",
            },
            {
                "name": "user-timers",
                "command": "systemctl --user list-timers",
                "timeout": 30.0,
                "success_exit_codes": [0],
                "notes": None,
                "status": "failed",
                "failure": "exit code 1 is not in success-exit-codes [0]",
                "exit_code": 1,
                "signal": None,
                "timed_out": False,
                "stdout_truncated": False,
                "stderr_truncated": False,
                "duration": 0.123,
                "stdout": "",
                "stderr": "Failed to connect to bus: No medium found\n",
            },
        ],
    }


def test_the_json_keeps_text_readable_and_lists_exit_codes_in_order() -> None:
    codes = frozenset({255, 1, 64})
    probe = result("café", "echo café", stdout="café\n", success_exit_codes=codes)

    text = evidence_json(evidence(probe))

    assert '"stdout": "café\\n"' in text
    assert json.loads(text)["probes"][0]["success_exit_codes"] == [1, 64, 255]
    assert text.endswith("}\n")


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (1024 * 1024, "1 MiB"),
        (3 * 1024 * 1024, "3 MiB"),
        (64 * 1024, "64 KiB"),
        (1024, "1 KiB"),
        (1536, "1536 bytes"),
        (1000, "1000 bytes"),
        (1, "1 byte"),
        (0, "0 bytes"),
    ],
)
def test_format_size(size: int, expected: str) -> None:
    assert format_size(size) == expected
