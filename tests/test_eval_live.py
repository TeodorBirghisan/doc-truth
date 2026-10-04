import hashlib
import json
from pathlib import Path

import pytest
from fake_claude import COST_USD, MODEL
from fakes import ANSWER, INIT, NO_FINDINGS, FakeClaude

from doc_truth.evidence import evidence_markdown
from doc_truth.prompt import build_prompt
from evals import live
from evals.cases import CASES_DIR, case_directories, load_case
from evals.live import CaseResult, Run
from evals.score import CaseScore

CASE_NAMES = [path.name for path in case_directories()]


@pytest.fixture
def runs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "runs"
    monkeypatch.setattr(live, "RUNS_DIR", directory)
    return directory


def reference(name: str) -> str:
    return (CASES_DIR / name / "reference.json").read_text(encoding="utf-8")


def prompt_key(name: str) -> str:
    case = load_case(CASES_DIR / name)
    prompt = build_prompt(case.docs, evidence_markdown(case.evidence))
    return hashlib.sha256(prompt.user.encode()).hexdigest()


def finding(**changes: object) -> str:
    (data,) = json.loads(reference("failed-user-probe"))["findings"]
    data.update(changes)
    return json.dumps({"findings": [data]})


def make_score(
    found: tuple[str, ...] = (),
    *,
    missed: tuple[str, ...] = (),
    violations: tuple[tuple[int, str], ...] = (),
    false_positives: tuple[int, ...] = (),
    allowed: tuple[int, ...] = (),
) -> CaseScore:
    return CaseScore(
        found=found,
        weak=(),
        missed=missed,
        violations=violations,
        false_positives=false_positives,
        allowed=allowed,
    )


def make_run(number: int, score: CaseScore | None) -> Run:
    return Run(
        number=number,
        answers=(),
        findings=(),
        score=score,
        error=None if score else "claude failed",
    )


def result_for(*scores: CaseScore | None) -> CaseResult:
    case = load_case(CASES_DIR / "failed-user-probe")
    runs = tuple(make_run(number, score) for number, score in enumerate(scores, start=1))
    return CaseResult(case=case, runs=runs)


FOUND = make_score(("backup-time",))
MISSED = make_score(missed=("backup-time",))


@pytest.mark.parametrize(
    ("scores", "passed"),
    [
        ((FOUND, FOUND, FOUND), True),
        ((FOUND, MISSED, FOUND), True),
        ((FOUND, MISSED, MISSED), False),
        ((FOUND,), True),
        ((MISSED,), False),
        ((FOUND, FOUND, MISSED, MISSED), False),
        ((FOUND, FOUND, FOUND, MISSED), True),
        ((FOUND, FOUND, None), False),
        ((FOUND, FOUND, make_score(("backup-time",), violations=((0, "x"),))), False),
        ((FOUND, FOUND, make_score(("backup-time",), false_positives=(1,))), False),
        ((FOUND, FOUND, make_score(("backup-time",), allowed=(1,))), True),
    ],
)
def test_a_case_passes_on_a_majority_of_runs_with_nothing_wrong(
    scores: tuple[CaseScore | None, ...], passed: bool
) -> None:
    assert result_for(*scores).passed is passed


def test_a_case_without_must_finds_passes_when_every_run_is_clean() -> None:
    case = load_case(CASES_DIR / "clean")
    runs = (make_run(1, make_score()), make_run(2, make_score()))

    assert CaseResult(case=case, runs=runs).passed


