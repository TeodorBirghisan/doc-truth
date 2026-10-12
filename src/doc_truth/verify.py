import json
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from doc_truth.evidence import ProbeResult
from doc_truth.findings import DocQuote, Finding, ProbeQuote
from doc_truth.prompt import DocText

_STRAIGHT_QUOTES = str.maketrans("\u2018\u2019\u201c\u201d", "''\"\"")


@dataclass(frozen=True, slots=True, kw_only=True)
class Dropped:
    finding: Finding
    problems: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class Verification:
    findings: tuple[Finding, ...]
    dropped: tuple[Dropped, ...]


def verify(
    findings: Sequence[Finding], docs: Sequence[DocText], results: Sequence[ProbeResult]
) -> Verification:
    lines = {text.doc.display_path: text.lines for text in docs}
    probes = {result.probe.name: result for result in results}
    kept: list[Finding] = []
    dropped: list[Dropped] = []
    for finding in findings:
        doc = _locate(finding.doc, lines)
        evidence = (
            _find_in_output(finding.evidence, probes)
            if isinstance(finding.evidence, ProbeQuote)
            else _locate(finding.evidence, lines)
        )
        if isinstance(doc, str) or isinstance(evidence, str):
            problems = [
                f"{side}: {problem}"
                for side, problem in (("doc", doc), ("evidence", evidence))
                if isinstance(problem, str)
            ]
            dropped.append(Dropped(finding=finding, problems=tuple(problems)))
        else:
            kept.append(replace(finding, doc=doc, evidence=evidence))
    return Verification(findings=tuple(kept), dropped=tuple(dropped))


def _locate(quote: DocQuote, docs: Mapping[str, tuple[str, ...]]) -> DocQuote | str:
    lines = docs.get(quote.file)
    if lines is None:
        return f"{json.dumps(quote.file)} is not one of the checked docs"
    if not lines:
        return f"{quote.file} is empty"
    if quote.line > len(lines):
        return f"{quote.file} has no line {quote.line}; it ends at line {len(lines)}"
    words: list[str] = []
    starts: list[int] = []
    numbers: list[int] = []
    offset = 0
    for number in range(quote.line, min(quote.end_line, len(lines)) + 1):
        for word in _words(lines[number - 1]):
            words.append(word)
            starts.append(offset)
            numbers.append(number)
            offset += len(word) + 1
    needle = " ".join(_words(quote.quote))
    start = " ".join(words).find(needle)
    if start < 0:
        return f"the quote is not in {quote.location}"
    end = start + len(needle) - 1
    return replace(
        quote,
        line=numbers[bisect_right(starts, start) - 1],
        end_line=numbers[bisect_right(starts, end) - 1],
    )


def _find_in_output(quote: ProbeQuote, probes: Mapping[str, ProbeResult]) -> ProbeQuote | str:
    name = json.dumps(quote.probe)
    result = probes.get(quote.probe)
    if result is None:
        return f"no probe is called {name}"
    if result.failed:
        return f"probe {name} failed, so it is no evidence"
    needle = " ".join(_words(quote.quote))
    if not any(needle in " ".join(_words(output)) for output in (result.stdout, result.stderr)):
        return f"the quote is not in the output of probe {name}"
    return quote


def _words(text: str) -> list[str]:
    return text.translate(_STRAIGHT_QUOTES).split()
