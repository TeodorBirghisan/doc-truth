import argparse
import json
import sys
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from doc_truth.compare import InvalidAnswerError, compare
from doc_truth.config import DEFAULT_MODEL, DEFAULT_MODEL_TIMEOUT, ModelSettings
from doc_truth.evidence import evidence_markdown
from doc_truth.findings import Finding, ProbeQuote
from doc_truth.model import Answer, ModelError, ask_claude
from doc_truth.prompt import Prompt, build_prompt
from evals.cases import Case, case_directories, load_case
from evals.score import CaseScore, score

RUNS_DIR = Path(__file__).resolve().parent / "runs"
DEFAULT_RUNS = 3
DEFAULT_JOBS = 4


@dataclass(frozen=True, slots=True, kw_only=True)
class Run:
    number: int
    answers: tuple[Answer, ...]
    findings: tuple[Finding, ...]
    score: CaseScore | None
    error: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class CaseResult:
    case: Case
    runs: tuple[Run, ...]

    def hits(self, must_find_id: str) -> int:
        return sum(must_find_id in run.score.found for run in self.runs if run.score is not None)

    @property
    def needed(self) -> int:
        return len(self.runs) // 2 + 1

    @property
    def passed(self) -> bool:
        return all(
            self.hits(matcher.id) >= self.needed for matcher in self.case.expected.must_find
        ) and all(
            run.score is not None and not run.score.violations and not run.score.false_positives
            for run in self.runs
        )

    @property
    def cost_usd(self) -> float:
        return sum(answer.cost_usd for run in self.runs for answer in run.answers)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    directories = case_directories()
    unknown = sorted(set(args.cases) - {directory.name for directory in directories})
    if unknown:
        print(f"evals.live: error: no such case: {', '.join(unknown)}", file=sys.stderr)
        return 2
    cases = [load_case(path) for path in directories if not args.cases or path.name in args.cases]
    settings = ModelSettings(name=args.model, timeout=args.timeout)
    output = RUNS_DIR / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output.mkdir(parents=True)
    prompts = {
        case.name: build_prompt(case.docs, evidence_markdown(case.evidence)) for case in cases
    }
    for case in cases:
        prompt = prompts[case.name]
        (output / f"{case.name}.prompt.md").write_text(
            f"{prompt.system}\n\n---\n\n{prompt.user}", encoding="utf-8"
        )
    tasks = [(case, number) for case in cases for number in range(1, args.runs + 1)]

    def run(task: tuple[Case, int]) -> Run:
        case, number = task
        result = _run_once(case, number, prompts[case.name], settings)
        _save(output / f"{case.name}-{number}.json", result)
        status = (
            "error" if result.error else "pass" if result.score and result.score.passed else "fail"
        )
        print(f"{case.name} #{number}: {status}", file=sys.stderr, flush=True)
        return result

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        runs = list(pool.map(run, tasks))
    results = [
        CaseResult(
            case=case,
            runs=tuple(run for (owner, _), run in zip(tasks, runs, strict=True) if owner is case),
        )
        for case in cases
    ]
    print(_report(results, settings))
    print(f"Answers and prompts: {output}")
    return 0 if all(result.passed for result in results) else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.live",
        description=(
            "Send every evaluation case to the real model several times and score the answers. "
            "This costs tokens. Exits with 0 when every case passes and 1 when any fails."
        ),
    )
    parser.add_argument("cases", nargs="*", metavar="CASE", help="only these cases")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="default: %(default)s")
    parser.add_argument("--runs", type=_positive, default=DEFAULT_RUNS, help="default: %(default)s")
    parser.add_argument(
        "--jobs", type=_positive, default=DEFAULT_JOBS, help="calls at once (default: %(default)s)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_MODEL_TIMEOUT,
        help="seconds per call (default: %(default)g)",
    )
    return parser


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _run_once(case: Case, number: int, prompt: Prompt, settings: ModelSettings) -> Run:
    try:
        comparison = compare(prompt, partial(ask_claude, settings=settings))
    except InvalidAnswerError as error:
        return Run(number=number, answers=error.answers, findings=(), score=None, error=str(error))
    except ModelError as error:
        return Run(number=number, answers=(), findings=(), score=None, error=str(error))
    return Run(
        number=number,
        answers=comparison.answers,
        findings=comparison.findings,
        score=score(case.expected, comparison.findings),
        error=None,
    )


