import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from fakes import ANSWER, FakeClaude

from doc_truth.cli import main

CONFIG = """
[[docs]]
path = "docs/*.md"

[[probes]]
name = "timers"
command = "echo 'restic-backup.timer *-*-* 03:00:00'"
"""
OPERATIONS = """# Operations

restic backs up nightly at 02:00.
"""
TITLE = "Backups run at 03:00, not 02:00"


def a_finding(*, confidence: str = "confirmed", schedule: str = "03:00:00") -> dict[str, object]:
    return {
        "kind": "contradiction",
        "title": TITLE,
        "doc": {"file": "docs/operations.md", "line": 3, "quote": "nightly at 02:00"},
        "evidence": {"probe": "timers", "quote": f"*-*-* {schedule}"},
        "confidence": confidence,
        "fix": "doc",
        "reason": "The timer fires later.",
    }


def answer_with(fake_claude: FakeClaude, *findings: dict[str, object]) -> None:
    fake_claude.play(*ANSWER, answers={"*": json.dumps({"findings": findings})})


@pytest.fixture
def config(tmp_path: Path, write_config: Callable[[str], Path]) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "operations.md").write_text(OPERATIONS, encoding="utf-8")
    return write_config(CONFIG)


@pytest.fixture
def known_file(tmp_path: Path) -> Path:
    return tmp_path / "doc-truth-known.toml"


def check(path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, Path, str]:
    code = main(["check", "-c", str(path)])
    out, err = capsys.readouterr()
    return code, Path(out.removesuffix("\n")), err


def report_of(run: Path) -> dict[str, object]:
    data: dict[str, object] = json.loads((run / "report.json").read_text(encoding="utf-8"))
    return data


def counts(run: Path) -> dict[str, int]:
    found = report_of(run)["counts"]
    assert isinstance(found, dict)
    return found


def markdown_of(run: Path) -> str:
    return (run / "report.md").read_text(encoding="utf-8")


def only_id(run: Path) -> str:
    findings = report_of(run)["findings"]
    assert isinstance(findings, list)
    (finding,) = findings
    identifier: str = finding["id"]
    return identifier


def ack_the_finding(
    path: Path, capsys: pytest.CaptureFixture[str], *flags: str
) -> tuple[int, str, str]:
    _, run, _ = check(path, capsys)
    code = main(["ack", only_id(run), "--reason", "On purpose.", "-c", str(path), *flags])
    out, err = capsys.readouterr()
    return code, out, err


def expire(known_file: Path) -> None:
    text = known_file.read_text(encoding="utf-8")
    known_file.write_text(text.replace("2999-12-31", "2000-01-01"), encoding="utf-8")


def test_a_finding_seen_again_is_open_and_still_fails_the_check(
    capsys: pytest.CaptureFixture[str], config: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding())

    first_code, first, first_err = check(config, capsys)
    second_code, second, second_err = check(config, capsys)
    third_code, third, _ = check(config, capsys)

    assert (first_code, second_code, third_code) == (1, 1, 1)
    assert first_err.endswith("\n1 finding: 1 confirmed, 0 suspect.\n")
    assert second_err.endswith("\n1 finding: 1 confirmed, 0 suspect. 0 new.\n")
    assert "· New ·" in markdown_of(first)
    assert "Compared with" not in markdown_of(first)
    assert report_of(first)["compared_with"] is None
    assert "· Open for 2 runs ·" in markdown_of(second)
    assert "· Open for 3 runs ·" in markdown_of(third)
    assert f"\nCompared with run {first.name}.\n" in markdown_of(second)
    assert report_of(second)["compared_with"] == first.name
    assert counts(first)["new"] == 1
    assert counts(second)["new"] == 0


