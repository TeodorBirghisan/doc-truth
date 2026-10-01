import os
from collections.abc import Callable
from pathlib import Path

import pytest

from doc_truth.config import ConfigError, DocSource, Probe, load_config

DOCS = """
[[docs]]
path = "README.md"
"""

PROBES = """
[[probes]]
name = "uptime"
command = "uptime"
"""


def problems_in(write_config: Callable[[str], Path], text: str) -> tuple[str, ...]:
    with pytest.raises(ConfigError) as caught:
        load_config(write_config(text))
    return caught.value.problems


def test_minimal_config_uses_the_documented_defaults(
    write_config: Callable[[str], Path],
) -> None:
    config = load_config(write_config(DOCS + PROBES))

    assert config.docs == (DocSource(path="README.md", notes=None),)
    assert config.probes == (
        Probe(
            name="uptime",
            command="uptime",
            timeout=30.0,
            success_exit_codes=frozenset({0}),
            notes=None,
        ),
    )


def test_every_setting_is_read(write_config: Callable[[str], Path]) -> None:
    config = load_config(
        write_config(
            '''
            [[docs]]
            path = "docs/*.md"
            notes = """
                Section 3 lists every scheduled job.
                  This line keeps its extra indent.
                """

            [[docs]]
            path = "runbooks/**/*.md"

            [[probes]]
            name = "backup-service"
            command = "systemctl is-active restic-backup.service"
            timeout = 2.5
            success-exit-codes = [3, 0]
            notes = "Exit code 3 means the service is inactive."

            [[probes]]
            name = "cron.d_files"
            command = """
            for f in /etc/cron.d/*; do
              cat "$f"
            done
            """
            timeout = 3600
            '''
        )
    )

    assert config.docs == (
        DocSource(
            path="docs/*.md",
            notes="Section 3 lists every scheduled job.\n  This line keeps its extra indent.",
        ),
        DocSource(path="runbooks/**/*.md", notes=None),
    )
    assert config.probes == (
        Probe(
            name="backup-service",
            command="systemctl is-active restic-backup.service",
            timeout=2.5,
            success_exit_codes=frozenset({0, 3}),
            notes="Exit code 3 means the service is inactive.",
        ),
        Probe(
            name="cron.d_files",
            command='for f in /etc/cron.d/*; do\n  cat "$f"\ndone\n',
            timeout=3600.0,
            success_exit_codes=frozenset({0}),
            notes=None,
        ),
    )


def test_relative_paths_belong_to_the_config_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_config: Callable[[str], Path]
) -> None:
    write_config(DOCS + PROBES)
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")

    config = load_config(Path("../doc-truth.toml"))

    assert config.path == Path("../doc-truth.toml")
    assert config.base_dir == tmp_path


def test_a_byte_order_mark_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "doc-truth.toml"
    path.write_bytes(b"\xef\xbb\xbf" + (DOCS + PROBES).encode())

    assert load_config(path).probes[0].name == "uptime"


@pytest.mark.parametrize(
    ("text", "problems"),
    [
        pytest.param(
            "",
            (
                "no [[docs]] entries: add at least one to list the documents to check",
                "no [[probes]] entries: add at least one to list the commands that "
                "collect evidence",
            ),
            id="empty file",
        ),
        pytest.param(
            "prob = 1\n" + DOCS + PROBES,
            ('unknown key "prob" (did you mean "probes"?)',),
            id="unknown top-level key",
        ),
        pytest.param(
            DOCS + PROBES + '[model]\nname = "x"\n',
            ('unknown key "model"',),
            id="unknown table",
        ),
        pytest.param(
            '[docs]\npath = "README.md"\n' + PROBES,
            ("[docs] must be written [[docs]], with double brackets, once per entry",),
            id="single-bracket table",
        ),
        pytest.param(
            'docs = "README.md"\n' + PROBES,
            ("docs must be [[docs]] tables, found a string",),
            id="not an array",
        ),
        pytest.param(
            "docs = []\n" + PROBES,
            ("docs is empty: add at least one [[docs]] entry to list the documents to check",),
            id="empty array",
        ),
        pytest.param(
            'docs = ["README.md"]\n' + PROBES,
            ("[[docs]] #1: must be a table, found a string",),
            id="array of strings",
        ),
        pytest.param(
            "probes = [1]\n" + DOCS,
            ("[[probes]] #1: must be a table, found an integer",),
            id="array of integers",
        ),
    ],
)
def test_structure_problems(
    write_config: Callable[[str], Path], text: str, problems: tuple[str, ...]
) -> None:
    assert problems_in(write_config, text) == problems


