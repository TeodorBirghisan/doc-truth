import json
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from doc_truth.evidence import ProbeResult
from doc_truth.findings import DocQuote, Finding, ProbeQuote, normalised, words
from doc_truth.prompt import DocText, split_lines


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
    cited = lines[quote.line - 1 : quote.end_line]
    span = _quoted_span(cited, normalised(quote.quote))
    if span is None:
        return f"the quote is not in {quote.location}"
    first, last = span
    return replace(quote, line=quote.line + first, end_line=quote.line + last)


def output_lines_quoted(result: ProbeResult, quote: str) -> list[str] | None:
    needle = normalised(quote)
    for output in (result.stdout, result.stderr):
        lines = split_lines(output)
        span = _quoted_span(lines, needle)
        if span is not None:
            return lines[span[0] : span[1] + 1]
    return None


def _quoted_span(lines: Sequence[str], needle: str) -> tuple[int, int] | None:
    found_words: list[str] = []
    starts: list[int] = []
    indexes: list[int] = []
    offset = 0
    for index, line in enumerate(lines):
        for word in words(line):
            found_words.append(word)
            starts.append(offset)
            indexes.append(index)
            offset += len(word) + 1
    start = " ".join(found_words).find(needle)
    if start < 0:
        return None
    end = start + len(needle) - 1
    return indexes[bisect_right(starts, start) - 1], indexes[bisect_right(starts, end) - 1]


def _find_in_output(quote: ProbeQuote, probes: Mapping[str, ProbeResult]) -> ProbeQuote | str:
    name = json.dumps(quote.probe)
    result = probes.get(quote.probe)
    if result is None:
        return f"no probe is called {name}"
    if result.failed:
        return f"probe {name} failed, so it is no evidence"
    if output_lines_quoted(result, quote.quote) is None:
        return f"the quote is not in the output of probe {name}"
    return quote
