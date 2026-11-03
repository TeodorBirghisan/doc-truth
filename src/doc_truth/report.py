import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from doc_truth.evidence import (
    Evidence,
    ProbeResult,
    blockquote,
    code_span,
    fence,
    utc_timestamp,
)
from doc_truth.findings import Confidence, DocQuote, Finding, Fix, Kind, ProbeQuote, one_line
from doc_truth.known import Earlier, Tracked, earlier_json, identity_json
from doc_truth.model import Answer
from doc_truth.verify import Dropped

REPORT_FORMAT = 2

_KINDS = {
    Kind.CONTRADICTION: "Contradiction",
    Kind.CROSS_DOC_CONTRADICTION: "Cross-doc contradiction",
    Kind.OMISSION: "Omission",
    Kind.STALE_STATUS: "Stale status",
}
_FIXES = {Fix.DOC: "edit the doc", Fix.HOST: "change the host"}


@dataclass(frozen=True, slots=True, kw_only=True)
class Report:
    evidence: Evidence
    docs: tuple[str, ...]
    prompt_version: int
    requested_model: str
    answers: tuple[Answer, ...]
    findings: tuple[Tracked, ...]
    dropped: tuple[Dropped, ...]
    finished_at: datetime
    previous_run: str | None = None
    no_longer_reported: tuple[Earlier, ...] = ()
    not_rechecked: tuple[Earlier, ...] = ()

    @property
    def confirmed(self) -> tuple[Tracked, ...]:
        return self._in_doc_order(Confidence.CONFIRMED)

    @property
    def suspect(self) -> tuple[Tracked, ...]:
        return self._in_doc_order(Confidence.SUSPECT)

    @property
    def acknowledged(self) -> tuple[Tracked, ...]:
        return self._sorted(item for item in self.findings if item.acknowledgement is not None)

    @property
    def failed_probes(self) -> tuple[ProbeResult, ...]:
        return tuple(result for result in self.evidence.results if result.failed)

    def _in_doc_order(self, confidence: Confidence) -> tuple[Tracked, ...]:
        return self._sorted(
            item
            for item in self.findings
            if item.finding.confidence is confidence and item.acknowledgement is None
        )

    def _sorted(self, items: Iterable[Tracked]) -> tuple[Tracked, ...]:
        position = {path: index for index, path in enumerate(self.docs)}
        return tuple(
            sorted(
                items,
                key=lambda item: (
                    position[item.finding.doc.file],
                    item.finding.doc.line,
                    item.finding.doc.end_line,
                ),
            )
        )


def summary(report: Report) -> str:
    return " ".join(_summary_parts(report))


def report_markdown(report: Report) -> str:
    headline, *rest = _summary_parts(report)
    blocks = [
        f"# doc-truth report for {code_span(report.evidence.host)}",
        " ".join([f"**{headline}**", *rest]),
        _checked(report),
    ]
    for heading, findings in (("Confirmed", report.confirmed), ("Suspect", report.suspect)):
        if findings:
            blocks.append(f"## {heading}")
            blocks.extend(_finding_markdown(item) for item in findings)
    if report.acknowledged:
        blocks.append("## Acknowledged")
        blocks.append(
            "These are known, each with a reason on record, so they are left out of the counts "
            "and the exit code. Delete an entry from the known-findings file to bring its "
            "finding back."
        )
        blocks.extend(_finding_markdown(item) for item in report.acknowledged)
    if report.no_longer_reported:
        blocks.append("## No longer reported")
        blocks.append(
            "These were in the last run or are acknowledged, and what they rest on worked this "
            "time, but the model didn't report them. They may be fixed, but a model can also "
            "miss things, so this isn't proof."
        )
        blocks.append(_earlier_markdown(report.no_longer_reported))
    if report.not_rechecked:
        blocks.append("## Not rechecked")
        blocks.append(
            "These were in the last run or are acknowledged, but this run couldn't check them: "
            "a probe failed, a doc or probe has left the config, or the model's quotes didn't "
            "check out."
        )
        blocks.append(_earlier_markdown(report.not_rechecked))
    if report.failed_probes:
        blocks.append("## Failed probes")
        blocks.append(
            "A failed probe is no evidence, so no finding rests on one. Claims that only "
            "these probes could check went unchecked."
        )
        blocks.append(
            "\n".join(
                f"- {code_span(result.probe.name)}: {result.failure}"
                for result in report.failed_probes
            )
        )
    if report.dropped:
        blocks.append("## Dropped findings")
        blocks.append(
            "The model reported these too, but their quotes didn't check out, so they are "
            "left out of the counts and the exit code."
        )
        blocks.extend(_dropped_markdown(item) for item in report.dropped)
    blocks.append("## Docs checked")
    blocks.append("\n".join(f"- {code_span(path)}" for path in report.docs))
    return "\n\n".join(blocks) + "\n"


