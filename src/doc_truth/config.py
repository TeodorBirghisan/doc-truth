import difflib
import glob
import json
import os
import re
import textwrap
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

DEFAULT_CONFIG_NAME = "doc-truth.toml"
DEFAULT_TIMEOUT = 30.0
MAX_TIMEOUT = 3600.0
DEFAULT_SUCCESS_EXIT_CODES = frozenset({0})

TOP_LEVEL_KEYS = ("docs", "probes")
DOC_KEYS = ("path", "notes")
PROBE_KEYS = ("name", "command", "timeout", "success-exit-codes", "notes")

_PROBE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_GLOB_CHARACTERS = frozenset("*?[")


class ConfigError(Exception):
    def __init__(
        self,
        path: Path,
        problems: Sequence[str],
        *,
        position: tuple[int, int] | None = None,
    ) -> None:
        self.path = path
        self.problems = tuple(problems)
        self.position = position
        super().__init__(self._message())

    def _message(self) -> str:
        location = str(self.path)
        if self.position is not None:
            line, column = self.position
            location += f":{line}:{column}"
        if len(self.problems) == 1:
            return f"{location}: {self.problems[0]}"
        listed = "\n".join(f"  - {problem}" for problem in self.problems)
        return f"{location}: {len(self.problems)} problems\n{listed}"


