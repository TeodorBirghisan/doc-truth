import hashlib
import json
import operator
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from doc_truth.config import Acknowledgement
from doc_truth.evidence import ProbeResult
from doc_truth.findings import (
    CitedLines,
    Confidence,
    DocQuote,
    Finding,
    Identity,
    Kind,
    ProbeOutput,
    ProbeQuote,
    normalised,
    one_line,
)
from doc_truth.prompt import DocText, split_lines
from doc_truth.verify import Dropped, output_lines_quoted

_KNOWN_HEADER = (
    "# Findings acknowledged with `doc-truth ack`. Commit this file with your docs.\n"
    "# Delete a [[known]] table to bring its finding back.\n"
)


class AckError(Exception):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Earlier:
    id: str
    title: str
    confidence: Confidence
    identity: Identity
    runs_open: int
    acknowledged: bool = False
    from_known: bool = False
    left_config: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class PreviousReport:
    run: str
    findings: tuple[Earlier, ...]
    no_longer_reported: tuple[Earlier, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Tracked:
    id: str
    finding: Finding
    identity: Identity
    runs_open: int = 1
    acknowledgement: Acknowledgement | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Tracking:
    findings: tuple[Tracked, ...]
    no_longer_reported: tuple[Earlier, ...]
    not_rechecked: tuple[Earlier, ...]


def identify(finding: Finding, docs: Sequence[DocText], results: Sequence[ProbeResult]) -> Identity:
    lines = {text.doc.display_path: text.lines for text in docs}
    evidence = finding.evidence
    return Identity(
        kind=finding.kind,
        doc=_cited(finding.doc, lines),
        evidence=(
            _printed(evidence, results)
            if isinstance(evidence, ProbeQuote)
            else _cited(evidence, lines)
        ),
    )


def same_finding(a: Identity, b: Identity) -> bool:
    if isinstance(a.evidence, ProbeOutput) and isinstance(b.evidence, ProbeOutput):
        if a.evidence.probe != b.evidence.probe or not _overlap(a.doc, b.doc):
            return False
        # Omissions cite a heading they share, so only the evidence tells them apart.
        return Kind.OMISSION not in (a.kind, b.kind) or bool(a.evidence.lines & b.evidence.lines)
    if isinstance(a.evidence, CitedLines) and isinstance(b.evidence, CitedLines):
        return {a.doc.file, a.evidence.file} == {b.doc.file, b.evidence.file} and any(
            _overlap(x, y) for x in (a.doc, a.evidence) for y in (b.doc, b.evidence)
        )
    return False


def covers(acknowledged: Identity, found: Identity) -> bool:
    a, b = acknowledged, found
    if isinstance(a.evidence, ProbeOutput) and isinstance(b.evidence, ProbeOutput):
        return (
            a.evidence.probe == b.evidence.probe
            and _overlap(a.doc, b.doc)
            and bool(a.evidence.lines & b.evidence.lines)
        )
    if isinstance(a.evidence, CitedLines) and isinstance(b.evidence, CitedLines):
        return (_overlap(a.doc, b.doc) and _overlap(a.evidence, b.evidence)) or (
            _overlap(a.doc, b.evidence) and _overlap(a.evidence, b.doc)
        )
    return False


def track(
    findings: Sequence[Finding],
    *,
    dropped: Sequence[Dropped],
    docs: Sequence[DocText],
    results: Sequence[ProbeResult],
    known: Sequence[Acknowledgement],
    previous: PreviousReport | None,
    today: date,
) -> Tracking:
    earlier = () if previous is None else previous.findings
    run = _Run(docs, results, dropped)
    identities = [identify(finding, docs, results) for finding in findings]
    pairs, unpaired = _paired(identities, earlier)
    states = [
        _acknowledgement_state(finding, identity, known, run, today)
        for finding, identity in zip(findings, identities, strict=True)
    ]
    # Findings under one acknowledgement share its ID on purpose; an earlier ID must not join them.
    taken = {acknowledgement.id for acknowledgement, _ in states if acknowledgement is not None}
    tracked: list[Tracked] = []
    for position, (finding, identity, (acknowledgement, note)) in enumerate(
        zip(findings, identities, states, strict=True)
    ):
        before = pairs.get(position)
        if acknowledgement is not None:
            id_ = acknowledgement.id
        elif before is not None and before.id not in taken:
            id_ = before.id
        else:
            id_ = finding_id(identity)
        taken.add(id_)
        tracked.append(
            Tracked(
                id=id_,
                finding=finding,
                identity=identity,
                runs_open=1 if before is None else before.runs_open + 1,
                acknowledgement=acknowledgement,
                note=note,
            )
        )
    gone = _gone(identities, unpaired, known, today)
    return Tracking(
        findings=tuple(tracked),
        no_longer_reported=tuple(item for item in gone if run.includes(item.identity)),
        not_rechecked=tuple(
            replace(item, left_config=run.left_config(item.identity))
            for item in gone
            if not run.includes(item.identity)
        ),
    )


def already_acknowledged(finding: Earlier, known: Iterable[Acknowledgement], today: date) -> bool:
    return any(
        _is_live(entry, today)
        and _reaches(entry, finding.confidence)
        and (
            entry.identity == finding.identity or (finding.acknowledged and entry.id == finding.id)
        )
        for entry in known
    )


def finding_id(identity: Identity) -> str:
    text = json.dumps(identity_json(identity), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def identity_json(identity: Identity) -> dict[str, object]:
    return {
        "kind": identity.kind.value,
        "doc": _cited_json(identity.doc),
        "evidence": (
            {"probe": identity.evidence.probe, "lines": sorted(identity.evidence.lines)}
            if isinstance(identity.evidence, ProbeOutput)
            else _cited_json(identity.evidence)
        ),
    }


def earlier_json(item: Earlier) -> dict[str, object]:
    return {
        "id": item.id,
        "title": item.title,
        "confidence": item.confidence.value,
        "runs_open": item.runs_open,
        "acknowledged": item.acknowledged,
        "left_config": item.left_config,
        "identity": identity_json(item.identity),
    }


def earlier_from_json(entry: Mapping[str, object]) -> Earlier:
    id_ = entry["id"]
    title = entry["title"]
    runs_open = entry["runs_open"]
    if not isinstance(id_, str) or not isinstance(title, str) or not isinstance(runs_open, int):
        raise ValueError("a finding has the wrong types")
    return Earlier(
        id=id_,
        title=title,
        confidence=Confidence(str(entry["confidence"])),
        runs_open=runs_open,
        acknowledged=entry.get("acknowledged") is True,
        identity=_identity_from_json(entry["identity"]),
    )


def acknowledge(
    finding: Earlier, *, reason: str, today: date, until: date | None
) -> Acknowledgement:
    return Acknowledgement(
        id=finding.id,
        title=finding.title,
        confidence=finding.confidence,
        reason=reason,
        acknowledged=today,
        until=until,
        identity=finding.identity,
    )


def append_known(path: Path, acknowledgement: Acknowledgement) -> None:
    entry = known_toml(acknowledgement)
    try:
        entry.encode("utf-8")
    except UnicodeError:
        raise AckError("the reason isn't valid UTF-8 text") from None
    try:
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        with path.open("a", encoding="utf-8") as file:
            if existing is None:
                file.write(_KNOWN_HEADER)
            elif existing and not existing.endswith("\n"):
                file.write("\n")
            file.write("\n" + entry)
    except OSError as error:
        raise AckError(f"cannot write {path}: {error.strerror or error}") from None


def known_toml(acknowledgement: Acknowledgement) -> str:
    identity = acknowledgement.identity
    fields = [
        f"id = {_toml_string(acknowledgement.id)}",
        f"title = {_toml_string(acknowledgement.title)}",
        f"kind = {_toml_string(identity.kind.value)}",
        f"confidence = {_toml_string(acknowledgement.confidence.value)}",
        f"reason = {_toml_string(acknowledgement.reason)}",
        f"acknowledged = {acknowledgement.acknowledged.isoformat()}",
    ]
    if acknowledgement.until is not None:
        fields.append(f"until = {acknowledgement.until.isoformat()}")
    fields += [
        f"doc = {_toml_string(identity.doc.file)}",
        f"lines = {_toml_lines(identity.doc.lines)}",
    ]
    if isinstance(identity.evidence, ProbeOutput):
        fields += [
            f"probe = {_toml_string(identity.evidence.probe)}",
            f"evidence-lines = {_toml_lines(identity.evidence.lines)}",
        ]
    else:
        fields += [
            f"other-doc = {_toml_string(identity.evidence.file)}",
            f"other-lines = {_toml_lines(identity.evidence.lines)}",
        ]
    return "[[known]]\n" + "\n".join(fields) + "\n"


class _Run:
    def __init__(
        self,
        docs: Sequence[DocText],
        results: Sequence[ProbeResult],
        dropped: Sequence[Dropped],
    ) -> None:
        self._doc_lines = {text.doc.display_path: _texts(text.lines) for text in docs}
        self._printed = {
            result.probe.name: _texts(split_lines(result.stdout))
            | _texts(split_lines(result.stderr))
            for result in results
        }
        self._failed = {result.probe.name for result in results if result.failed}
        self._dropped = [item.finding for item in dropped]

    def left_config(self, identity: Identity) -> bool:
        evidence = identity.evidence
        return identity.doc.file not in self._doc_lines or (
            evidence.probe not in self._printed
            if isinstance(evidence, ProbeOutput)
            else evidence.file not in self._doc_lines
        )

    def includes(self, identity: Identity) -> bool:
        evidence = identity.evidence
        return (
            not self.left_config(identity)
            and not (isinstance(evidence, ProbeOutput) and evidence.probe in self._failed)
            and not any(_cites_same_sources(finding, identity) for finding in self._dropped)
        )

    def still_there(self, identity: Identity) -> bool:
        evidence = identity.evidence
        cited = [identity.doc, evidence] if isinstance(evidence, CitedLines) else [identity.doc]
        if not all(item.lines <= self._doc_lines.get(item.file, frozenset()) for item in cited):
            return False
        return not isinstance(evidence, ProbeOutput) or evidence.lines <= self._printed.get(
            evidence.probe, frozenset()
        )


def _cites_same_sources(finding: Finding, identity: Identity) -> bool:
    evidence = finding.evidence
    if isinstance(evidence, ProbeQuote) and isinstance(identity.evidence, ProbeOutput):
        return finding.doc.file == identity.doc.file and evidence.probe == identity.evidence.probe
    if isinstance(evidence, DocQuote) and isinstance(identity.evidence, CitedLines):
        return {finding.doc.file, evidence.file} == {identity.doc.file, identity.evidence.file}
    return False


def _paired(
    current: Sequence[Identity], earlier: Sequence[Earlier]
) -> tuple[dict[int, Earlier], list[Earlier]]:
    pairs: dict[int, Earlier] = {}
    unpaired = list(earlier)
    # Strongest match first, so a finding keeps its own past when the model reorders its answer.
    for matches in (operator.eq, covers, same_finding):
        for position, identity in enumerate(current):
            if position not in pairs:
                match = next((item for item in unpaired if matches(item.identity, identity)), None)
                if match is not None:
                    pairs[position] = match
                    unpaired.remove(match)
    return pairs, unpaired


def _acknowledgement_state(
    finding: Finding,
    identity: Identity,
    known: Sequence[Acknowledgement],
    run: _Run,
    today: date,
) -> tuple[Acknowledgement | None, str | None]:
    covering = [
        ack for ack in known if covers(ack.identity, identity) and run.still_there(ack.identity)
    ]
    live = [ack for ack in covering if _is_live(ack, today)]
    holding = next((ack for ack in live if _reaches(ack, finding.confidence)), None)
    if holding is not None:
        return holding, None
    if live:
        ack = live[-1]
        return None, (
            f"An acknowledgement from {ack.acknowledged} was given when this was only suspect. "
            f"It's confirmed now, so it counts again. Its reason was: {one_line(ack.reason)}"
        )
    if covering:
        ack = covering[-1]
        return None, (
            f"An acknowledgement of this ran out on {ack.until}, so it counts again. "
            f"Its reason was: {one_line(ack.reason)}"
        )
    for ack in known:
        if same_finding(ack.identity, identity):
            why = (
                "for other evidence, so it doesn't cover this"
                if run.still_there(ack.identity)
                else "what it rests on has changed, so this counts again"
            )
            return None, (
                f"An acknowledgement from {ack.acknowledged} is on record for this line, but "
                f"{why}. Its reason was: {one_line(ack.reason)}"
            )
    return None, None


def _reaches(ack: Acknowledgement, confidence: Confidence) -> bool:
    return ack.confidence is Confidence.CONFIRMED or confidence is Confidence.SUSPECT


def _gone(
    current: Sequence[Identity],
    unpaired: Sequence[Earlier],
    known: Sequence[Acknowledgement],
    today: date,
) -> list[Earlier]:
    from_known: list[Earlier] = []
    for ack in sorted(known, key=lambda ack: not _is_live(ack, today)):
        if not any(same_finding(ack.identity, identity) for identity in current) and not any(
            covers(listed.identity, ack.identity) for listed in from_known
        ):
            from_known.append(
                Earlier(
                    id=ack.id,
                    title=ack.title,
                    confidence=ack.confidence,
                    identity=ack.identity,
                    runs_open=max(
                        (
                            item.runs_open
                            for item in unpaired
                            if covers(ack.identity, item.identity)
                        ),
                        default=0,
                    ),
                    acknowledged=_is_live(ack, today),
                    from_known=True,
                )
            )
    return [
        *from_known,
        *(
            replace(item, acknowledged=False)
            for item in unpaired
            if not any(covers(listed.identity, item.identity) for listed in from_known)
        ),
    ]


def _is_live(ack: Acknowledgement, today: date) -> bool:
    return ack.until is None or ack.until >= today


def _cited(quote: DocQuote, lines: Mapping[str, tuple[str, ...]]) -> CitedLines:
    cited = lines[quote.file][quote.line - 1 : quote.end_line]
    return CitedLines(file=quote.file, lines=_worded(cited))


def _printed(quote: ProbeQuote, results: Sequence[ProbeResult]) -> ProbeOutput:
    for result in results:
        if result.probe.name == quote.probe:
            lines = output_lines_quoted(result, quote.quote)
            if lines is not None:
                return ProbeOutput(probe=quote.probe, lines=_worded(lines))
    raise ValueError(f"the quote is not in the output of probe {quote.probe}")


def _worded(lines: Iterable[str]) -> frozenset[str]:
    texts = [normalised(line) for line in lines]
    # A shared code fence or table rule says nothing about whether two findings are the same.
    worded = [text for text in texts if any(character.isalnum() for character in text)]
    return frozenset(worded or filter(None, texts))


def _texts(lines: Iterable[str]) -> frozenset[str]:
    return frozenset(normalised(line) for line in lines)


def _overlap(a: CitedLines, b: CitedLines) -> bool:
    return a.file == b.file and bool(a.lines & b.lines)


def _cited_json(cited: CitedLines) -> dict[str, object]:
    return {"file": cited.file, "lines": sorted(cited.lines)}


def _identity_from_json(value: object) -> Identity:
    if not isinstance(value, dict):
        raise ValueError("an identity must be an object")
    evidence = value["evidence"]
    if not isinstance(evidence, dict):
        raise ValueError("an identity's evidence must be an object")
    return Identity(
        kind=Kind(value["kind"]),
        doc=_cited_from_json(value["doc"]),
        evidence=(
            ProbeOutput(probe=str(evidence["probe"]), lines=_lines_from_json(evidence["lines"]))
            if "probe" in evidence
            else _cited_from_json(evidence)
        ),
    )


def _cited_from_json(value: object) -> CitedLines:
    if not isinstance(value, dict):
        raise ValueError("cited lines must be an object")
    return CitedLines(file=str(value["file"]), lines=_lines_from_json(value["lines"]))


def _lines_from_json(value: object) -> frozenset[str]:
    if not isinstance(value, list):
        raise ValueError("lines must be a list")
    return frozenset(str(line) for line in value)


def _toml_lines(lines: frozenset[str]) -> str:
    return "[" + ", ".join(_toml_string(line) for line in sorted(lines)) + "]"


def _toml_string(text: str) -> str:
    return json.dumps(text, ensure_ascii=False).replace("\x7f", "\\u007F")