def _finding_markdown(item: Tracked) -> str:
    finding = item.finding
    extras = [f"Reason: {one_line(item.acknowledgement.reason)}"] if item.acknowledgement else []
    if item.note is not None:
        extras.append(item.note)
    return "\n\n".join(
        [
            f"### {one_line(finding.title)}",
            f"{code_span(item.id)} · {_state(item)} · {_KINDS[finding.kind]} · "
            f"likely fix: {_FIXES[finding.fix]}",
            *extras,
            f"{code_span(finding.doc.location)} says:",
            blockquote(finding.doc.quote),
            *_evidence_markdown(finding.evidence),
            f"Why: {one_line(finding.reason)}",
        ]
    )


def _state(item: Tracked) -> str:
    acknowledgement = item.acknowledgement
    if acknowledgement is not None:
        until = "" if acknowledgement.until is None else f" until {acknowledgement.until}"
        confidence = item.finding.confidence.value.capitalize()
        return f"{confidence}, acknowledged on {acknowledgement.acknowledged}{until}"
    return "New" if item.runs_open == 1 else f"Open for {item.runs_open} runs"


def _earlier_markdown(items: Iterable[Earlier]) -> str:
    return "\n".join(
        f"- {code_span(item.id)} in {code_span(item.identity.doc.file)}: {one_line(item.title)}"
        + _earlier_label(item)
        for item in items
    )


def _earlier_label(item: Earlier) -> str:
    if item.left_config:
        return (
            " (its doc or probe left the config; delete its entry to stop listing it)"
            if item.from_known
            else " (left the config, so it's listed only this once)"
        )
    if item.acknowledged:
        return " (acknowledged)"
    return (
        " (its acknowledgement ran out; delete its entry to stop listing it)"
        if item.from_known
        else ""
    )