@pytest.mark.parametrize(
    ("entry", "problem"),
    [
        ('notes = "x"', "[[docs]] #1: missing path"),
        ("path = 7", "[[docs]] #1: path must be a string, found an integer"),
        ("path = 2026-10-01", "[[docs]] #1: path must be a string, found a date"),
        ("path = 2026-10-01T09:30:00", "[[docs]] #1: path must be a string, found a date-time"),
        ("path = 09:30:00", "[[docs]] #1: path must be a string, found a time"),
        ("path = [1]", "[[docs]] #1: path must be a string, found an array"),
        ("path = {}", "[[docs]] #1: path must be a string, found a table"),
        ("path = 1.5", "[[docs]] #1: path must be a string, found a float"),
        ('path = " "', '[[docs]] #1 " ": path must not be empty'),
        (
            'path = "a\\u0000b"',
            '[[docs]] #1 "a\\u0000b": path must not contain a NUL character',
        ),
        (
            'path = "README.md"\npaths = "x"',
            '[[docs]] #1 "README.md": unknown key "paths" (did you mean "path"?)',
        ),
        ('path = "README.md"\nnotes = ""', '[[docs]] #1 "README.md": notes must not be empty'),
        (
            'path = "README.md"\nnotes = true',
            '[[docs]] #1 "README.md": notes must be a string, found a boolean',
        ),
    ],
)
def test_docs_entry_problems(write_config: Callable[[str], Path], entry: str, problem: str) -> None:
    assert problems_in(write_config, f"[[docs]]\n{entry}\n" + PROBES) == (problem,)


NAME_RULE = (
    'name must be 1 to 64 lowercase letters, digits, ".", "_" or "-", '
    "starting with a letter or digit"
)


@pytest.mark.parametrize(
    ("entry", "problem"),
    [
        ('command = "uptime"', "[[probes]] #1: missing name"),
        ('name = "uptime"', '[[probes]] #1 "uptime": missing command'),
        ('name = 5\ncommand = "uptime"', "[[probes]] #1: name must be a string, found an integer"),
        ('name = ""\ncommand = "uptime"', '[[probes]] #1 "": name must not be empty'),
        (
            'name = "Uptime"\ncommand = "uptime"',
            f'[[probes]] #1 "Uptime": {NAME_RULE} (did you mean "uptime"?)',
        ),
        (
            'name = "up time "\ncommand = "uptime"',
            f'[[probes]] #1 "up time ": {NAME_RULE} (did you mean "up-time"?)',
        ),
        (
            'name = "-uptime"\ncommand = "uptime"',
            f'[[probes]] #1 "-uptime": {NAME_RULE} (did you mean "uptime"?)',
        ),
        (
            f'name = "{"a" * 65}"\ncommand = "uptime"',
            f'[[probes]] #1 "{"a" * 65}": {NAME_RULE} (did you mean "{"a" * 64}"?)',
        ),
        ('name = "???"\ncommand = "uptime"', f'[[probes]] #1 "???": {NAME_RULE}'),
        ('name = "uptime"\ncommand = "  "', '[[probes]] #1 "uptime": command must not be empty'),
        (
            'name = "uptime"\ncommand = ["uptime"]',
            '[[probes]] #1 "uptime": command must be a string, found an array',
        ),
        (
            'name = "uptime"\ncommand = "uptime"\ntimout = 5',
            '[[probes]] #1 "uptime": unknown key "timout" (did you mean "timeout"?)',
        ),
        (
            'name = "uptime"\ncommand = "uptime"\nsuccess_exit_codes = [0]',
            '[[probes]] #1 "uptime": unknown key "success_exit_codes" '
            '(did you mean "success-exit-codes"?)',
        ),
        (
            'name = "uptime"\ncommand = "uptime"\nhost = "core"',
            '[[probes]] #1 "uptime": unknown key "host"',
        ),
        (
            'name = "uptime"\ncommand = "uptime"\nnotes = "\\n\\t"',
            '[[probes]] #1 "uptime": notes must not be empty',
        ),
    ],
)
def test_probe_entry_problems(
    write_config: Callable[[str], Path], entry: str, problem: str
) -> None:
    assert problems_in(write_config, DOCS + f"[[probes]]\n{entry}\n") == (problem,)


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        ("true", "timeout must be a number of seconds, found a boolean"),
        ('"30"', "timeout must be a number of seconds, found a string"),
        ("0", "timeout must be more than 0 and at most 3600 seconds, found 0"),
        ("-1", "timeout must be more than 0 and at most 3600 seconds, found -1"),
        ("3600.5", "timeout must be more than 0 and at most 3600 seconds, found 3600.5"),
        ("inf", "timeout must be more than 0 and at most 3600 seconds, found inf"),
        ("nan", "timeout must be more than 0 and at most 3600 seconds, found nan"),
        (
            "9223372036854775808",
            "timeout must be more than 0 and at most 3600 seconds, found 9223372036854775808",
        ),
    ],
)
def test_timeout_problems(write_config: Callable[[str], Path], value: str, problem: str) -> None:
    text = DOCS + f'[[probes]]\nname = "uptime"\ncommand = "uptime"\ntimeout = {value}\n'

    assert problems_in(write_config, text) == (f'[[probes]] #1 "uptime": {problem}',)


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        ("0", "success-exit-codes must be an array of integers, found an integer"),
        ("[]", "success-exit-codes must list at least one exit code"),
        ("[true]", "success-exit-codes must contain only integers, found a boolean"),
        ("[1.0]", "success-exit-codes must contain only integers, found a float"),
        ("[256]", "success-exit-codes contains 256, but exit codes run from 0 to 255"),
        ("[-1]", "success-exit-codes contains -1, but exit codes run from 0 to 255"),
        ("[0, 1, 0]", "success-exit-codes lists 0 more than once"),
    ],
)
def test_success_exit_code_problems(
    write_config: Callable[[str], Path], value: str, problem: str
) -> None:
    text = DOCS + f'[[probes]]\nname = "uptime"\ncommand = "uptime"\nsuccess-exit-codes = {value}\n'

    assert problems_in(write_config, text) == (f'[[probes]] #1 "uptime": {problem}',)