def test_a_new_finding_next_to_an_open_one_is_counted_as_new(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config: Path, fake_claude: FakeClaude
) -> None:
    (tmp_path / "docs" / "operations.md").write_text(
        OPERATIONS + "\nThe sitemap is at /map.xml.\n", encoding="utf-8"
    )
    answer_with(fake_claude, a_finding())
    check(config, capsys)
    other = a_finding()
    other["doc"] = {"file": "docs/operations.md", "line": 5, "quote": "at /map.xml"}
    answer_with(fake_claude, a_finding(), other)

    _, run, err = check(config, capsys)

    assert err.endswith("\n2 findings: 2 confirmed, 0 suspect. 1 new.\n")
    assert counts(run)["new"] == 1


def test_ack_records_the_finding_and_the_next_check_passes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    config: Path,
    known_file: Path,
    fake_claude: FakeClaude,
) -> None:
    answer_with(fake_claude, a_finding())

    code, out, err = ack_the_finding(config, capsys)

    assert (code, err) == (0, "")
    assert out.endswith(
        f": {TITLE}\nRecorded in {known_file}. "
        "Commit it with your docs, so the reason gets reviewed.\n"
    )
    assert 'reason = "On purpose."\n' in known_file.read_text(encoding="utf-8")

    code, run, err = check(config, capsys)

    assert code == 0
    assert err.endswith("\nNo findings. 1 acknowledged.\n")
    markdown = markdown_of(run)
    assert "**No findings.** 1 acknowledged.\n" in markdown
    assert "\n## Acknowledged\n" in markdown
    assert "Reason: On purpose.\n" in markdown
    assert "\n> nightly at 02:00\n" in markdown
    assert (counts(run)["acknowledged"], counts(run)["confirmed"]) == (1, 0)


def test_ack_runs_no_probe_and_no_model(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    write_config: Callable[[str], Path],
    config: Path,
    fake_claude: FakeClaude,
) -> None:
    probing = write_config(CONFIG.replace("echo '", "touch ran; echo '"))
    answer_with(fake_claude, a_finding())
    _, run, _ = check(probing, capsys)
    (tmp_path / "ran").unlink()
    calls = len(fake_claude.calls())

    assert main(["ack", only_id(run), "--reason", "r", "-c", str(probing)]) == 0

    assert not (tmp_path / "ran").exists()
    assert len(fake_claude.calls()) == calls


def test_the_model_is_never_told_what_is_known(
    capsys: pytest.CaptureFixture[str], config: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding())
    ack_the_finding(config, capsys)

    check(config, capsys)

    for call in fake_claude.calls():
        assert "On purpose." not in call["stdin"]
        assert not any("On purpose." in argument for argument in call["argv"])


def test_an_acknowledged_suspect_finding_is_acknowledged_too(
    capsys: pytest.CaptureFixture[str], config: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding(confidence="suspect"))
    assert ack_the_finding(config, capsys)[0] == 0

    code, run, err = check(config, capsys)

    assert code == 0
    assert err.endswith("\nNo findings. 1 acknowledged.\n")
    assert counts(run)["suspect"] == 0


def test_a_suspect_acknowledgement_ends_when_the_finding_is_confirmed(
    capsys: pytest.CaptureFixture[str], config: Path, known_file: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding(confidence="suspect"))
    assert ack_the_finding(config, capsys)[0] == 0
    answer_with(fake_claude, a_finding())

    code, run, _ = check(config, capsys)

    assert code == 1
    assert counts(run)["acknowledged"] == 0
    assert "was given when this was only suspect" in markdown_of(run)

    assert main(["ack", only_id(run), "--reason", "Known now.", "-c", str(config)]) == 0
    capsys.readouterr()
    assert known_file.read_text(encoding="utf-8").count("[[known]]\n") == 2
    assert check(config, capsys)[0] == 0


def test_an_until_in_the_future_keeps_the_acknowledgement_live(
    capsys: pytest.CaptureFixture[str], config: Path, known_file: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding())

    assert ack_the_finding(config, capsys, "--until", "2999-12-31")[0] == 0

    assert "until = 2999-12-31\n" in known_file.read_text(encoding="utf-8")
    code, run, _ = check(config, capsys)
    assert code == 0
    assert " until 2999-12-31 · " in markdown_of(run)