def report_json(report: Report) -> str:
    evidence = report.evidence
    data = {
        "format": REPORT_FORMAT,
        "doc_truth_version": evidence.tool_version,
        "prompt_version": report.prompt_version,
        "host": evidence.host,
        "started_at": utc_timestamp(evidence.started_at),
        "finished_at": utc_timestamp(report.finished_at),
        "config": str(evidence.config_path),
        "compared_with": report.previous_run,
        "counts": {
            "confirmed": len(report.confirmed),
            "suspect": len(report.suspect),
            "new": _new_count(report),
            "acknowledged": len(report.acknowledged),
            "no_longer_reported": len(report.no_longer_reported),
            "not_rechecked": len(report.not_rechecked),
            "dropped": len(report.dropped),
            "failed_probes": len(report.failed_probes),
        },
        "model": {
            "requested": report.requested_model,
            "calls": [_answer_json(answer) for answer in report.answers],
        },
        "docs": list(report.docs),
        "failed_probes": [
            {"name": result.probe.name, "failure": result.failure}
            for result in report.failed_probes
        ],
        "findings": [
            _tracked_json(item)
            for item in (*report.confirmed, *report.suspect, *report.acknowledged)
        ],
        "no_longer_reported": [earlier_json(item) for item in report.no_longer_reported],
        "not_rechecked": [earlier_json(item) for item in report.not_rechecked],
        "dropped": [
            {"finding": _finding_json(item.finding), "problems": list(item.problems)}
            for item in report.dropped
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _summary_parts(report: Report) -> list[str]:
    confirmed = len(report.confirmed)
    suspect = len(report.suspect)
    parts = [
        f"{_count(confirmed + suspect, 'finding')}: {confirmed} confirmed, {suspect} suspect."
        if confirmed + suspect
        else "No findings."
    ]
    if report.previous_run is not None and confirmed + suspect:
        parts.append(f"{_new_count(report)} new.")
    if report.acknowledged:
        parts.append(f"{len(report.acknowledged)} acknowledged.")
    if report.no_longer_reported:
        parts.append(f"{len(report.no_longer_reported)} no longer reported.")
    if report.not_rechecked:
        parts.append(f"{len(report.not_rechecked)} not rechecked.")
    if report.failed_probes:
        parts.append(f"{_count(len(report.failed_probes), 'probe')} failed.")
    if report.dropped:
        parts.append(f"{_count(len(report.dropped), 'finding')} dropped.")
    return parts


def _new_count(report: Report) -> int:
    return sum(item.runs_open == 1 for item in (*report.confirmed, *report.suspect))


def _checked(report: Report) -> str:
    evidence = report.evidence
    answers = report.answers
    started = evidence.started_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    models = list(dict.fromkeys(model for answer in answers for model in answer.models))
    models = models or [report.requested_model]
    input_tokens = sum(answer.input_tokens for answer in answers)
    output_tokens = sum(answer.output_tokens for answer in answers)
    cost = sum(answer.cost_usd for answer in answers)
    compared = "" if report.previous_run is None else f"\nCompared with run {report.previous_run}."
    return (
        f"Checked {started} by doc-truth {evidence.tool_version}: "
        f"{_count(len(report.docs), 'doc')}, {_count(len(evidence.results), 'probe')}.\n"
        f"{'Model' if len(models) == 1 else 'Models'}: {', '.join(models)} "
        f"({_count(len(answers), 'call')}, {input_tokens:,} tokens in, {output_tokens:,} out, "
        f"${cost:.2f} as reported by Claude Code)."
        f"{compared}"
    )


def _evidence_markdown(evidence: ProbeQuote | DocQuote) -> list[str]:
    if isinstance(evidence, ProbeQuote):
        return [f"Probe {code_span(evidence.probe)} printed:", fence(evidence.quote, "text")]
    return [f"{code_span(evidence.location)} says:", blockquote(evidence.quote)]


def _dropped_markdown(item: Dropped) -> str:
    finding = item.finding
    evidence = finding.evidence
    source = (
        f"probe {json.dumps(evidence.probe)}"
        if isinstance(evidence, ProbeQuote)
        else json.dumps(evidence.location)
    )
    return "\n\n".join(
        [
            f"### {one_line(finding.title)}",
            "\n".join(f"- {problem}" for problem in item.problems),
            f"The model's doc quote, for {json.dumps(finding.doc.location)}:",
            fence(finding.doc.quote, "text"),
            f"The model's evidence quote, for {source}:",
            fence(evidence.quote, "text"),
        ]
    )


def _tracked_json(item: Tracked) -> dict[str, object]:
    acknowledgement = item.acknowledgement
    return {
        "id": item.id,
        "runs_open": item.runs_open,
        "acknowledged": acknowledgement is not None,
        **(
            {}
            if acknowledgement is None
            else {
                "acknowledgement": {
                    "reason": acknowledgement.reason,
                    "acknowledged": acknowledgement.acknowledged.isoformat(),
                    "until": acknowledgement.until and acknowledgement.until.isoformat(),
                }
            }
        ),
        "note": item.note,
        "identity": identity_json(item.identity),
        **_finding_json(item.finding),
    }


def _finding_json(finding: Finding) -> dict[str, object]:
    return {
        "kind": finding.kind.value,
        "title": finding.title,
        "doc": _quote_json(finding.doc),
        "evidence": _quote_json(finding.evidence),
        "confidence": finding.confidence.value,
        "fix": finding.fix.value,
        "reason": finding.reason,
    }


def _quote_json(quote: DocQuote | ProbeQuote) -> dict[str, object]:
    if isinstance(quote, ProbeQuote):
        return {"probe": quote.probe, "quote": quote.quote}
    return {
        "file": quote.file,
        "line": quote.line,
        "end_line": quote.end_line,
        "quote": quote.quote,
    }


def _answer_json(answer: Answer) -> dict[str, object]:
    return {
        "models": list(answer.models),
        "input_tokens": answer.input_tokens,
        "output_tokens": answer.output_tokens,
        "cost_usd": answer.cost_usd,
        "duration": round(answer.duration, 3),
    }


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"
