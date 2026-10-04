import re
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


COLLECT_CONFIG = """
[[docs]]
path = "docs/*.md"

[[probes]]
name = "greeting"
command = "echo hello"

[[probes]]
name = "inactive-unit"
command = "echo inactive; exit 3"
success-exit-codes = [0, 3]
"""


def test_collect_writes_a_run_and_prints_its_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    write_config: Callable[[str], Path],
) -> None:
    write_config(COLLECT_CONFIG)
    monkeypatch.chdir(tmp_path)

    assert main(["collect"]) == 0

    out, err = capsys.readouterr()
    run = Path(out.removesuffix("\n"))
    assert run.parent == tmp_path / ".doc-truth" / "runs"
    assert "## greeting" in (run / "evidence.md").read_text(encoding="utf-8")
    assert (run / "evidence.json").is_file()
    assert re.fullmatch(
        r"\[1/2\] greeting       ok      \d+\.\d\ds\n"
        r"\[2/2\] inactive-unit  ok      \d+\.\d\ds\n"
        r"Probes: 2 ok, 0 failed\.\n",
        err,
    )


def test_collect_exits_2_when_a_probe_fails_and_still_writes_the_evidence(
    capsys: pytest.CaptureFixture[str], write_config: Callable[[str], Path]
) -> None:
    config = write_config(COLLECT_CONFIG.replace("[0, 3]", "[0]"))

    assert main(["collect", "--config", str(config)]) == 2

    out, err = capsys.readouterr()
    assert "PROBE FAILED" in (Path(out.strip()) / "evidence.md").read_text(encoding="utf-8")
    assert re.search(
        r"^\[2/2\] inactive-unit  failed  \d+\.\d\ds  "
        r"exit code 3 is not in success-exit-codes \[0\]$",
        err,
        flags=re.MULTILINE,
    )
    assert err.endswith("Probes: 1 ok, 1 failed.\n")


def test_collect_pads_the_counter_for_ten_or_more_probes(
    capsys: pytest.CaptureFixture[str], write_config: Callable[[str], Path]
) -> None:
    probes = "".join(f'[[probes]]\nname = "p{n}"\ncommand = "true"\n' for n in range(1, 11))
    config = write_config(f'[[docs]]\npath = "a.md"\n{probes}')

    assert main(["collect", "-c", str(config)]) == 0

    lines = capsys.readouterr().err.splitlines()
    assert lines[0].startswith("[ 1/10] p1   ok")
    assert lines[9].startswith("[10/10] p10  ok")


def test_collect_does_not_need_the_docs_to_exist(
    capsys: pytest.CaptureFixture[str], write_config: Callable[[str], Path]
) -> None:
    config = write_config(COLLECT_CONFIG)

    assert main(["collect", "-c", str(config)]) == 0


def test_collect_writes_to_the_output_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], write_config: Callable[[str], Path]
) -> None:
    config = write_config(COLLECT_CONFIG)

    assert main(["collect", "-c", str(config), "--output-dir", str(tmp_path / "state")]) == 0

    assert Path(capsys.readouterr().out.strip()).parent == tmp_path / "state" / "runs"
    assert not (tmp_path / ".doc-truth").exists()


def test_collect_checks_the_output_dir_before_running_any_probe(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], write_config: Callable[[str], Path]
) -> None:
    (tmp_path / "state").write_text("not a directory\n", encoding="utf-8")
    config = write_config(
        '[[docs]]\npath = "a.md"\n[[probes]]\nname = "x"\ncommand = "touch ran"\n'
    )

    assert main(["collect", "-c", str(config), "-o", str(tmp_path / "state")]) == 2

    assert capsys.readouterr() == (
        "",
        f"doc-truth: error: cannot write the evidence to {tmp_path / 'state'}: Not a directory\n",
    )
    assert not (tmp_path / "ran").exists()


def test_collect_exits_2_without_bash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    write_config: Callable[[str], Path],
) -> None:
    config = write_config(COLLECT_CONFIG)
    monkeypatch.setenv("PATH", str(tmp_path))

    assert main(["collect", "-c", str(config)]) == 2

    assert capsys.readouterr().err.startswith("doc-truth: error: bash was not found on PATH;")


def test_collect_exits_2_on_config_problems(
    capsys: pytest.CaptureFixture[str], write_config: Callable[[str], Path]
) -> None:
    config = write_config('[[docs]]\npath = "README.md"\n')

    assert main(["collect", "-c", str(config)]) == 2
    assert "no [[probes]] entries" in capsys.readouterr().err


def test_an_interrupted_run_exits_130(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    write_config: Callable[[str], Path],
) -> None:
    def interrupt(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "collect", interrupt)
    config = write_config(COLLECT_CONFIG)

    assert main(["collect", "-c", str(config)]) == 130
    assert capsys.readouterr() == ("", "doc-truth: interrupted\n")
