import errno
import json
import os
import stat
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from doc_truth import runs as runs_module
from doc_truth.config import Config, Probe
from doc_truth.evidence import Evidence, ProbeResult, evidence_json, evidence_markdown
from doc_truth.report import Report, report_json, report_markdown
from doc_truth.runs import (
    RunsError,
    latest_report,
    prepare_runs_dir,
    runs_dir,
    write_report,
    write_run,
)

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
        host="homeserver",
        user="ops",
        timezone="UTC",
        utc_offset="+00:00",
        started_at=started_at,
        finished_at=started_at,
        config_path=Path("/etc/doc-truth.toml"),
        results=(result,),
    )


def make_report(evidence: Evidence) -> Report:
    return Report(
        evidence=evidence,
        docs=("docs/ops.md",),
        prompt_version=1,
        requested_model="sonnet",
        answers=(),
        findings=(),
        dropped=(),
        finished_at=evidence.finished_at,
    )


def write_text_failing_for(name: str, error: BaseException) -> Callable[..., int]:
    write_text = Path.write_text

    def failing(self: Path, data: str, *args: Any, **kwargs: Any) -> int:
        if self.name == name:
            raise error
        return write_text(self, data, *args, **kwargs)

    return failing


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


def test_the_report_goes_next_to_the_evidence(tmp_path: Path) -> None:
    evidence = make_evidence()
    run = write_run(evidence, prepare_runs_dir(make_config(tmp_path), None))
    report = make_report(evidence)

    write_report(report, run)

    assert sorted(path.name for path in run.iterdir()) == [
        "evidence.json",
        "evidence.md",
        "report.json",
        "report.md",
    ]
    assert (run / "report.json").read_text(encoding="utf-8") == report_json(report)
    assert (run / "report.md").read_text(encoding="utf-8") == report_markdown(report)


@pytest.mark.parametrize(
    ("error", "raised"),
    [
        (OSError(errno.ENOSPC, os.strerror(errno.ENOSPC)), RunsError),
        (KeyboardInterrupt(), KeyboardInterrupt),
    ],
)
def test_a_failed_report_write_leaves_no_partial_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    raised: type[BaseException],
) -> None:
    evidence = make_evidence()
    run = write_run(evidence, prepare_runs_dir(make_config(tmp_path), None))
    monkeypatch.setattr(Path, "write_text", write_text_failing_for(".report.md.incomplete", error))

    with pytest.raises(raised) as caught:
        write_report(make_report(evidence), run)

    if raised is RunsError:
        assert str(caught.value) == f"cannot write the report to {run}: No space left on device"
    assert sorted(path.name for path in run.iterdir()) == ["evidence.json", "evidence.md"]


@needs_permissions
def test_an_unwritable_run_folder_is_an_error_for_the_report(tmp_path: Path) -> None:
    evidence = make_evidence()
    run = write_run(evidence, prepare_runs_dir(make_config(tmp_path), None))
    run.chmod(0o500)

    with pytest.raises(RunsError) as caught:
        write_report(make_report(evidence), run)

    assert str(caught.value) == f"cannot write the report to {run}: Permission denied"
    assert sorted(path.name for path in run.iterdir()) == ["evidence.json", "evidence.md"]


def write_report_file(run: Path, **fields: object) -> None:
    run.mkdir(parents=True)
    report = {
        "format": 2,
        "config": "/etc/doc-truth.toml",
        "findings": [],
        "not_rechecked": [],
        "no_longer_reported": [],
    }
    (run / "report.json").write_text(json.dumps(report | fields), encoding="utf-8")


def earlier_entry(id_: str, *, runs_open: int = 1) -> dict[str, object]:
    return {
        "id": id_,
        "title": "A title",
        "confidence": "confirmed",
        "runs_open": runs_open,
        "acknowledged": False,
        "identity": {
            "kind": "contradiction",
            "doc": {"file": "docs/ops.md", "lines": ["A line."]},
            "evidence": {"probe": "uptime", "lines": ["up 3 days"]},
        },
    }


@pytest.fixture
def config_at_etc() -> Config:
    return make_config(Path("/etc"))


def test_with_no_runs_there_is_no_previous_report(tmp_path: Path, config_at_etc: Config) -> None:
    assert latest_report(tmp_path / "runs", config_at_etc) is None
    assert latest_report(tmp_path, config_at_etc) is None


def test_the_newest_report_is_the_previous_one(tmp_path: Path, config_at_etc: Config) -> None:
    write_report_file(tmp_path / "20261019T080000Z", findings=[earlier_entry("old")])
    write_report_file(tmp_path / "20261026T080000Z", findings=[earlier_entry("new")])
    write_report_file(tmp_path / "20261012T080000Z", findings=[earlier_entry("older")])

    previous = latest_report(tmp_path, config_at_etc)

    assert previous is not None
    assert previous.run == "20261026T080000Z"
    assert [item.id for item in previous.findings] == ["new"]


def test_a_run_without_a_report_is_skipped(tmp_path: Path, config_at_etc: Config) -> None:
    write_report_file(tmp_path / "20261019T080000Z")
    (tmp_path / "20261026T080000Z").mkdir()

    previous = latest_report(tmp_path, config_at_etc)

    assert previous is not None
    assert previous.run == "20261019T080000Z"


def test_a_half_written_run_is_skipped(tmp_path: Path, config_at_etc: Config) -> None:
    write_report_file(tmp_path / ".incomplete-abc")

    assert latest_report(tmp_path, config_at_etc) is None


