import json
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from doc_truth.collect import probe_failure
from doc_truth.config import Config, ConfigError, Doc, Probe, load_config, resolve_docs
from doc_truth.evidence import Evidence, ProbeResult
from doc_truth.findings import Confidence, Finding, FindingsError, parse_findings

CASES_DIR = Path(__file__).resolve().parent / "cases"
HOST = "homeserver"
USER = "ops"
TIMEZONE = "CEST"
UTC_OFFSET = "+02:00"
COLLECTED_AT = datetime(2026, 10, 3, 8, 20, tzinfo=UTC)
TOOL_VERSION = "0.1.0"

PROBE_PREFIX = "probe:"
_LOCATION = re.compile(r"(?P<file>[^:]+):(?P<start>[1-9][0-9]*)(?:-(?P<end>[1-9][0-9]*))?")
_ID = re.compile(r"[a-z0-9][a-z0-9-]*")
_RESULT_KEYS = ("probe", "exit-code", "timed-out", "stdout", "stderr")
_MATCHER_KEYS = ("id", "doc", "evidence", "confidence", "note")
_SECTIONS = ("must-find", "must-not-find", "allowed")


class CaseError(Exception):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Location:
    file: str
    start: int
    end: int

    def overlaps(self, file: str, start: int, end: int) -> bool:
        return file == self.file and start <= self.end and self.start <= end


@dataclass(frozen=True, slots=True, kw_only=True)
class Matcher:
    id: str
    doc: tuple[Location, ...]
    probes: tuple[str, ...]
    evidence_docs: tuple[Location, ...]
    confidence: Confidence | None
    note: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Expected:
    must_find: tuple[Matcher, ...]
    must_not_find: tuple[Matcher, ...]
    allowed: tuple[Matcher, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class Case:
    name: str
    directory: Path
    config: Config
    docs: tuple[Doc, ...]
    evidence: Evidence
    expected: Expected
    reference: tuple[Finding, ...]


def case_directories() -> list[Path]:
    return sorted(path for path in CASES_DIR.iterdir() if path.is_dir())


def load_case(directory: Path) -> Case:
    try:
        config = load_config(directory / "doc-truth.toml")
        docs = resolve_docs(config)
        evidence = _evidence(directory, config)
        line_counts = {doc.display_path: _line_count(doc.path) for doc in docs}
        probe_names = {probe.name for probe in config.probes}
        expected = _expected(_read_toml(directory / "expected.toml"), line_counts, probe_names)
        answer = json.loads((directory / "reference.json").read_text(encoding="utf-8"))
        reference = parse_findings(answer)
    except (CaseError, ConfigError, FindingsError, OSError, ValueError) as error:
        raise CaseError(f"case {directory.name}: {error}") from error
    return Case(
        name=directory.name,
        directory=directory,
        config=config,
        docs=docs,
        evidence=evidence,
        expected=expected,
        reference=reference,
    )


def _evidence(directory: Path, config: Config) -> Evidence:
    data = _read_toml(directory / "evidence.toml")
    _only_keys(data, ("results",), "evidence.toml")
    entries = data.get("results")
    if not isinstance(entries, list):
        raise CaseError("evidence.toml: needs [[results]] tables")
    results: dict[str, ProbeResult] = {}
    probes = {probe.name: probe for probe in config.probes}
    for number, entry in enumerate(entries, start=1):
        where = f"evidence.toml [[results]] #{number}"
        if not isinstance(entry, dict):
            raise CaseError(f"{where}: must be a table")
        _only_keys(entry, _RESULT_KEYS, where)
        name = entry.get("probe")
        if not isinstance(name, str) or name not in probes:
            raise CaseError(f"{where}: probe must name a probe from doc-truth.toml")
        if name in results:
            raise CaseError(f"{where}: probe {name} already has a result")
        results[name] = _result(entry, probes[name], where)
    missing = [name for name in probes if name not in results]
    if missing:
        raise CaseError(f"evidence.toml: no result for {', '.join(missing)}")
    return Evidence(
        tool_version=TOOL_VERSION,
        host=HOST,
        user=USER,
        timezone=TIMEZONE,
        utc_offset=UTC_OFFSET,
        started_at=COLLECTED_AT,
        finished_at=COLLECTED_AT,
        config_path=config.base_dir / config.path.name,
        results=tuple(results[probe.name] for probe in config.probes),
    )


def _result(entry: Mapping[str, object], probe: Probe, where: str) -> ProbeResult:
    timed_out = entry.get("timed-out", False)
    exit_code = entry.get("exit-code")
    stdout = entry.get("stdout", "")
    stderr = entry.get("stderr", "")
    if not isinstance(timed_out, bool):
        raise CaseError(f"{where}: timed-out must be a boolean")
    if timed_out == (exit_code is not None):
        raise CaseError(f"{where}: give either exit-code or timed-out = true")
    if exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int)):
        raise CaseError(f"{where}: exit-code must be an integer")
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        raise CaseError(f"{where}: stdout and stderr must be strings")
    signal_name = "SIGTERM" if timed_out else None
    return ProbeResult(
        probe=probe,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        signal=signal_name,
        duration=0.0,
        timed_out=timed_out,
        stdout_truncated=False,
        stderr_truncated=False,
        failure=probe_failure(
            probe,
            exit_code=exit_code,
            signal_name=signal_name,
            timed_out=timed_out,
            stdout_truncated=False,
        ),
    )


