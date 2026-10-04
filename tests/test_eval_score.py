from doc_truth.findings import Confidence, DocQuote, Finding, Fix, Kind, ProbeQuote
from evals.cases import Expected, Location, Matcher
from evals.score import score

OPS = "docs/operations.md"
NOTES = "notes/apt.md"


def matcher(
    matcher_id: str,
    *,
    doc: tuple[Location, ...] = (),
    probes: tuple[str, ...] = (),
    evidence_docs: tuple[Location, ...] = (),
    confidence: Confidence | None = None,
) -> Matcher:
    return Matcher(
        id=matcher_id,
        doc=doc,
        probes=probes,
        evidence_docs=evidence_docs,
        confidence=confidence,
        note=None,
    )


def at(file: str, start: int, end: int | None = None) -> Location:
    return Location(file=file, start=start, end=start if end is None else end)


def finding(
    file: str = OPS,
    line: int = 10,
    end_line: int | None = None,
    *,
    evidence: ProbeQuote | DocQuote | None = None,
    confidence: Confidence = Confidence.CONFIRMED,
) -> Finding:
    return Finding(
        kind=Kind.CONTRADICTION,
        title="title",
        doc=DocQuote(
            file=file, line=line, end_line=line if end_line is None else end_line, quote="q"
        ),
        evidence=ProbeQuote(probe="timers", quote="q") if evidence is None else evidence,
        confidence=confidence,
        fix=Fix.DOC,
        reason="reason",
    )


def expected(
    must_find: tuple[Matcher, ...] = (),
    must_not_find: tuple[Matcher, ...] = (),
    allowed: tuple[Matcher, ...] = (),
) -> Expected:
    return Expected(must_find=must_find, must_not_find=must_not_find, allowed=allowed)


BACKUP = matcher("backup", doc=(at(OPS, 10),), probes=("timers",), confidence=Confidence.CONFIRMED)


def test_a_matching_finding_is_found() -> None:
    result = score(expected(must_find=(BACKUP,)), [finding()])

    assert result.found == ("backup",)
    assert result.passed


def test_no_findings_misses_every_must_find() -> None:
    result = score(expected(must_find=(BACKUP,)), [])

    assert result.missed == ("backup",)
    assert not result.passed


def test_no_findings_passes_a_case_that_expects_none() -> None:
    assert score(expected(), []).passed


def test_a_finding_where_none_is_expected_is_a_false_positive() -> None:
    result = score(expected(), [finding()])

    assert result.false_positives == (0,)
    assert not result.passed


def test_a_suspect_where_confirmed_is_required_is_weak_not_a_false_positive() -> None:
    result = score(expected(must_find=(BACKUP,)), [finding(confidence=Confidence.SUSPECT)])

    assert (result.found, result.weak, result.missed, result.false_positives) == (
        (),
        ("backup",),
        (),
        (),
    )
    assert not result.passed


def test_a_confirmed_finding_outweighs_a_weak_one() -> None:
    findings = [finding(confidence=Confidence.SUSPECT), finding()]

    result = score(expected(must_find=(BACKUP,)), findings)

    assert (result.found, result.weak) == (("backup",), ())
    assert result.passed


def test_a_must_find_without_a_confidence_accepts_either() -> None:
    either = matcher("backup", doc=(at(OPS, 10),))

    assert score(expected(must_find=(either,)), [finding(confidence=Confidence.SUSPECT)]).passed


def test_one_problem_reported_twice_is_found_twice() -> None:
    two_docs = matcher("cron", doc=(at(OPS, 10), at(NOTES, 3, 5)), probes=("timers",))

    result = score(expected(must_find=(two_docs,)), [finding(), finding(NOTES, 5)])

    assert result.found == ("cron",)
    assert result.false_positives == ()


def test_lines_match_when_the_ranges_overlap() -> None:
    section = matcher("section", doc=(at(OPS, 10, 20),))
    case = expected(must_find=(section,))

    assert score(case, [finding(line=20, end_line=25)]).passed
    assert score(case, [finding(line=5, end_line=10)]).passed
    assert score(case, [finding(line=12)]).passed
    assert score(case, [finding(line=21)]).missed == ("section",)
    assert score(case, [finding(line=9)]).missed == ("section",)
    assert score(case, [finding(NOTES, 12)]).missed == ("section",)


def test_evidence_from_another_probe_does_not_match() -> None:
    other_probe = finding(evidence=ProbeQuote(probe="cron", quote="q"))

    result = score(expected(must_find=(BACKUP,)), [other_probe])

    assert (result.missed, result.false_positives) == (("backup",), (0,))


def test_cross_doc_evidence_matches_by_location() -> None:
    cross_doc = matcher("apt", doc=(at(OPS, 10),), evidence_docs=(at(NOTES, 3, 5),))
    case = expected(must_find=(cross_doc,))

    assert score(
        case, [finding(evidence=DocQuote(file=NOTES, line=4, end_line=4, quote="q"))]
    ).passed
    assert not score(case, [finding()]).passed
    assert not score(
        case, [finding(evidence=DocQuote(file=NOTES, line=6, end_line=6, quote="q"))]
    ).passed


def test_a_violation_counts_even_where_a_must_find_also_matches() -> None:
    failed_probe = matcher("failed", probes=("timers",))

    result = score(expected(must_find=(BACKUP,), must_not_find=(failed_probe,)), [finding()])

    assert result.violations == ((0, "failed"),)
    assert result.missed == ("backup",)
    assert not result.passed


def test_a_finding_can_violate_several_rules() -> None:
    rules = (matcher("probe", probes=("timers",)), matcher("line", doc=(at(OPS, 10),)))

    assert score(expected(must_not_find=rules), [finding()]).violations == (
        (0, "probe"),
        (0, "line"),
    )


def test_a_confidence_filter_limits_a_violation_and_allowed_findings() -> None:
    lines = (at(OPS, 10),)
    case = expected(
        must_not_find=(matcher("confirmed", doc=lines, confidence=Confidence.CONFIRMED),),
        allowed=(matcher("suspect", doc=lines, confidence=Confidence.SUSPECT),),
    )

    confirmed = score(case, [finding()])
    suspect = score(case, [finding(confidence=Confidence.SUSPECT)])

    assert (confirmed.violations, confirmed.allowed) == (((0, "confirmed"),), ())
    assert (suspect.violations, suspect.allowed, suspect.passed) == ((), (0,), True)


def test_results_follow_the_order_of_the_expectations() -> None:
    first = matcher("first", doc=(at(OPS, 1),))
    second = matcher("second", doc=(at(OPS, 2),))
    third = matcher("third", doc=(at(OPS, 3),), confidence=Confidence.CONFIRMED)

    result = score(
        expected(must_find=(first, second, third)),
        [finding(line=3, confidence=Confidence.SUSPECT), finding(line=2)],
    )

    assert (result.found, result.weak, result.missed) == (("second",), ("third",), ("first",))
