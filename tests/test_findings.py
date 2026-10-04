import copy

import pytest

from doc_truth.findings import (
    Confidence,
    DocQuote,
    Finding,
    FindingsError,
    Fix,
    Kind,
    ProbeQuote,
    parse_findings,
)

VALID: dict[str, object] = {
    "kind": "contradiction",
    "title": "The backup runs at 03:00, not 02:00",
    "doc": {"file": "docs/operations.md", "line": 14, "quote": "daily 02:00"},
    "evidence": {"probe": "custom-timers", "quote": "OnCalendar=*-*-* 03:00:00"},
    "confidence": "confirmed",
    "fix": "doc",
    "reason": "The timer runs at 03:00.",
}


def answer(**changes: object) -> dict[str, object]:
    finding = copy.deepcopy(VALID)
    for key, value in changes.items():
        if value is None:
            del finding[key]
        else:
            finding[key] = value
    return {"findings": [finding]}


def problems(data: object) -> tuple[str, ...]:
    with pytest.raises(FindingsError) as caught:
        parse_findings(data)
    return caught.value.problems


def test_a_finding_with_probe_evidence() -> None:
    assert parse_findings(answer()) == (
        Finding(
            kind=Kind.CONTRADICTION,
            title="The backup runs at 03:00, not 02:00",
            doc=DocQuote(file="docs/operations.md", line=14, end_line=14, quote="daily 02:00"),
            evidence=ProbeQuote(probe="custom-timers", quote="OnCalendar=*-*-* 03:00:00"),
            confidence=Confidence.CONFIRMED,
            fix=Fix.DOC,
            reason="The timer runs at 03:00.",
        ),
    )


def test_a_cross_doc_finding_quotes_another_doc_as_evidence() -> None:
    evidence = {"file": "notes/apt.md", "line": 5, "end_line": 6, "quote": "noble-updates"}

    (finding,) = parse_findings(answer(kind="cross-doc-contradiction", evidence=evidence))

    assert finding.kind is Kind.CROSS_DOC_CONTRADICTION
    assert finding.evidence == DocQuote(
        file="notes/apt.md", line=5, end_line=6, quote="noble-updates"
    )


def test_an_answer_without_findings_is_valid() -> None:
    assert parse_findings({"findings": []}) == ()


def test_unknown_keys_are_ignored() -> None:
    data = answer(severity="high")
    data["model_notes"] = "none"

    assert len(parse_findings(data)) == 1


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ([], "the answer must be a JSON object, found an array"),
        ({}, "missing findings"),
        ({"findings": None}, "findings must be an array, found null"),
        ({"findings": {}}, "findings must be an array, found an object"),
        ({"findings": ["x"]}, "findings[0]: must be an object, found a string"),
    ],
)
def test_the_shape_of_the_answer(data: object, expected: str) -> None:
    assert problems(data) == (expected,)


def test_every_problem_is_reported_at_once() -> None:
    data = {"findings": [VALID, {"kind": "typo", "doc": {"file": "a.md", "line": 0}}]}

    assert problems(data) == (
        'findings[1].kind: must be one of "contradiction", "cross-doc-contradiction", '
        '"omission", "stale-status", found "typo"',
        "findings[1]: missing title",
        "findings[1].doc.line: must be a line number from 1, found 0",
        "findings[1].doc: missing quote",
        "findings[1]: missing evidence",
        "findings[1]: missing confidence",
        "findings[1]: missing fix",
        "findings[1]: missing reason",
    )


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"confidence": "certain"}, 'must be one of "confirmed", "suspect", found "certain"'),
        ({"fix": 1}, 'must be one of "doc", "host", found 1'),
        ({"title": ""}, "findings[0].title: must not be empty"),
        ({"title": "  "}, "findings[0].title: must not be empty"),
        ({"reason": 3}, "findings[0].reason: must be a string, found a number"),
        ({"doc": "docs/a.md:3"}, "findings[0].doc: must be an object, found a string"),
        ({"evidence": None}, "findings[0]: missing evidence"),
    ],
)
def test_invalid_fields(changes: dict[str, object], expected: str) -> None:
    (problem,) = problems(answer(**changes))

    assert problem.endswith(expected)


@pytest.mark.parametrize("line", [0, -1, 1.5, "3", True, None])
def test_line_numbers_are_integers_from_one(line: object) -> None:
    doc = {"file": "a.md", "line": line, "quote": "x"}

    (problem,) = problems(answer(doc=doc))

    assert problem.startswith("findings[0].doc.line: must be a line number from 1, found ")


def test_a_range_cannot_end_before_it_starts() -> None:
    doc = {"file": "a.md", "line": 5, "end_line": 4, "quote": "x"}

    assert problems(answer(doc=doc)) == (
        "findings[0].doc.end_line: must not be before line 5, found 4",
    )


@pytest.mark.parametrize(
    "evidence",
    [
        {"quote": "x"},
        {"probe": "p", "file": "a.md", "line": 1, "quote": "x"},
    ],
)
def test_evidence_names_either_a_probe_or_a_file(evidence: dict[str, object]) -> None:
    assert problems(answer(evidence=evidence)) == (
        "findings[0].evidence: must name either a probe or a file",
    )


def test_probe_evidence_needs_a_quote() -> None:
    assert problems(answer(evidence={"probe": "p"})) == ("findings[0].evidence: missing quote",)


def test_the_error_message_lists_the_problems() -> None:
    assert str(FindingsError(["one"])) == "invalid findings: one"
    assert str(FindingsError(["one", "two"])) == ("invalid findings: 2 problems\n  - one\n  - two")


def test_a_quote_needs_a_line() -> None:
    assert problems(answer(doc={"file": "a.md", "quote": "x"})) == (
        "findings[0].doc: missing line",
    )


def test_types_are_named_the_way_json_names_them() -> None:
    assert problems(answer(title=True)) == ("findings[0].title: must be a string, found a boolean",)
    assert problems({"findings": (1,)}) == ("findings must be an array, found tuple",)