def test_an_expired_acknowledgement_fails_the_check_again_and_says_why(
    capsys: pytest.CaptureFixture[str], config: Path, known_file: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding())
    ack_the_finding(config, capsys, "--until", "2999-12-31")
    expire(known_file)

    code, run, _ = check(config, capsys)

    assert code == 1
    assert "\n## Confirmed\n" in markdown_of(run)
    assert "ran out on 2000-01-01, so it counts again. Its reason was: On purpose." in markdown_of(
        run
    )


def test_an_expired_acknowledgement_can_be_renewed(
    capsys: pytest.CaptureFixture[str], config: Path, known_file: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding())
    ack_the_finding(config, capsys, "--until", "2999-12-31")
    expire(known_file)
    _, run, _ = check(config, capsys)

    assert main(["ack", only_id(run), "--reason", "Still.", "-c", str(config)]) == 0
    capsys.readouterr()

    code, _, err = check(config, capsys)
    assert code == 0
    assert err.endswith("\nNo findings. 1 acknowledged.\n")


def test_changed_evidence_fails_the_check_again_and_says_why(
    capsys: pytest.CaptureFixture[str],
    write_config: Callable[[str], Path],
    config: Path,
    fake_claude: FakeClaude,
) -> None:
    answer_with(fake_claude, a_finding())
    ack_the_finding(config, capsys)
    later = write_config(CONFIG.replace("03:00:00", "04:00:00"))
    answer_with(fake_claude, a_finding(schedule="04:00:00"))

    code, run, _ = check(later, capsys)

    assert code == 1
    assert "what it rests on has changed, so this counts again" in markdown_of(run)
    assert counts(run)["no_longer_reported"] == 0

    assert main(["ack", only_id(run), "--reason", "Still.", "-c", str(later)]) == 0


def test_a_finding_the_model_stops_reporting_is_no_longer_reported(
    capsys: pytest.CaptureFixture[str], config: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding())
    _, first, _ = check(config, capsys)
    answer_with(fake_claude)

    code, run, err = check(config, capsys)

    assert code == 0
    assert err.endswith("\nNo findings. 1 no longer reported.\n")
    assert f"\n- `{only_id(first)}` in `docs/operations.md`: {TITLE}\n" in markdown_of(run)
    assert "\n## No longer reported\n" in markdown_of(run)
    assert "isn't proof" in " ".join(markdown_of(run).split())


def test_a_finding_the_model_misses_once_comes_back_as_new(
    capsys: pytest.CaptureFixture[str], config: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding())
    check(config, capsys)
    answer_with(fake_claude)
    check(config, capsys)
    answer_with(fake_claude, a_finding())

    _, run, _ = check(config, capsys)

    assert counts(run)["new"] == 1


def test_ack_accepts_a_finding_listed_as_no_longer_reported(
    capsys: pytest.CaptureFixture[str], config: Path, known_file: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding())
    _, first, _ = check(config, capsys)
    answer_with(fake_claude)
    _, second, _ = check(config, capsys)
    assert counts(second)["no_longer_reported"] == 1

    assert main(["ack", only_id(first), "--reason", "Comes and goes.", "-c", str(config)]) == 0
    capsys.readouterr()

    assert "Comes and goes." in known_file.read_text(encoding="utf-8")
    answer_with(fake_claude, a_finding())
    code, _, err = check(config, capsys)
    assert code == 0
    assert err.endswith("\nNo findings. 1 acknowledged.\n")


def test_an_acknowledgement_with_nothing_left_to_match_is_listed_as_acknowledged(
    capsys: pytest.CaptureFixture[str], config: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding())
    ack_the_finding(config, capsys)
    answer_with(fake_claude)

    code, run, _ = check(config, capsys)

    assert code == 0
    assert f": {TITLE} (acknowledged)\n" in markdown_of(run)
    assert counts(run)["no_longer_reported"] == 1


