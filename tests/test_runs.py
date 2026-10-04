import errno
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from doc_truth import runs as runs_module
from doc_truth.config import Config, Probe
from doc_truth.evidence import Evidence, ProbeResult, evidence_json, evidence_markdown
from doc_truth.runs import RunsError, prepare_runs_dir, write_run

needs_permissions = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")


def make_config(directory: Path) -> Config:
    return Config(path=directory / "doc-truth.toml", base_dir=directory, docs=(), probes=())


def make_evidence(started_at: datetime = datetime(2026, 10, 4, 12, 4, 19, tzinfo=UTC)) -> Evidence:
    probe = Probe(
        name="uptime", command="uptime", timeout=30, success_exit_codes=frozenset({0}), notes=None
    )
    result = ProbeResult(
        probe=probe,
        stdout="up 3 days\n",
        stderr="",
        exit_code=0,
        signal=None,
        duration=0.01,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        failure=None,
    )
    return Evidence(
        tool_version="0.1.0",
        host="core",
        user="teo",
        timezone="UTC",
        utc_offset="+00:00",
        started_at=started_at,
        finished_at=started_at,
        config_path=Path("/etc/doc-truth.toml"),
        results=(result,),
    )


def test_runs_go_next_to_the_config_by_default(tmp_path: Path) -> None:
    runs = prepare_runs_dir(make_config(tmp_path), None)
    evidence = make_evidence()

    run = write_run(evidence, runs)

    assert run == tmp_path / ".doc-truth" / "runs" / "20261004T120419Z"
    assert sorted(path.name for path in run.iterdir()) == ["evidence.json", "evidence.md"]
    assert (run / "evidence.json").read_text(encoding="utf-8") == evidence_json(evidence)
    assert (run / "evidence.md").read_text(encoding="utf-8") == evidence_markdown(evidence)


def test_run_folders_are_private_to_the_user(tmp_path: Path) -> None:
    run = write_run(make_evidence(), prepare_runs_dir(make_config(tmp_path), None))

    assert stat.S_IMODE(run.stat().st_mode) == 0o700


def test_the_default_folder_is_kept_out_of_git(tmp_path: Path) -> None:
    prepare_runs_dir(make_config(tmp_path), None)

    ignore = (tmp_path / ".doc-truth" / ".gitignore").read_text(encoding="utf-8")
    assert ignore.splitlines()[-1] == "*"


def test_an_existing_default_folder_is_left_as_it_is(tmp_path: Path) -> None:
    (tmp_path / ".doc-truth").mkdir()

    prepare_runs_dir(make_config(tmp_path), None)

    assert sorted(path.name for path in (tmp_path / ".doc-truth").iterdir()) == ["runs"]


def test_an_output_dir_replaces_the_default_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    runs = prepare_runs_dir(make_config(tmp_path / "config"), Path("state"))

    assert runs == tmp_path / "state" / "runs"
    assert runs.is_dir()
    assert not (tmp_path / "state" / ".gitignore").exists()
    assert not (tmp_path / "config").exists()


def test_runs_started_in_the_same_second_get_their_own_folders(tmp_path: Path) -> None:
    runs = prepare_runs_dir(make_config(tmp_path), None)

    names = [write_run(make_evidence(), runs).name for _ in range(3)]

    assert names == ["20261004T120419Z", "20261004T120419Z-2", "20261004T120419Z-3"]


def test_run_folders_are_named_in_utc(tmp_path: Path) -> None:
    local = datetime(2026, 10, 4, 15, 4, 19).astimezone()
    runs = prepare_runs_dir(make_config(tmp_path), None)

    run = write_run(make_evidence(local), runs)

    assert run.name == local.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


@needs_permissions
def test_an_unwritable_output_dir_is_an_error(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)

    with pytest.raises(RunsError) as caught:
        prepare_runs_dir(make_config(tmp_path), locked / "state")

    assert (
        str(caught.value) == f"cannot write the evidence to {locked / 'state'}: Permission denied"
    )


@needs_permissions
def test_an_unwritable_runs_folder_is_an_error(tmp_path: Path) -> None:
    runs = prepare_runs_dir(make_config(tmp_path), None)
    runs.chmod(0o500)

    with pytest.raises(RunsError, match=r"^cannot write the evidence to .*: Permission denied$"):
        write_run(make_evidence(), runs)


def test_a_failed_write_leaves_no_partial_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def disk_full(evidence: Evidence) -> str:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    monkeypatch.setattr(runs_module, "evidence_markdown", disk_full)
    runs = prepare_runs_dir(make_config(tmp_path), None)

    with pytest.raises(RunsError, match=r": No space left on device$"):
        write_run(make_evidence(), runs)

    assert list(runs.iterdir()) == []


def test_an_interrupted_write_leaves_no_partial_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(evidence: Evidence) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(runs_module, "evidence_markdown", interrupted)
    runs = prepare_runs_dir(make_config(tmp_path), None)

    with pytest.raises(KeyboardInterrupt):
        write_run(make_evidence(), runs)

    assert list(runs.iterdir()) == []


def test_a_taken_name_reported_as_eexist_is_retried_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rename = Path.rename
    attempts: list[Path] = []

    def taken_once(self: Path, target: Path) -> Path:
        attempts.append(target)
        if len(attempts) == 1:
            raise OSError(errno.EEXIST, os.strerror(errno.EEXIST))
        return rename(self, target)

    monkeypatch.setattr(Path, "rename", taken_once)
    runs = prepare_runs_dir(make_config(tmp_path), None)

    run = write_run(make_evidence(), runs)

    assert attempts == [runs / "20261004T120419Z", runs / "20261004T120419Z-2"]
    assert run == runs / "20261004T120419Z-2"


def test_other_rename_errors_are_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[Path] = []

    def cross_device(self: Path, target: Path) -> Path:
        attempts.append(target)
        if len(attempts) > 3:
            raise AssertionError("a rename error that can't succeed was retried")
        raise OSError(errno.EXDEV, os.strerror(errno.EXDEV))

    monkeypatch.setattr(Path, "rename", cross_device)
    runs = prepare_runs_dir(make_config(tmp_path), None)

    with pytest.raises(RunsError, match=r": Invalid cross-device link$"):
        write_run(make_evidence(), runs)

    assert attempts == [runs / "20261004T120419Z"]
    assert list(runs.iterdir()) == []
