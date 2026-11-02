import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from examples import fenced_blocks, fenced_in
from fakes import ANSWER, INIT, FakeClaude

from doc_truth.collect import (
    LOCALE,
    MAX_STDERR,
    MAX_STDOUT,
    REMOVED_VARIABLES,
    STOP_GRACE,
    probe_environment,
    probe_failure,
)
from doc_truth.compare import InvalidAnswerError, compare
from doc_truth.config import (
    DEFAULT_MODEL,
    DEFAULT_MODEL_TIMEOUT,
    DEFAULT_TIMEOUT,
    DOC_KEYS,
    MODEL_KEYS,
    PROBE_KEYS,
    TOP_LEVEL_KEYS,
    ModelSettings,
    Probe,
    load_config,
)
from doc_truth.evidence import FAILED_LABEL, Evidence, ProbeResult, format_size
from doc_truth.findings import Confidence, DocQuote, Finding, Fix, Kind, ProbeQuote
from doc_truth.model import PROMPT_TOO_LONG, Answer, ModelError, ask_claude
from doc_truth.prompt import PROMPT_VERSION, Prompt
from doc_truth.report import Report, report_markdown
from doc_truth.runs import (
    DEFAULT_OUTPUT_DIR_NAME,
    EVIDENCE_JSON,
    EVIDENCE_MARKDOWN,
    REPORT_JSON,
    REPORT_MARKDOWN,
    RUNS_DIR_NAME,
)

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "docs" / "configuration.md"


@pytest.mark.parametrize("document", ["README.md", "docs/configuration.md"])
def test_toml_examples_are_valid_configs(tmp_path: Path, document: str) -> None:
    examples = fenced_blocks(ROOT / document, "toml")
    assert examples, f"{document} has no TOML examples"

    for example in examples:
        path = tmp_path / "doc-truth.toml"
        path.write_text(example, encoding="utf-8")
        load_config(path)


def test_the_reference_documents_every_key() -> None:
    reference = REFERENCE.read_text(encoding="utf-8")
    tables = {"docs": "`[[docs]]`", "probes": "`[[probes]]`", "model": "`[model]`"}
    documented = [*tables.values(), *(f"`{key}`" for key in (*DOC_KEYS, *PROBE_KEYS, *MODEL_KEYS))]

    assert set(tables) == set(TOP_LEVEL_KEYS)
    assert [form for form in documented if form not in reference] == []


def test_the_reference_gives_the_model_defaults() -> None:
    reference = REFERENCE.read_text(encoding="utf-8")

    assert f'| `name` | string | `"{DEFAULT_MODEL}"` |' in reference
    assert f"| `timeout` | number | `{DEFAULT_MODEL_TIMEOUT:g}` |" in reference


def flowed(document: Path) -> str:
    return " ".join(document.read_text(encoding="utf-8").split())


def test_the_reference_describes_how_probes_run() -> None:
    reference = flowed(REFERENCE)
    facts = [
        "`bash -o pipefail`",
        f"`LC_ALL={LOCALE}`",
        *(f"`{name}` removed" for name in REMOVED_VARIABLES),
        f"{STOP_GRACE:g} seconds later",
        f"first {format_size(MAX_STDOUT)} of a probe's standard output",
        f"first {format_size(MAX_STDERR)} of its standard error",
    ]

    assert [fact for fact in facts if fact not in reference] == []


def test_the_reference_says_where_runs_are_kept() -> None:
    reference = flowed(REFERENCE)
    facts = [f"`{DEFAULT_OUTPUT_DIR_NAME}/{RUNS_DIR_NAME}/<UTC time>/`", "`--output-dir PATH`"]

    assert [fact for fact in facts if fact not in reference] == []


def test_the_readme_describes_the_run_folder() -> None:
    readme = flowed(ROOT / "README.md")
    facts = [
        f"`{DEFAULT_OUTPUT_DIR_NAME}/{RUNS_DIR_NAME}/<UTC time>/`",
        f"`{EVIDENCE_MARKDOWN}`",
        f"`{EVIDENCE_JSON}`",
        f"`{REPORT_MARKDOWN}`",
        f"`{REPORT_JSON}`",
        "`--output-dir PATH`",
    ]

    assert [fact for fact in facts if fact not in readme] == []