def _save(path: Path, run: Run) -> None:
    data = {
        "error": run.error,
        "score": None
        if run.score is None
        else {
            "passed": run.score.passed,
            "found": run.score.found,
            "weak": run.score.weak,
            "missed": run.score.missed,
            "violations": run.score.violations,
            "false_positives": run.score.false_positives,
            "allowed": run.score.allowed,
        },
        "answers": [
            {
                "models": answer.models,
                "input_tokens": answer.input_tokens,
                "output_tokens": answer.output_tokens,
                "cost_usd": answer.cost_usd,
                "duration": round(answer.duration, 1),
                "text": answer.text,
            }
            for answer in run.answers
        ],
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _report(results: Sequence[CaseResult], settings: ModelSettings) -> str:
    width = max(len(result.case.name) for result in results)
    lines = [f"{'case':<{width}}  must-find  wrong  errors  cost     result"]
    details: list[str] = []
    for result in results:
        must_find = result.case.expected.must_find
        hits = min((result.hits(matcher.id) for matcher in must_find), default=None)
        found = "-" if hits is None else f"{hits}/{len(result.runs)}"
        wrong = sum(
            len(run.score.violations) + len(run.score.false_positives)
            for run in result.runs
            if run.score is not None
        )
        errors = sum(run.error is not None for run in result.runs)
        lines.append(
            f"{result.case.name:<{width}}  {found:<9}  {wrong:<5}  {errors:<6}  "
            f"${result.cost_usd:<7.4f} {'pass' if result.passed else 'FAIL'}"
        )
        details.extend(_details(result))
    runs = [run for result in results for run in result.runs]
    answers = [answer for run in runs for answer in run.answers]
    models = sorted({model for answer in answers for model in answer.models})
    lines.append("")
    lines.append(
        f"{sum(result.passed for result in results)} of {len(results)} cases passed, "
        f"{len(runs)} runs, {len(answers)} calls with --model {settings.name} "
        f"(answered by {', '.join(models) or 'no model'}), "
        f"{sum(answer.input_tokens for answer in answers)} input and "
        f"{sum(answer.output_tokens for answer in answers)} output tokens, "
        f"${sum(answer.cost_usd for answer in answers):.4f}."
    )
    if details:
        lines.extend(["", *details])
    return "\n".join(lines)


def _details(result: CaseResult) -> list[str]:
    lines: list[str] = []
    name = result.case.name
    for matcher in result.case.expected.must_find:
        hits = result.hits(matcher.id)
        if hits < len(result.runs):
            lines.append(f"{name}: must-find {matcher.id} found in {hits} of {len(result.runs)}")
    for run in result.runs:
        if run.error is not None:
            lines.append(f"{name} #{run.number}: {run.error}")
        if run.score is None:
            continue
        for index, matcher_id in run.score.violations:
            lines.append(
                f"{name} #{run.number}: violates {matcher_id}: {_describe(run.findings[index])}"
            )
        for index in run.score.false_positives:
            lines.append(f"{name} #{run.number}: false positive: {_describe(run.findings[index])}")
        for matcher_id in run.score.weak:
            lines.append(f"{name} #{run.number}: {matcher_id} found, but only as suspect")
    return lines


def _describe(finding: Finding) -> str:
    doc = finding.doc
    evidence = finding.evidence
    source = (
        f"probe {evidence.probe}"
        if isinstance(evidence, ProbeQuote)
        else f"{evidence.file}:{evidence.line}"
    )
    return f"{doc.file}:{doc.line} vs {source} [{finding.confidence}] {finding.title}"


if __name__ == "__main__":
    sys.exit(main())