def test_an_expired_acknowledgement_with_nothing_left_to_match_says_how_to_clear_it(
    capsys: pytest.CaptureFixture[str], config: Path, known_file: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding())
    ack_the_finding(config, capsys, "--until", "2999-12-31")
    expire(known_file)
    answer_with(fake_claude)

    _, run, _ = check(config, capsys)

    assert (
        f": {TITLE} (its acknowledgement ran out; delete its entry to stop listing it)\n"
        in markdown_of(run)
    )


def test_a_failed_probe_means_not_rechecked_and_the_count_survives_it(
    capsys: pytest.CaptureFixture[str],
    write_config: Callable[[str], Path],
    config: Path,
    fake_claude: FakeClaude,
) -> None:
    answer_with(fake_claude, a_finding())
    check(config, capsys)
    broken = write_config(CONFIG.replace("echo 'restic-backup.timer *-*-* 03:00:00'", "exit 1"))
    answer_with(fake_claude)

    code, run, err = check(broken, capsys)

    assert code == 2
    assert err.endswith("\nNo findings. 1 not rechecked. 1 probe failed.\n")
    assert "\n## Not rechecked\n" in markdown_of(run)
    assert counts(run)["no_longer_reported"] == 0

    fixed = write_config(CONFIG)
    answer_with(fake_claude, a_finding())
    _, later, _ = check(fixed, capsys)

    assert "· Open for 2 runs ·" in markdown_of(later)


def test_a_finding_whose_doc_left_the_config_is_listed_once(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    write_config: Callable[[str], Path],
    config: Path,
    fake_claude: FakeClaude,
) -> None:
    answer_with(fake_claude, a_finding())
    check(config, capsys)
    (tmp_path / "other.md").write_text("# Other\n", encoding="utf-8")
    moved = write_config(CONFIG.replace('"docs/*.md"', '"other.md"'))
    answer_with(fake_claude)

    _, once, once_err = check(moved, capsys)
    _, after, after_err = check(moved, capsys)

    assert once_err.endswith("\nNo findings. 1 not rechecked.\n")
    assert "(left the config, so it's listed only this once)" in markdown_of(once)
    assert after_err.endswith("\nNo findings.\n")
    assert "Not rechecked" not in markdown_of(after)


def test_a_quote_that_fails_verification_means_not_rechecked(
    capsys: pytest.CaptureFixture[str], config: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding())
    check(config, capsys)
    bad_quote = a_finding()
    bad_quote["doc"] = {"file": "docs/operations.md", "line": 3, "quote": "nightly at 01:00"}
    answer_with(fake_claude, bad_quote)

    code, run, err = check(config, capsys)

    assert code == 0
    assert err.endswith("\nNo findings. 1 not rechecked. 1 finding dropped.\n")
    assert counts(run)["no_longer_reported"] == 0


def test_an_acknowledgement_can_end_today(
    capsys: pytest.CaptureFixture[str], config: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding())

    assert ack_the_finding(config, capsys, "--until", date.today().isoformat())[0] == 0

    assert check(config, capsys)[0] == 0


def test_a_config_keeps_its_own_known_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config: Path, fake_claude: FakeClaude
) -> None:
    other = tmp_path / "ops.toml"
    other.write_text(CONFIG, encoding="utf-8")
    answer_with(fake_claude, a_finding())

    assert ack_the_finding(other, capsys)[0] == 0

    assert (tmp_path / "ops-known.toml").exists()
    assert not (tmp_path / "doc-truth-known.toml").exists()