def test_limits_are_inclusive(write_config: Callable[[str], Path]) -> None:
    config = load_config(
        write_config(
            DOCS
            + f"""
            [[probes]]
            name = "{"a" * 64}"
            command = "true"
            timeout = 3600
            success-exit-codes = [0, 255]

            [[probes]]
            name = "0"
            command = "true"
            timeout = 0.001
            """
        )
    )

    assert [(probe.name, probe.timeout) for probe in config.probes] == [
        ("a" * 64, 3600.0),
        ("0", 0.001),
    ]
    assert config.probes[0].success_exit_codes == frozenset({0, 255})


def test_duplicate_probe_names_point_at_the_first_use(
    write_config: Callable[[str], Path],
) -> None:
    probe = '[[probes]]\nname = "uptime"\ncommand = "uptime"\n'

    assert problems_in(write_config, DOCS + probe * 3) == (
        '[[probes]] #2 "uptime": name is already used by [[probes]] #1',
        '[[probes]] #3 "uptime": name is already used by [[probes]] #1',
    )


def test_every_problem_is_reported_at_once(write_config: Callable[[str], Path]) -> None:
    path = write_config(
        """
        [[docs]]
        path = 7

        [[probes]]
        name = "uptime"
        command = ""
        """
    )

    with pytest.raises(ConfigError) as caught:
        load_config(path)

    assert str(caught.value) == (
        f"{path}: 2 problems\n"
        "  - [[docs]] #1: path must be a string, found an integer\n"
        '  - [[probes]] #1 "uptime": command must not be empty'
    )


def test_invalid_toml_points_at_the_line_and_column(
    write_config: Callable[[str], Path],
) -> None:
    path = write_config('[[docs]]\npath = "README.md"\n[[probes]\n')

    with pytest.raises(ConfigError) as caught:
        load_config(path)

    assert caught.value.position == (3, 9)
    assert str(caught.value).startswith(f"{path}:3:9: invalid TOML: expected ")


def test_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "doc-truth.toml"

    with pytest.raises(ConfigError) as caught:
        load_config(path)

    assert str(caught.value) == f"{path}: file not found"


def test_directory_instead_of_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as caught:
        load_config(tmp_path)

    assert str(caught.value) == f"{tmp_path}: is a directory, not a file"


def test_invalid_utf8(tmp_path: Path) -> None:
    path = tmp_path / "doc-truth.toml"
    path.write_bytes(b'[[docs]]\npath = "\xff"\n')

    with pytest.raises(ConfigError) as caught:
        load_config(path)

    assert str(caught.value) == f"{path}: is not valid UTF-8"


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read files without permission")
def test_unreadable_file(write_config: Callable[[str], Path]) -> None:
    path = write_config(DOCS + PROBES)
    path.chmod(0)

    with pytest.raises(ConfigError) as caught:
        load_config(path)

    assert str(caught.value) == f"{path}: cannot be read: Permission denied"
