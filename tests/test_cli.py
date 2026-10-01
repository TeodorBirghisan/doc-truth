import subprocess
import sys
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest

from doc_truth import cli
from doc_truth.cli import main

CONFIG = """
[[docs]]
path = "docs/*.md"

[[probes]]
name = "uptime"
command = "uptime"

[[probes]]
name = "backup-service"
command = "systemctl is-active restic-backup.service"
timeout = 2.5
"""


@pytest.fixture(autouse=True)
def plain_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYTHON_COLORS", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")


def test_validate_lists_the_resolved_docs_and_probes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    write_config: Callable[[str], Path],
    touch: Callable[..., None],
) -> None:
    write_config(CONFIG)
    touch("docs/b.md", "docs/a.md")
    monkeypatch.chdir(tmp_path)

    assert main(["validate"]) == 0
    assert capsys.readouterr() == (
        "doc-truth.toml is valid.\n"
        "\n"
        "Docs (2):\n"
        "  docs/a.md\n"
        "  docs/b.md\n"
        "\n"
        "Probes (2):\n"
        "  uptime          timeout 30s\n"
        "  backup-service  timeout 2.5s\n",
        "",
    )


def test_validate_reads_the_config_given_with_the_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    write_config: Callable[[str], Path],
    touch: Callable[..., None],
) -> None:
    config = write_config(CONFIG)
    touch("docs/a.md", "elsewhere/.keep")
    monkeypatch.chdir(tmp_path / "elsewhere")

    assert main(["validate", "--config", "../doc-truth.toml"]) == 0
    assert capsys.readouterr().out.startswith("../doc-truth.toml is valid.\n")
    assert main(["validate", "-c", str(config)]) == 0
    assert capsys.readouterr().out.startswith(f"{config} is valid.\n")


def test_validate_exits_2_on_config_problems(
    capsys: pytest.CaptureFixture[str], write_config: Callable[[str], Path]
) -> None:
    config = write_config('[[docs]]\npath = "README.md"\n')

    assert main(["validate", "--config", str(config)]) == 2
    assert capsys.readouterr() == (
        "",
        f"doc-truth: error: {config}: no [[probes]] entries: "
        "add at least one to list the commands that collect evidence\n",
    )


def test_validate_exits_2_when_a_doc_path_matches_nothing(
    capsys: pytest.CaptureFixture[str], write_config: Callable[[str], Path]
) -> None:
    config = write_config(CONFIG)

    assert main(["validate", "--config", str(config)]) == 2
    assert capsys.readouterr() == (
        "",
        f'doc-truth: error: {config}: [[docs]] #1 "docs/*.md": no files match\n',
    )


def test_validate_without_a_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["validate"]) == 2
    assert capsys.readouterr() == ("", "doc-truth: error: doc-truth.toml: file not found\n")


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--version"])

    assert caught.value.code == 0
    assert capsys.readouterr().out == f"doc-truth {version('doc-truth')}\n"


def test_version_when_the_package_metadata_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def missing(name: str) -> str:
        raise PackageNotFoundError(name)

    monkeypatch.setattr(cli, "version", missing)

    with pytest.raises(SystemExit):
        main(["--version"])

    assert capsys.readouterr().out == "doc-truth unknown\n"


def test_a_command_is_required(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main([])

    assert caught.value.code == 2
    assert "the following arguments are required: <command>" in capsys.readouterr().err


def test_a_mistyped_command_gets_a_suggestion(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["valdate"])

    assert caught.value.code == 2
    assert "maybe you meant 'validate'?" in capsys.readouterr().err


def test_the_package_runs_as_a_module() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "doc_truth", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert (result.returncode, result.stdout, result.stderr) == (
        0,
        f"doc-truth {version('doc-truth')}\n",
        "",
    )
