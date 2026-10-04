import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

_FENCED_BLOCK = re.compile(r"^```(?:json)?[ \t]*\n(.*?)\n```[ \t]*$", re.DOTALL | re.MULTILINE)


class Kind(StrEnum):
    CONTRADICTION = "contradiction"
    CROSS_DOC_CONTRADICTION = "cross-doc-contradiction"
    OMISSION = "omission"
    STALE_STATUS = "stale-status"


class Confidence(StrEnum):
    CONFIRMED = "confirmed"
    SUSPECT = "suspect"


class Fix(StrEnum):
    DOC = "doc"
    HOST = "host"


@dataclass(frozen=True, slots=True, kw_only=True)
class DocQuote:
    file: str
    line: int
    end_line: int
    quote: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ProbeQuote:
    probe: str
    quote: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Finding:
    kind: Kind
    title: str
    doc: DocQuote
    evidence: ProbeQuote | DocQuote
    confidence: Confidence
    fix: Fix
    reason: str


class FindingsError(Exception):
    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        if len(self.problems) == 1:
            message = f"invalid findings: {self.problems[0]}"
        else:
            listed = "\n".join(f"  - {problem}" for problem in self.problems)
            message = f"invalid findings: {len(self.problems)} problems\n{listed}"
        super().__init__(message)


def parse_answer(text: str) -> tuple[Finding, ...]:
    blocks = _FENCED_BLOCK.findall(text)
    body = blocks[0] if len(blocks) == 1 else text
    try:
        data = json.loads(body)
    except ValueError as error:
        raise FindingsError([f"the answer is not valid JSON: {error}"]) from None
    return parse_findings(data)


def parse_findings(data: object) -> tuple[Finding, ...]:
    if not isinstance(data, dict):
        raise FindingsError([f"the answer must be a JSON object, found {_json_type(data)}"])
    if "findings" not in data:
        raise FindingsError(["missing findings"])
    entries = data["findings"]
    if not isinstance(entries, list):
        raise FindingsError([f"findings must be an array, found {_json_type(entries)}"])
    problems: list[str] = []
    findings = [
        _finding(entry, f"findings[{index}]", problems) for index, entry in enumerate(entries)
    ]
    if problems:
        raise FindingsError(problems)
    return tuple(finding for finding in findings if finding is not None)


def _finding(entry: object, where: str, problems: list[str]) -> Finding | None:
    if not isinstance(entry, dict):
        problems.append(f"{where}: must be an object, found {_json_type(entry)}")
        return None
    kind = _choice(entry, "kind", Kind, where, problems)
    title = _text(entry, "title", where, problems)
    doc = _doc_quote(entry, "doc", where, problems)
    evidence = _evidence(entry, where, problems)
    confidence = _choice(entry, "confidence", Confidence, where, problems)
    fix = _choice(entry, "fix", Fix, where, problems)
    reason = _text(entry, "reason", where, problems)
    if (
        kind is None
        or title is None
        or doc is None
        or evidence is None
        or confidence is None
        or fix is None
        or reason is None
    ):
        return None
    return Finding(
        kind=kind,
        title=title,
        doc=doc,
        evidence=evidence,
        confidence=confidence,
        fix=fix,
        reason=reason,
    )


def _evidence(
    table: Mapping[str, object], where: str, problems: list[str]
) -> ProbeQuote | DocQuote | None:
    value = _object(table, "evidence", where, problems)
    if value is None:
        return None
    where = f"{where}.evidence"
    if ("probe" in value) == ("file" in value):
        problems.append(f"{where}: must name either a probe or a file")
        return None
    if "file" in value:
        return _quoted_lines(value, where, problems)
    probe = _text(value, "probe", where, problems)
    quote = _text(value, "quote", where, problems)
    if probe is None or quote is None:
        return None
    return ProbeQuote(probe=probe, quote=quote)


def _doc_quote(
    table: Mapping[str, object], key: str, where: str, problems: list[str]
) -> DocQuote | None:
    value = _object(table, key, where, problems)
    return None if value is None else _quoted_lines(value, f"{where}.{key}", problems)


def _quoted_lines(table: Mapping[str, object], where: str, problems: list[str]) -> DocQuote | None:
    file = _text(table, "file", where, problems)
    line = _line_number(table, "line", where, problems)
    end_line = _line_number(table, "end_line", where, problems) if "end_line" in table else line
    quote = _text(table, "quote", where, problems)
    if file is None or line is None or end_line is None or quote is None:
        return None
    if end_line < line:
        problems.append(f"{where}.end_line: must not be before line {line}, found {end_line}")
        return None
    return DocQuote(file=file, line=line, end_line=end_line, quote=quote)


def _object(
    table: Mapping[str, object], key: str, where: str, problems: list[str]
) -> dict[str, object] | None:
    if key not in table:
        problems.append(f"{where}: missing {key}")
        return None
    value = table[key]
    if not isinstance(value, dict):
        problems.append(f"{where}.{key}: must be an object, found {_json_type(value)}")
        return None
    return value


def _text(table: Mapping[str, object], key: str, where: str, problems: list[str]) -> str | None:
    if key not in table:
        problems.append(f"{where}: missing {key}")
        return None
    value = table[key]
    if not isinstance(value, str):
        problems.append(f"{where}.{key}: must be a string, found {_json_type(value)}")
        return None
    if not value.strip():
        problems.append(f"{where}.{key}: must not be empty")
        return None
    return value


def _line_number(
    table: Mapping[str, object], key: str, where: str, problems: list[str]
) -> int | None:
    if key not in table:
        problems.append(f"{where}: missing {key}")
        return None
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        problems.append(f"{where}.{key}: must be a line number from 1, found {json.dumps(value)}")
        return None
    return value


def _choice[E: StrEnum](
    table: Mapping[str, object], key: str, choices: type[E], where: str, problems: list[str]
) -> E | None:
    if key not in table:
        problems.append(f"{where}: missing {key}")
        return None
    value = table[key]
    values = [choice.value for choice in choices]
    if isinstance(value, str) and value in values:
        return choices(value)
    allowed = ", ".join(json.dumps(choice) for choice in values)
    problems.append(f"{where}.{key}: must be one of {allowed}, found {json.dumps(value)}")
    return None


def _json_type(value: object) -> str:
    match value:
        case None:
            return "null"
        case bool():
            return "a boolean"
        case int() | float():
            return "a number"
        case str():
            return "a string"
        case list():
            return "an array"
        case dict():
            return "an object"
    return type(value).__name__