@dataclass(frozen=True, slots=True, kw_only=True)
class DocSource:
    path: str
    notes: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Probe:
    name: str
    command: str
    timeout: float
    success_exit_codes: frozenset[int]
    notes: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Config:
    path: Path
    base_dir: Path
    docs: tuple[DocSource, ...]
    probes: tuple[Probe, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class Doc:
    path: Path
    display_path: str
    notes: tuple[str, ...]


def load_config(path: Path) -> Config:
    data = _read_toml(path)
    problems: list[str] = []
    _reject_unknown_keys(data, TOP_LEVEL_KEYS, None, problems)
    docs = _parse_docs(data.get("docs"), problems)
    probes = _parse_probes(data.get("probes"), problems)
    if problems:
        raise ConfigError(path, problems)
    return Config(
        path=path,
        base_dir=Path(os.path.abspath(path)).parent,
        docs=docs,
        probes=probes,
    )


def resolve_docs(config: Config) -> tuple[Doc, ...]:
    problems: list[str] = []
    files: dict[str, tuple[Path, list[str]]] = {}
    for number, source in enumerate(config.docs, start=1):
        where = f"[[docs]] #{number} {_quote(source.path)}"
        pattern = os.path.expanduser(source.path)
        if _GLOB_CHARACTERS.isdisjoint(pattern):
            literal = config.base_dir / pattern
            if os.path.isdir(literal):
                hint = _quote(source.path.rstrip("/") + "/**/*.md")
                problems.append(
                    f"{where}: is a directory; to check the Markdown files in it, "
                    f"use a pattern such as {hint}"
                )
                continue
            if not os.path.isfile(literal):
                problems.append(f"{where}: file not found")
                continue
            matches = [literal]
        else:
            candidates = (
                config.base_dir / match
                for match in glob.glob(pattern, root_dir=config.base_dir, recursive=True)
            )
            matches = sorted(candidate for candidate in candidates if os.path.isfile(candidate))
            if not matches:
                problems.append(f"{where}: no files match")
                continue
        for match in matches:
            path = Path(os.path.abspath(match))
            _, notes = files.setdefault(os.path.realpath(path), (path, []))
            if source.notes is not None and source.notes not in notes:
                notes.append(source.notes)
    if problems:
        raise ConfigError(config.path, problems)
    return tuple(
        Doc(path=path, display_path=_display_path(path, config.base_dir), notes=tuple(notes))
        for path, notes in files.values()
    )


def _read_toml(path: Path) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ConfigError(path, ["file not found"]) from None
    except IsADirectoryError:
        raise ConfigError(path, ["is a directory, not a file"]) from None
    except UnicodeDecodeError:
        raise ConfigError(path, ["is not valid UTF-8"]) from None
    except OSError as error:
        raise ConfigError(path, [f"cannot be read: {error.strerror or error}"]) from None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        message = error.msg[:1].lower() + error.msg[1:]
        raise ConfigError(
            path, [f"invalid TOML: {message}"], position=(error.lineno, error.colno)
        ) from None


def _parse_docs(value: object, problems: list[str]) -> tuple[DocSource, ...]:
    sources: list[DocSource] = []
    entries = _entries(value, "docs", "the documents to check", problems)
    for number, entry in enumerate(entries, start=1):
        where = _entry_label("docs", number, entry, "path")
        if not isinstance(entry, dict):
            problems.append(f"{where}: must be a table, found {_describe(entry)}")
            continue
        before = len(problems)
        _reject_unknown_keys(entry, DOC_KEYS, where, problems)
        path = _string(entry, "path", where, problems, required=True)
        notes = _notes(entry, where, problems)
        if len(problems) > before or path is None:
            continue
        sources.append(DocSource(path=path, notes=notes))
    return tuple(sources)


def _parse_probes(value: object, problems: list[str]) -> tuple[Probe, ...]:
    probes: list[Probe] = []
    numbers_by_name: dict[str, int] = {}
    entries = _entries(value, "probes", "the commands that collect evidence", problems)
    for number, entry in enumerate(entries, start=1):
        where = _entry_label("probes", number, entry, "name")
        if not isinstance(entry, dict):
            problems.append(f"{where}: must be a table, found {_describe(entry)}")
            continue
        before = len(problems)
        _reject_unknown_keys(entry, PROBE_KEYS, where, problems)
        name = _probe_name(entry, where, problems)
        if name is not None:
            if name in numbers_by_name:
                problems.append(
                    f"{where}: name is already used by [[probes]] #{numbers_by_name[name]}"
                )
            else:
                numbers_by_name[name] = number
        command = _string(entry, "command", where, problems, required=True)
        timeout = _timeout(entry, where, problems)
        success_exit_codes = _success_exit_codes(entry, where, problems)
        notes = _notes(entry, where, problems)
        if (
            len(problems) > before
            or name is None
            or command is None
            or timeout is None
            or success_exit_codes is None
        ):
            continue
        probes.append(
            Probe(
                name=name,
                command=command,
                timeout=timeout,
                success_exit_codes=success_exit_codes,
                notes=notes,
            )
        )
    return tuple(probes)


def _entries(value: object, key: str, purpose: str, problems: list[str]) -> list[object]:
    if value is None:
        problems.append(f"no [[{key}]] entries: add at least one to list {purpose}")
        return []
    if isinstance(value, dict):
        problems.append(f"[{key}] must be written [[{key}]], with double brackets, once per entry")
        return []
    if not isinstance(value, list):
        problems.append(f"{key} must be [[{key}]] tables, found {_describe(value)}")
        return []
    if not value:
        problems.append(f"{key} is empty: add at least one [[{key}]] entry to list {purpose}")
        return []
    return value


def _entry_label(key: str, number: int, entry: object, label_key: str) -> str:
    label = f"[[{key}]] #{number}"
    if isinstance(entry, dict):
        value = entry.get(label_key)
        if isinstance(value, str):
            label += f" {_quote(value)}"
    return label


def _reject_unknown_keys(
    table: Mapping[str, object],
    allowed: Sequence[str],
    where: str | None,
    problems: list[str],
) -> None:
    for key in table:
        if key in allowed:
            continue
        message = f"unknown key {_quote(key)}"
        if close := difflib.get_close_matches(key, allowed, n=1):
            message += f" (did you mean {_quote(close[0])}?)"
        problems.append(message if where is None else f"{where}: {message}")


def _string(
    table: Mapping[str, object],
    key: str,
    where: str,
    problems: list[str],
    *,
    required: bool,
) -> str | None:
    value = table.get(key)
    if value is None:
        if required:
            problems.append(f"{where}: missing {key}")
    elif not isinstance(value, str):
        problems.append(f"{where}: {key} must be a string, found {_describe(value)}")
    elif not value.strip():
        problems.append(f"{where}: {key} must not be empty")
    elif "\0" in value:
        problems.append(f"{where}: {key} must not contain a NUL character")
    else:
        return value
    return None


def _probe_name(table: Mapping[str, object], where: str, problems: list[str]) -> str | None:
    name = _string(table, "name", where, problems, required=True)
    if name is None or _PROBE_NAME.fullmatch(name):
        return name
    message = (
        f'{where}: name must be 1 to 64 lowercase letters, digits, ".", "_" or "-", '
        "starting with a letter or digit"
    )
    suggestion = re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip("._-")[:64].rstrip("._-")
    if _PROBE_NAME.fullmatch(suggestion):
        message += f" (did you mean {_quote(suggestion)}?)"
    problems.append(message)
    return None


def _timeout(table: Mapping[str, object], where: str, problems: list[str]) -> float | None:
    value = table.get("timeout")
    if value is None:
        return DEFAULT_TIMEOUT
    if isinstance(value, bool) or not isinstance(value, int | float):
        problems.append(f"{where}: timeout must be a number of seconds, found {_describe(value)}")
        return None
    if not 0 < value <= MAX_TIMEOUT:
        problems.append(
            f"{where}: timeout must be more than 0 and at most {MAX_TIMEOUT:g} seconds, "
            f"found {value}"
        )
        return None
    return float(value)


def _success_exit_codes(
    table: Mapping[str, object], where: str, problems: list[str]
) -> frozenset[int] | None:
    key = "success-exit-codes"
    value = table.get(key)
    if value is None:
        return DEFAULT_SUCCESS_EXIT_CODES
    if not isinstance(value, list):
        problems.append(f"{where}: {key} must be an array of integers, found {_describe(value)}")
        return None
    if not value:
        problems.append(f"{where}: {key} must list at least one exit code")
        return None
    codes: set[int] = set()
    for code in value:
        if isinstance(code, bool) or not isinstance(code, int):
            problems.append(f"{where}: {key} must contain only integers, found {_describe(code)}")
            return None
        if not 0 <= code <= 255:
            problems.append(f"{where}: {key} contains {code}, but exit codes run from 0 to 255")
            return None
        if code in codes:
            problems.append(f"{where}: {key} lists {code} more than once")
            return None
        codes.add(code)
    return frozenset(codes)


def _notes(table: Mapping[str, object], where: str, problems: list[str]) -> str | None:
    notes = _string(table, "notes", where, problems, required=False)
    return None if notes is None else textwrap.dedent(notes).strip()


def _display_path(path: Path, base_dir: Path) -> str:
    return str(path.relative_to(base_dir)) if path.is_relative_to(base_dir) else str(path)


def _quote(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def _describe(value: object) -> str:
    match value:
        case bool():
            return "a boolean"
        case int():
            return "an integer"
        case float():
            return "a float"
        case str():
            return "a string"
        case list():
            return "an array"
        case dict():
            return "a table"
        case datetime():
            return "a date-time"
        case date():
            return "a date"
        case time():
            return "a time"
    return type(value).__name__