def _expected(
    data: Mapping[str, object], line_counts: Mapping[str, int], probe_names: set[str]
) -> Expected:
    _only_keys(data, _SECTIONS, "expected.toml")
    ids: set[str] = set()
    sections: dict[str, tuple[Matcher, ...]] = {}
    for section in _SECTIONS:
        entries = data.get(section, [])
        if not isinstance(entries, list):
            raise CaseError(f"expected.toml: {section} must be [[{section}]] tables")
        matchers = []
        for number, entry in enumerate(entries, start=1):
            where = f"expected.toml [[{section}]] #{number}"
            matcher = _matcher(entry, where, line_counts, probe_names)
            if matcher.id in ids:
                raise CaseError(f"{where}: id {matcher.id} is already used")
            ids.add(matcher.id)
            if section == "must-find" and not matcher.doc:
                raise CaseError(f"{where}: must-find needs doc locations")
            if section == "must-find" and matcher.confidence is Confidence.SUSPECT:
                raise CaseError(f'{where}: must-find can only require confidence = "confirmed"')
            if section != "must-find" and not (
                matcher.doc or matcher.probes or matcher.evidence_docs
            ):
                raise CaseError(f"{where}: needs doc or evidence, or it would match every finding")
            matchers.append(matcher)
        sections[section] = tuple(matchers)
    return Expected(
        must_find=sections["must-find"],
        must_not_find=sections["must-not-find"],
        allowed=sections["allowed"],
    )


def _matcher(
    entry: object, where: str, line_counts: Mapping[str, int], probe_names: set[str]
) -> Matcher:
    if not isinstance(entry, dict):
        raise CaseError(f"{where}: must be a table")
    _only_keys(entry, _MATCHER_KEYS, where)
    matcher_id = entry.get("id")
    if not isinstance(matcher_id, str) or not _ID.fullmatch(matcher_id):
        raise CaseError(f"{where}: id must be a lowercase slug")
    doc = tuple(_location(text, where, line_counts) for text in _strings(entry, "doc", where))
    probes: list[str] = []
    evidence_docs: list[Location] = []
    for reference in _strings(entry, "evidence", where):
        if reference.startswith(PROBE_PREFIX):
            name = reference.removeprefix(PROBE_PREFIX)
            if name not in probe_names:
                raise CaseError(f"{where}: no probe named {name}")
            probes.append(name)
        else:
            evidence_docs.append(_location(reference, where, line_counts))
    confidence = entry.get("confidence")
    if confidence is not None and confidence not in [level.value for level in Confidence]:
        raise CaseError(f'{where}: confidence must be "confirmed" or "suspect"')
    note = entry.get("note")
    if note is not None and not isinstance(note, str):
        raise CaseError(f"{where}: note must be a string")
    return Matcher(
        id=matcher_id,
        doc=doc,
        probes=tuple(probes),
        evidence_docs=tuple(evidence_docs),
        confidence=None if confidence is None else Confidence(confidence),
        note=note,
    )


def _location(text: str, where: str, line_counts: Mapping[str, int]) -> Location:
    match = _LOCATION.fullmatch(text)
    if match is None:
        raise CaseError(f"{where}: {text!r} is not FILE:LINE or FILE:START-END")
    file = match["file"]
    start = int(match["start"])
    end = int(match["end"] or start)
    if file not in line_counts:
        raise CaseError(f"{where}: {file} is not one of the case's docs")
    if not start <= end <= line_counts[file]:
        raise CaseError(f"{where}: {text} is outside {file}'s {line_counts[file]} lines")
    return Location(file=file, start=start, end=end)


def _strings(entry: Mapping[str, object], key: str, where: str) -> list[str]:
    value = entry.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CaseError(f"{where}: {key} must be an array of strings")
    return [item for item in value if isinstance(item, str)]


def _only_keys(table: Mapping[str, object], allowed: tuple[str, ...], where: str) -> None:
    unknown = [key for key in table if key not in allowed]
    if unknown:
        raise CaseError(f"{where}: unknown keys {', '.join(unknown)}")


def _read_toml(path: Path) -> dict[str, object]:
    with path.open("rb") as file:
        return tomllib.load(file)


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())