def test_a_stray_file_among_the_runs_is_skipped(tmp_path: Path, config_at_etc: Config) -> None:
    (tmp_path / "20261026T080000Z").write_text("not a folder", encoding="utf-8")

    assert latest_report(tmp_path, config_at_etc) is None


def test_another_configs_run_does_not_count(tmp_path: Path, config_at_etc: Config) -> None:
    write_report_file(tmp_path / "20261019T080000Z", findings=[earlier_entry("mine")])
    write_report_file(tmp_path / "20261026T080000Z", config="/srv/other.toml")

    previous = latest_report(tmp_path, config_at_etc)

    assert previous is not None
    assert [item.id for item in previous.findings] == ["mine"]


def test_not_rechecked_findings_carry_over(tmp_path: Path, config_at_etc: Config) -> None:
    write_report_file(
        tmp_path / "20261026T080000Z",
        findings=[earlier_entry("seen")],
        not_rechecked=[earlier_entry("waiting", runs_open=3)],
    )

    previous = latest_report(tmp_path, config_at_etc)

    assert previous is not None
    assert [(item.id, item.runs_open) for item in previous.findings] == [
        ("seen", 1),
        ("waiting", 3),
    ]


def test_no_longer_reported_findings_can_be_found_but_do_not_carry_over(
    tmp_path: Path, config_at_etc: Config
) -> None:
    write_report_file(
        tmp_path / "20261026T080000Z",
        findings=[earlier_entry("open")],
        no_longer_reported=[earlier_entry("gone")],
    )

    previous = latest_report(tmp_path, config_at_etc)

    assert previous is not None
    assert [item.id for item in previous.findings] == ["open"]
    assert [item.id for item in previous.no_longer_reported] == ["gone"]


def test_a_finding_that_left_the_config_does_not_carry_over(
    tmp_path: Path, config_at_etc: Config
) -> None:
    write_report_file(
        tmp_path / "20261026T080000Z",
        not_rechecked=[
            {**earlier_entry("gone"), "left_config": True},
            earlier_entry("waiting"),
        ],
    )

    previous = latest_report(tmp_path, config_at_etc)

    assert previous is not None
    assert [item.id for item in previous.findings] == ["waiting"]


def test_a_report_from_before_this_format_means_no_previous_report(
    tmp_path: Path, config_at_etc: Config
) -> None:
    write_report_file(tmp_path / "20261026T080000Z", format=1, findings=[{"title": "old"}])
    write_report_file(tmp_path / "20261019T080000Z", findings=[earlier_entry("older")])

    assert latest_report(tmp_path, config_at_etc) is None


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        '{"format": 2, "config": "/etc/doc-truth.toml"}',
        '{"format": 2, "config": "/etc/doc-truth.toml", "findings": 3, "not_rechecked": []}',
        '{"format": 2, "config": "/etc/doc-truth.toml", "findings": [3], "not_rechecked": []}',
        '{"format": 2, "config": "/etc/doc-truth.toml", "findings": [{}], "not_rechecked": []}',
    ],
)
def test_an_unreadable_report_is_an_error(tmp_path: Path, config_at_etc: Config, text: str) -> None:
    run = tmp_path / "20261026T080000Z"
    run.mkdir()
    (run / "report.json").write_text(text, encoding="utf-8")

    with pytest.raises(RunsError, match=r"cannot read .*report\.json"):
        latest_report(tmp_path, config_at_etc)


def test_a_report_that_cannot_be_opened_is_an_error(tmp_path: Path, config_at_etc: Config) -> None:
    (tmp_path / "20261026T080000Z" / "report.json").mkdir(parents=True)

    with pytest.raises(RunsError, match=r"cannot read .*report\.json: Is a directory"):
        latest_report(tmp_path, config_at_etc)


@needs_permissions
def test_a_newer_run_that_cannot_be_read_is_an_error_not_skipped(
    tmp_path: Path, config_at_etc: Config
) -> None:
    write_report_file(tmp_path / "20261026T080000Z")
    locked = tmp_path / "20261102T080000Z"
    write_report_file(locked)
    locked.chmod(0)
    try:
        with pytest.raises(RunsError, match=r"cannot read .*report\.json: Permission denied"):
            latest_report(tmp_path, config_at_etc)
    finally:
        locked.chmod(0o700)


@pytest.mark.parametrize(("written_from", "read_from"), [("link", "real"), ("real", "link")])
def test_the_same_config_reached_through_a_link_keeps_its_history(
    tmp_path: Path, written_from: str, read_from: str
) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    runs = tmp_path / "runs"
    write_report_file(
        runs / "20261026T080000Z", config=str(tmp_path / written_from / "doc-truth.toml")
    )

    previous = latest_report(runs, make_config(tmp_path / read_from))

    assert previous is not None
    assert previous.run == "20261026T080000Z"


def test_a_report_without_a_config_path_does_not_count(
    tmp_path: Path, config_at_etc: Config
) -> None:
    write_report_file(tmp_path / "20261026T080000Z", config=None)

    assert latest_report(tmp_path, config_at_etc) is None


def test_a_runs_path_that_is_not_a_folder_is_an_error(
    tmp_path: Path, config_at_etc: Config
) -> None:
    runs = tmp_path / "runs"
    runs.write_text("not a folder", encoding="utf-8")

    with pytest.raises(RunsError, match=r"cannot read .*runs: Not a directory"):
        latest_report(runs, config_at_etc)


def test_finding_the_runs_dir_creates_nothing(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    assert runs_dir(config, None) == tmp_path / ".doc-truth" / "runs"
    assert runs_dir(config, tmp_path / "elsewhere") == tmp_path / "elsewhere" / "runs"
    assert list(tmp_path.iterdir()) == []
