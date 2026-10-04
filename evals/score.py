from collections.abc import Sequence
from dataclasses import dataclass

from doc_truth.findings import Finding, ProbeQuote
from evals.cases import Expected, Matcher


@dataclass(frozen=True, slots=True, kw_only=True)
class CaseScore:
    found: tuple[str, ...]
    weak: tuple[str, ...]
    missed: tuple[str, ...]
    violations: tuple[tuple[int, str], ...]
    false_positives: tuple[int, ...]
    allowed: tuple[int, ...]

    @property
    def passed(self) -> bool:
        return not (self.weak or self.missed or self.violations or self.false_positives)


def score(expected: Expected, findings: Sequence[Finding]) -> CaseScore:
    found: set[str] = set()
    weak: set[str] = set()
    violations: list[tuple[int, str]] = []
    false_positives: list[int] = []
    allowed: list[int] = []
    for index, finding in enumerate(findings):
        violated = [matcher.id for matcher in expected.must_not_find if matches(matcher, finding)]
        if violated:
            violations.extend((index, matcher_id) for matcher_id in violated)
            continue
        targets = [
            matcher
            for matcher in expected.must_find
            if matches(matcher, finding, ignore_confidence=True)
        ]
        if targets:
            for matcher in targets:
                (found if _confident_enough(matcher, finding) else weak).add(matcher.id)
        elif any(matches(matcher, finding) for matcher in expected.allowed):
            allowed.append(index)
        else:
            false_positives.append(index)
    ids = [matcher.id for matcher in expected.must_find]
    return CaseScore(
        found=tuple(i for i in ids if i in found),
        weak=tuple(i for i in ids if i in weak and i not in found),
        missed=tuple(i for i in ids if i not in found and i not in weak),
        violations=tuple(violations),
        false_positives=tuple(false_positives),
        allowed=tuple(allowed),
    )


def matches(matcher: Matcher, finding: Finding, *, ignore_confidence: bool = False) -> bool:
    doc = finding.doc
    if matcher.doc and not any(
        location.overlaps(doc.file, doc.line, doc.end_line) for location in matcher.doc
    ):
        return False
    if (matcher.probes or matcher.evidence_docs) and not _evidence_matches(matcher, finding):
        return False
    return ignore_confidence or _confident_enough(matcher, finding)


def _evidence_matches(matcher: Matcher, finding: Finding) -> bool:
    evidence = finding.evidence
    if isinstance(evidence, ProbeQuote):
        return evidence.probe in matcher.probes
    return any(
        location.overlaps(evidence.file, evidence.line, evidence.end_line)
        for location in matcher.evidence_docs
    )


def _confident_enough(matcher: Matcher, finding: Finding) -> bool:
    return matcher.confidence is None or finding.confidence is matcher.confidence