def test_the_reference_answers_pass_through_the_real_model_call(
    fake_claude: FakeClaude, runs_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_claude.play(*ANSWER, answers={prompt_key(name): reference(name) for name in CASE_NAMES})

    exit_code = live.main(["--runs", "1"])

    out = capsys.readouterr().out
    assert exit_code == 0
    summary = f"10 of 10 cases passed, 10 runs, 10 calls with --model sonnet (answered by {MODEL})"
    assert summary in out
    assert f"12030 input and 500 output tokens, ${10 * COST_USD:.4f}." in out
    assert "timeshift-cron-contradiction  1/1        0      0       $0.0125  pass" in out
    (output,) = runs_dir.iterdir()
    assert f"Answers and prompts: {output}" in out
    assert sorted(path.name for path in output.iterdir()) == sorted(
        [f"{name}-1.json" for name in CASE_NAMES] + [f"{name}.prompt.md" for name in CASE_NAMES]
    )


def test_each_run_is_saved(fake_claude: FakeClaude, runs_dir: Path) -> None:
    fake_claude.play(*ANSWER, answers={"*": reference("stale-status")})

    live.main(["stale-status", "--runs", "1", "--model", "opus"])

    (output,) = runs_dir.iterdir()
    saved = json.loads((output / "stale-status-1.json").read_text(encoding="utf-8"))
    assert saved["error"] is None
    assert saved["score"] == {
        "passed": True,
        "found": ["offsite-running"],
        "weak": [],
        "missed": [],
        "violations": [],
        "false_positives": [],
        "allowed": [],
    }
    (answer,) = saved["answers"]
    assert answer["text"] == reference("stale-status")
    assert answer["models"] == [MODEL]
    assert (answer["input_tokens"], answer["output_tokens"]) == (1203, 50)
    assert answer["cost_usd"] == COST_USD
    prompt = (output / "stale-status.prompt.md").read_text(encoding="utf-8")
    assert prompt.startswith("You check operations documentation")
    assert "\n\n---\n\n# Documents\n\n## docs/backups.md\n" in prompt
    assert "--model=opus" in fake_claude.calls()[0]["argv"]


@pytest.mark.parametrize(
    ("case", "answer", "detail"),
    [
        (
            "failed-user-probe",
            NO_FINDINGS,
            "failed-user-probe: must-find backup-time found in 0 of 2",
        ),
        (
            "failed-user-probe",
            finding(confidence="suspect"),
            "failed-user-probe #1: backup-time found, but only as suspect",
        ),
        (
            "failed-user-probe",
            finding(evidence={"probe": "user-timers", "quote": "Failed to connect to bus"}),
            "failed-user-probe #2: violates failed-user-probes: docs/operations.md:17 vs probe "
            "user-timers [confirmed] The restic backup runs at 03:00, not 02:00",
        ),
        (
            "clean",
            finding(evidence={"file": "docs/services.md", "line": 3, "quote": "x"}),
            "clean #1: false positive: docs/operations.md:17 vs docs/services.md:3 [confirmed] "
            "The restic backup runs at 03:00, not 02:00",
        ),
        (
            "clean",
            "Everything matches.",
            "clean #2: the model's answer was unusable 2 times in a row",
        ),
    ],
)
def test_a_failing_case_says_why(
    fake_claude: FakeClaude,
    runs_dir: Path,
    capsys: pytest.CaptureFixture[str],
    case: str,
    answer: str,
    detail: str,
) -> None:
    fake_claude.play(*ANSWER, answers={"*": answer})

    exit_code = live.main([case, "--runs", "2"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "0 of 1 cases passed" in out
    assert f"{case}  " in out and " FAIL" in out
    assert detail in out


def test_a_model_that_fails_is_reported(
    fake_claude: FakeClaude, runs_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    failed = {"type": "result", "is_error": True, "result": "Not logged in · Please run /login"}
    fake_claude.play(("out", INIT), ("out", failed), ("exit", 1))

    exit_code = live.main(["clean", "--runs", "1"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "clean  -          0      1       $0.0000  FAIL" in out
    assert "answered by no model" in out
    assert "clean #1: claude failed: Not logged in · Please run /login" in out


def test_an_unknown_case(runs_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert live.main(["clean", "nope", "also-nope"]) == 2
    assert capsys.readouterr().err == "evals.live: error: no such case: also-nope, nope\n"
    assert not runs_dir.exists()


@pytest.mark.parametrize("option", ["--runs", "--jobs"])
def test_counts_must_be_positive(option: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        live.main([option, "0"])

    assert caught.value.code == 2
    assert "must be at least 1" in capsys.readouterr().err