def test_runs_of_another_config_in_a_shared_folder_do_not_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config: Path, fake_claude: FakeClaude
) -> None:
    other = tmp_path / "ops.toml"
    other.write_text(CONFIG, encoding="utf-8")
    shared = str(tmp_path / "shared")
    answer_with(fake_claude, a_finding())
    assert main(["check", "-c", str(other), "-o", shared]) == 1
    capsys.readouterr()

    assert main(["check", "-c", str(config), "-o", shared]) == 1

    out, _ = capsys.readouterr()
    assert "· New ·" in markdown_of(Path(out.removesuffix("\n")))


def test_ack_reads_the_report_from_the_output_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config: Path, fake_claude: FakeClaude
) -> None:
    shared = str(tmp_path / "shared")
    answer_with(fake_claude, a_finding())
    main(["check", "-c", str(config), "-o", shared])
    identifier = only_id(Path(capsys.readouterr().out.removesuffix("\n")))

    assert main(["ack", identifier, "--reason", "r", "-c", str(config), "-o", shared]) == 0


def test_an_unreadable_previous_report_warns_and_everything_is_new(
    capsys: pytest.CaptureFixture[str], config: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding())
    _, first, _ = check(config, capsys)
    (first / "report.json").write_text("not json", encoding="utf-8")

    code, run, err = check(config, capsys)

    assert code == 1
    assert err.startswith(
        f"doc-truth: warning: cannot read {first / 'report.json'}: it isn't valid JSON; "
        "every finding counts as new this run\n"
    )
    assert "· New ·" in markdown_of(run)


def test_an_unreadable_previous_report_stops_ack(
    capsys: pytest.CaptureFixture[str], config: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding())
    _, first, _ = check(config, capsys)
    (first / "report.json").write_text("not json", encoding="utf-8")

    assert main(["ack", "x", "--reason", "r", "-c", str(config)]) == 2

    assert capsys.readouterr().err.startswith("doc-truth: error: cannot read ")


def test_a_report_from_before_this_format_means_everything_is_new(
    capsys: pytest.CaptureFixture[str], config: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding())
    _, first, _ = check(config, capsys)
    old = {**report_of(first), "format": 1}
    (first / "report.json").write_text(json.dumps(old), encoding="utf-8")

    _, run, err = check(config, capsys)

    assert "warning" not in err
    assert "· New ·" in markdown_of(run)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--reason", "   "], "--reason must not be empty"),
        (["--reason", "r", "--until", "2000-01-01"], "--until 2000-01-01 is in the past"),
    ],
)
def test_ack_refuses_a_bad_reason_or_date(
    capsys: pytest.CaptureFixture[str],
    config: Path,
    known_file: Path,
    fake_claude: FakeClaude,
    arguments: list[str],
    message: str,
) -> None:
    answer_with(fake_claude, a_finding())
    _, run, _ = check(config, capsys)

    assert main(["ack", only_id(run), *arguments, "-c", str(config)]) == 2

    assert capsys.readouterr() == ("", f"doc-truth: error: {message}\n")
    assert not known_file.exists()


def test_a_reason_is_written_on_one_line(
    capsys: pytest.CaptureFixture[str], config: Path, known_file: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding())
    _, run, _ = check(config, capsys)

    assert main(["ack", only_id(run), "--reason", "  two\n  lines ", "-c", str(config)]) == 0

    assert 'reason = "two lines"\n' in known_file.read_text(encoding="utf-8")


def test_ack_refuses_a_date_it_cannot_read(
    capsys: pytest.CaptureFixture[str], config: Path
) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["ack", "x", "--reason", "r", "--until", "soon", "-c", str(config)])

    assert stopped.value.code == 2
    assert "--until" in capsys.readouterr().err


def test_ack_needs_a_reason(capsys: pytest.CaptureFixture[str], config: Path) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["ack", "x", "-c", str(config)])

    assert stopped.value.code == 2
    assert "--reason" in capsys.readouterr().err


