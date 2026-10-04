import os
import pwd
import shutil
import signal
import socket
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

from doc_truth import collect as collect_module
from doc_truth.collect import (
    LOCALE,
    CollectError,
    collect,
    find_shell,
    probe_environment,
    run_probe,
)
from doc_truth.config import Probe, load_config
from doc_truth.evidence import ProbeResult

SINGLE_PROBE = """
[[docs]]
path = "a.md"

[[probes]]
name = "x"
command = "true"
"""


def make_probe(
    command: str, *, timeout: float = 10, success_exit_codes: frozenset[int] = frozenset({0})
) -> Probe:
    return Probe(
        name="probe",
        command=command,
        timeout=timeout,
        success_exit_codes=success_exit_codes,
        notes=None,
    )


@pytest.fixture
def run(tmp_path: Path) -> Callable[..., ProbeResult]:
    environment = probe_environment(os.environ)
    shell = find_shell(environment)

    def run_command(
        command: str,
        *,
        timeout: float = 10,
        success_exit_codes: frozenset[int] = frozenset({0}),
    ) -> ProbeResult:
        probe = make_probe(command, timeout=timeout, success_exit_codes=success_exit_codes)
        return run_probe(probe, shell=shell, cwd=tmp_path, environment=environment)

    return run_command


@pytest.fixture
def quick_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(collect_module, "STOP_GRACE", 0.2)
    monkeypatch.setattr(collect_module, "DRAIN_TIME", 0.2)


def alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        return False
    return state != "Z"


def gone(pid: int, *, within: float = 3.0) -> bool:
    give_up = time.monotonic() + within
    while alive(pid):
        if time.monotonic() > give_up:
            return False
        time.sleep(0.02)
    return True


def test_a_successful_probe_records_its_output(run: Callable[..., ProbeResult]) -> None:
    result = run("echo out; echo err >&2")

    assert result.failure is None
    assert not result.failed
    assert (result.stdout, result.stderr) == ("out\n", "err\n")
    assert (result.exit_code, result.signal) == (0, None)
    assert not (result.timed_out or result.stdout_truncated or result.stderr_truncated)
    assert 0 <= result.duration < 5


def test_an_exit_code_outside_success_exit_codes_fails(run: Callable[..., ProbeResult]) -> None:
    result = run("exit 4", success_exit_codes=frozenset({8, 1}))

    assert result.exit_code == 4
    assert result.failure == "exit code 4 is not in success-exit-codes [1, 8]"
    assert result.failed


def test_an_exit_code_in_success_exit_codes_succeeds(run: Callable[..., ProbeResult]) -> None:
    result = run("echo inactive; exit 3", success_exit_codes=frozenset({0, 3}))

    assert (result.exit_code, result.failure, result.stdout) == (3, None, "inactive\n")


def test_a_failure_anywhere_in_a_pipeline_fails_the_probe(
    run: Callable[..., ProbeResult],
) -> None:
    result = run("false | cat")

    assert result.failure == "exit code 1 is not in success-exit-codes [0]"


def test_a_timeout_stops_the_whole_process_group(run: Callable[..., ProbeResult]) -> None:
    result = run("sleep 30 & echo $!; sleep 30", timeout=0.3)

    assert result.timed_out
    assert result.failure == "timed out after 0.3s"
    assert result.duration < 1.5
    assert gone(int(result.stdout))


def test_a_timed_out_probe_gets_sigterm_first(run: Callable[..., ProbeResult]) -> None:
    result = run("trap 'echo cleaning up; exit 0' TERM; sleep 30 & wait", timeout=0.3)

    assert result.timed_out
    assert result.stdout == "cleaning up\n"


def test_a_probe_that_ignores_sigterm_is_killed(
    run: Callable[..., ProbeResult], quick_stop: None
) -> None:
    result = run("trap '' TERM; sleep 30 & echo $!; sleep 30", timeout=0.3)

    assert result.timed_out
    assert result.signal == "SIGKILL"
    assert result.failure == "timed out after 0.3s"
    assert result.duration < 3
    assert gone(int(result.stdout))