def test_the_readme_shows_a_report_the_way_the_report_writes_it() -> None:
    timers = Probe(
        name="timer-schedules",
        command="true",
        timeout=30,
        success_exit_codes=frozenset({0}),
        notes=None,
    )
    restic = replace(timers, name="restic-version")
    worked = ProbeResult(
        probe=timers,
        stdout="",
        stderr="",
        exit_code=0,
        signal=None,
        duration=0.1,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        failure=None,
    )
    started = datetime(2026, 11, 2, 18, 26, 34, tzinfo=UTC)
    report = Report(
        evidence=Evidence(
            tool_version="0.1.0.dev0",
            host="homeserver",
            user="ops",
            timezone="UTC",
            utc_offset="+00:00",
            started_at=started,
            finished_at=started,
            config_path=Path("doc-truth.toml"),
            results=(
                worked,
                replace(
                    worked,
                    probe=restic,
                    exit_code=127,
                    failure=probe_failure(
                        restic,
                        exit_code=127,
                        signal_name=None,
                        timed_out=False,
                        stdout_truncated=False,
                    ),
                ),
            ),
        ),
        docs=("docs/operations.md",),
        prompt_version=PROMPT_VERSION,
        requested_model="sonnet",
        answers=(
            Answer(
                text="",
                models=("claude-sonnet-5-5",),
                input_tokens=3872,
                output_tokens=290,
                cost_usd=0.02,
                duration=1.0,
            ),
        ),
        findings=(
            Finding(
                kind=Kind.CONTRADICTION,
                title="dpkg-db-backup.timer runs daily, not weekly",
                doc=DocQuote(
                    file="docs/operations.md",
                    line=6,
                    end_line=6,
                    quote="`dpkg-db-backup.timer` backs up the package database once a week.",
                ),
                evidence=ProbeQuote(
                    probe="timer-schedules",
                    quote="dpkg-db-backup.timer active waiting { OnCalendar=*-*-* 00:00:00 }",
                ),
                confidence=Confidence.CONFIRMED,
                fix=Fix.DOC,
                reason=(
                    "The timer is active and its calendar is every day at 00:00:00, with no "
                    "weekday restriction. The document says it runs once a week."
                ),
            ),
        ),
        dropped=(),
        finished_at=started,
    )
    without_title = report_markdown(report).split("\n\n", 1)[1]

    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert f"````markdown\n{without_title}````\n" in readme


def readme_section(heading: str) -> str:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    return readme.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]


def test_the_quick_start_runs(tmp_path: Path, fake_claude: FakeClaude) -> None:
    install, *steps = fenced_in(readme_section("Quick start"), "sh")
    assert install.startswith("uv tool install ")

    version = subprocess.run(
        ["bash", "--version"],
        env=probe_environment(os.environ),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()[0]
    finding = {
        "kind": "contradiction",
        "title": "Host runs a newer bash",
        "doc": {"file": "operations.md", "line": 3, "quote": "This host runs bash 3.2."},
        "evidence": {"probe": "bash-version", "quote": version},
        "confidence": "confirmed",
        "fix": "doc",
        "reason": "The doc says 3.2.",
    }
    fake_claude.play(*ANSWER, answers={"*": json.dumps({"findings": [finding]})})
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command = bin_dir / "doc-truth"
    command.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m doc_truth "$@"\n', encoding="utf-8")
    command.chmod(0o755)

    (tmp_path / "doc-truth-demo").mkdir()
    mine = tmp_path / "operations.md"
    mine.write_text("mine\n", encoding="utf-8")

    done = subprocess.run(
        ["bash", "-uo", "pipefail", "-c", "\n".join(steps)],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert done.returncode == 0, done.stderr
    assert "is valid." in done.stdout
    assert version in done.stdout
    assert "exit code: 1\n" in done.stdout
    assert "**1 finding: 1 confirmed, 0 suspect.**" in done.stdout
    assert "doc-truth: error" not in done.stderr
    assert mine.read_text(encoding="utf-8") == "mine\n"


def troubleshooting() -> str:
    return " ".join(readme_section("Troubleshooting").split())


def model_error(timeout: float = DEFAULT_MODEL_TIMEOUT) -> str:
    prompt = Prompt(version=PROMPT_VERSION, system="", user="")
    with pytest.raises(ModelError) as caught:
        ask_claude(prompt, settings=ModelSettings(timeout=timeout))
    return str(caught.value)


def test_troubleshooting_quotes_the_error_for_a_missing_claude(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "")

    assert f"`{model_error().split(';')[0]}`" in troubleshooting()


def test_troubleshooting_quotes_how_doc_truth_reports_no_login(fake_claude: FakeClaude) -> None:
    fake_claude.play(
        ("out", INIT),
        (
            "out",
            {"type": "result", "is_error": True, "result": "Not logged in · Please run /login"},
        ),
        ("exit", 1),
    )

    assert f"`{model_error()}`" in troubleshooting()


def test_troubleshooting_quotes_the_model_timeout(fake_claude: FakeClaude) -> None:
    fake_claude.play(("sleep", 5))

    message = model_error(timeout=0.2).split(";")[0].replace("0.2", f"{DEFAULT_MODEL_TIMEOUT:g}")

    assert f"`{message}`" in troubleshooting()


def test_troubleshooting_quotes_the_prompt_size_error() -> None:
    assert f"`{PROMPT_TOO_LONG}`" in troubleshooting()


def test_troubleshooting_quotes_the_unusable_answer_error() -> None:
    answer = Answer(
        text="not json", models=(), input_tokens=0, output_tokens=0, cost_usd=0, duration=0
    )
    prompt = Prompt(version=PROMPT_VERSION, system="", user="")

    with pytest.raises(InvalidAnswerError) as caught:
        compare(prompt, lambda _: answer)

    assert f"`{str(caught.value).split(';')[0]}`" in troubleshooting()


def test_troubleshooting_quotes_a_probe_timeout() -> None:
    probe = Probe(
        name="slow",
        command="sleep 5",
        timeout=DEFAULT_TIMEOUT,
        success_exit_codes=frozenset({0}),
        notes=None,
    )

    message = probe_failure(
        probe, exit_code=None, signal_name=None, timed_out=True, stdout_truncated=False
    )

    assert f"`{message}`" in troubleshooting()
    assert f"`{FAILED_LABEL}`" in troubleshooting()