def test_ack_with_no_report_says_to_run_check(
    capsys: pytest.CaptureFixture[str], config: Path, tmp_path: Path
) -> None:
    assert main(["ack", "x", "--reason", "r", "-c", str(config)]) == 2

    assert capsys.readouterr() == (
        "",
        "doc-truth: error: there is no report with finding IDs for this config in "
        f"{tmp_path / '.doc-truth' / 'runs'}; "
        "run doc-truth check, or give ack the --output-dir that check used\n",
    )


def test_ack_with_an_unknown_id_lists_the_ones_it_has(
    capsys: pytest.CaptureFixture[str], config: Path, known_file: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding())
    _, run, _ = check(config, capsys)

    assert main(["ack", "nope", "--reason", "r", "-c", str(config)]) == 2

    assert capsys.readouterr() == (
        "",
        f"doc-truth: error: nope can't be acknowledged from run {run.name} ({only_id(run)})\n",
    )
    assert not known_file.exists()


def test_ack_with_an_unknown_id_says_when_the_report_has_no_findings(
    capsys: pytest.CaptureFixture[str], config: Path, fake_claude: FakeClaude
) -> None:
    _, run, _ = check(config, capsys)

    assert main(["ack", "nope", "--reason", "r", "-c", str(config)]) == 2

    assert capsys.readouterr().err == (
        f"doc-truth: error: nope can't be acknowledged from run {run.name} (it has no findings)\n"
    )


def test_acknowledging_twice_is_refused(
    capsys: pytest.CaptureFixture[str], config: Path, known_file: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding())
    _, run, _ = check(config, capsys)
    identifier = only_id(run)
    assert main(["ack", identifier, "--reason", "r", "-c", str(config)]) == 0
    capsys.readouterr()

    assert main(["ack", identifier, "--reason", "again", "-c", str(config)]) == 2

    assert capsys.readouterr().err == (
        f"doc-truth: error: {identifier} is already acknowledged; "
        f"edit its entry in {known_file} to change it\n"
    )
    assert known_file.read_text(encoding="utf-8").count("[[known]]\n") == 1


def test_an_invalid_known_file_stops_check_before_any_probe(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    write_config: Callable[[str], Path],
    known_file: Path,
    fake_claude: FakeClaude,
) -> None:
    (tmp_path / "ops.md").write_text("# Ops\n", encoding="utf-8")
    probing = write_config(
        '[[docs]]\npath = "ops.md"\n[[probes]]\nname = "x"\ncommand = "touch ran"\n'
    )
    known_file.write_text("[[known]]\nid = 3\n", encoding="utf-8")

    assert main(["check", "-c", str(probing)]) == 2

    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith(f"doc-truth: error: {known_file}: ")
    assert "[[known]] #1: id must be a string, found an integer" in err
    assert not (tmp_path / "ran").exists()
    assert fake_claude.calls() == []


def test_an_invalid_known_file_fails_validate_and_ack(
    capsys: pytest.CaptureFixture[str], config: Path, known_file: Path
) -> None:
    known_file.write_text("[[known]]\nid = 3\n", encoding="utf-8")

    assert main(["validate", "-c", str(config)]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "[[known]] #1" in err
    assert main(["ack", "x", "--reason", "r", "-c", str(config)]) == 2
    assert "[[known]] #1" in capsys.readouterr().err


def test_validate_lists_known_findings(
    capsys: pytest.CaptureFixture[str], config: Path, fake_claude: FakeClaude
) -> None:
    answer_with(fake_claude, a_finding())
    _, run, _ = check(config, capsys)
    identifier = only_id(run)
    main(["ack", identifier, "--reason", "r", "-c", str(config)])
    capsys.readouterr()

    assert main(["validate", "-c", str(config)]) == 0

    assert capsys.readouterr().out.endswith(f"\nKnown findings (1):\n  {identifier}  {TITLE}\n")


def test_validate_says_nothing_about_known_findings_when_there_are_none(
    capsys: pytest.CaptureFixture[str], config: Path
) -> None:
    assert main(["validate", "-c", str(config)]) == 0

    assert "Known findings" not in capsys.readouterr().out