def test_closing_the_output_does_not_end_the_wait(
    run: Callable[..., ProbeResult], quick_stop: None
) -> None:
    result = run("exec >&- 2>&-; sleep 30", timeout=1.0)

    assert result.timed_out
    assert result.failure == "timed out after 1s"
    assert result.duration < 3


def test_background_processes_are_stopped_when_the_shell_exits(
    run: Callable[..., ProbeResult],
) -> None:
    result = run("sleep 30 & echo $!", timeout=10)

    assert result.failure is None
    assert not result.timed_out
    assert result.duration < 3
    assert gone(int(result.stdout))


@pytest.mark.skipif(shutil.which("setsid") is None, reason="needs setsid")
def test_a_process_that_leaves_the_group_cannot_hang_the_run(
    run: Callable[..., ProbeResult], quick_stop: None
) -> None:
    result = run("setsid sleep 30 & echo $!", timeout=10)
    escaped = int(result.stdout)
    try:
        assert result.failure is None
        assert result.duration < 3
    finally:
        os.kill(escaped, signal.SIGKILL)


def test_output_over_the_limit_fails_the_probe_and_stops_it(
    run: Callable[..., ProbeResult], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(collect_module, "MAX_STDOUT", 1000)

    result = run("yes", timeout=10)

    assert result.stdout_truncated
    assert result.stdout == "y\n" * 500
    assert result.failure == "printed more than 1000 bytes on standard output"
    assert not result.timed_out
    assert result.duration < 5


def test_standard_output_is_capped_at_one_mebibyte(run: Callable[..., ProbeResult]) -> None:
    result = run("head -c 2000000 /dev/zero | tr '\\0' a")

    assert result.stdout == "a" * 1024 * 1024
    assert result.failure == "printed more than 1 MiB on standard output"


def test_output_that_fits_the_limit_exactly_is_kept_whole(
    run: Callable[..., ProbeResult], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(collect_module, "MAX_STDOUT", 1000)

    result = run("head -c 1000 /dev/zero | tr '\\0' a")

    assert (result.failure, result.stdout_truncated) == (None, False)
    assert result.stdout == "a" * 1000


def test_standard_error_over_the_limit_is_cut_off_without_failing(
    run: Callable[..., ProbeResult], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(collect_module, "MAX_STDERR", 100)

    result = run("head -c 5000 /dev/zero | tr '\\0' e >&2; echo done")

    assert result.failure is None
    assert result.stderr == "e" * 100
    assert result.stderr_truncated
    assert result.stdout == "done\n"


def test_probes_read_nothing_from_standard_input(run: Callable[..., ProbeResult]) -> None:
    read_end, write_end = os.pipe()
    saved_stdin = os.dup(0)
    os.dup2(read_end, 0)
    try:
        result = run("readlink /proc/self/fd/0; cat; echo end", timeout=2)
    finally:
        os.dup2(saved_stdin, 0)
        for fd in (saved_stdin, read_end, write_end):
            os.close(fd)

    assert (result.failure, result.stdout) == (None, "/dev/null\nend\n")


def test_probes_run_in_the_config_directory(
    run: Callable[..., ProbeResult], tmp_path: Path
) -> None:
    assert run("pwd -P").stdout == f"{tmp_path.resolve()}\n"


def test_probes_inherit_the_environment_with_a_fixed_locale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    startup = tmp_path / "startup.sh"
    startup.write_text("echo sourced\n", encoding="utf-8")
    monkeypatch.setenv("LC_ALL", "fr_FR.UTF-8")
    monkeypatch.setenv("LANGUAGE", "fr")
    monkeypatch.setenv("BASH_ENV", str(startup))
    monkeypatch.setenv("TZ", "Europe/Bucharest")
    monkeypatch.setenv("DOC_TRUTH_TEST", "kept")
    environment = probe_environment(os.environ)
    probe = make_probe('echo "$LC_ALL|${LANGUAGE-unset}|${BASH_ENV-unset}|$TZ|$DOC_TRUTH_TEST"')

    result = run_probe(probe, shell=find_shell(environment), cwd=tmp_path, environment=environment)

    assert result.stdout == f"{LOCALE}|unset|unset|Europe/Bucharest|kept\n"


def test_the_probe_environment_leaves_the_original_alone() -> None:
    inherited = {"PATH": "/usr/bin", "LANGUAGE": "fr", "BASH_ENV": "/x", "LC_ALL": "de_DE"}

    environment = probe_environment(inherited)

    assert environment == {"PATH": "/usr/bin", "LC_ALL": LOCALE}
    assert inherited == {"PATH": "/usr/bin", "LANGUAGE": "fr", "BASH_ENV": "/x", "LC_ALL": "de_DE"}


def test_a_probe_ended_by_a_signal_fails(run: Callable[..., ProbeResult]) -> None:
    result = run("echo partial; kill -KILL $$")

    assert (result.exit_code, result.signal) == (None, "SIGKILL")
    assert result.failure == "ended by SIGKILL"
    assert result.stdout == "partial\n"


def test_a_signal_without_a_name_is_reported_by_number(run: Callable[..., ProbeResult]) -> None:
    number = signal.SIGRTMIN + 1

    result = run(f"kill -{number} $$")

    assert result.signal == f"signal {number}"
    assert result.failure == f"ended by signal {number}"


def test_a_probe_that_cannot_start_fails(tmp_path: Path) -> None:
    result = run_probe(
        make_probe("true"),
        shell=str(tmp_path / "no-such-shell"),
        cwd=tmp_path,
        environment=probe_environment(os.environ),
    )

    assert result.failure == "could not start: No such file or directory"
    assert (result.exit_code, result.signal, result.stdout, result.stderr) == (None, None, "", "")
    assert not result.timed_out


def test_invalid_utf8_is_escaped_rather_than_dropped(run: Callable[..., ProbeResult]) -> None:
    result = run("printf 'caf\\351 caf\\303\\251\\n'")

    assert result.stdout == "caf\\xe9 café\n"


def test_find_shell_uses_the_probe_path(tmp_path: Path) -> None:
    bash = tmp_path / "bash"
    bash.write_text("#!/bin/sh\n", encoding="utf-8")
    bash.chmod(0o755)

    assert find_shell({"PATH": str(tmp_path)}) == str(bash)


def test_find_shell_fails_without_bash(tmp_path: Path) -> None:
    with pytest.raises(CollectError, match=r"^bash was not found on PATH; .* bash -o pipefail"):
        find_shell({"PATH": str(tmp_path)})


def test_collect_runs_every_probe_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_config: Callable[[str], Path]
) -> None:
    write_config(
        """
        [[docs]]
        path = "missing.md"

        [[probes]]
        name = "first"
        command = 'pwd -P; echo "$LC_ALL"; sleep 0.01'

        [[probes]]
        name = "second"
        command = "exit 1"
        """
    )
    monkeypatch.chdir(tmp_path)
    config = load_config(Path("doc-truth.toml"))
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")
    reported: list[str] = []
    before = datetime.now().astimezone()

    evidence = collect(
        config, tool_version="1.2.3", on_result=lambda result: reported.append(result.probe.name)
    )

    assert reported == ["first", "second"]
    assert [result.probe.name for result in evidence.results] == ["first", "second"]
    assert [result.failed for result in evidence.results] == [False, True]
    assert evidence.results[0].stdout == f"{tmp_path.resolve()}\n{LOCALE}\n"
    assert evidence.tool_version == "1.2.3"
    assert evidence.host == socket.gethostname()
    assert evidence.user == pwd.getpwuid(os.geteuid()).pw_name
    assert evidence.timezone == before.strftime("%Z")
    assert evidence.utc_offset == before.strftime("%:z")
    assert before <= evidence.started_at < evidence.finished_at
    assert evidence.started_at.utcoffset() is not None
    assert evidence.config_path == tmp_path / "doc-truth.toml"


def test_collect_needs_bash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_config: Callable[[str], Path]
) -> None:
    config = load_config(write_config(SINGLE_PROBE))
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(CollectError):
        collect(config, tool_version="1")


def test_collect_names_a_user_without_a_passwd_entry_by_uid(
    monkeypatch: pytest.MonkeyPatch, write_config: Callable[[str], Path]
) -> None:
    def missing(uid: int) -> object:
        raise KeyError(uid)

    monkeypatch.setattr(pwd, "getpwuid", missing)
    config = load_config(write_config(SINGLE_PROBE))

    assert collect(config, tool_version="1").user == str(os.geteuid())
