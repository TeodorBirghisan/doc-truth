import os
import pwd
import selectors
import shutil
import signal
import socket
import subprocess
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from doc_truth.config import Config, Probe
from doc_truth.evidence import Evidence, ProbeResult, format_size

LOCALE = "C.UTF-8"
REMOVED_VARIABLES = ("LANGUAGE", "BASH_ENV")
MAX_STDOUT = 1024 * 1024
MAX_STDERR = 64 * 1024
STOP_GRACE = 2.0
DRAIN_TIME = 1.0

_POLL_INTERVAL = 0.05
_CHUNK = 65536


class CollectError(Exception):
    pass


@dataclass(slots=True)
class _Stream:
    limit: int
    data: bytearray = field(default_factory=bytearray)
    truncated: bool = False

    def take(self, chunk: bytes) -> None:
        room = self.limit - len(self.data)
        self.data += chunk[:room]
        if len(chunk) > room:
            self.truncated = True

    def text(self) -> str:
        return self.data.decode("utf-8", errors="backslashreplace")


def collect(
    config: Config,
    *,
    tool_version: str,
    on_result: Callable[[ProbeResult], None] | None = None,
) -> Evidence:
    environment = probe_environment(os.environ)
    shell = find_shell(environment)
    started_at = datetime.now(UTC)
    local = started_at.astimezone()
    results: list[ProbeResult] = []
    for probe in config.probes:
        result = run_probe(probe, shell=shell, cwd=config.base_dir, environment=environment)
        results.append(result)
        if on_result is not None:
            on_result(result)
    return Evidence(
        tool_version=tool_version,
        host=socket.gethostname(),
        user=_user_name(),
        timezone=local.strftime("%Z"),
        utc_offset=local.strftime("%:z"),
        started_at=started_at,
        finished_at=datetime.now(UTC),
        config_path=config.base_dir / config.path.name,
        results=tuple(results),
    )


def probe_environment(inherited: Mapping[str, str]) -> dict[str, str]:
    environment = {
        name: value for name, value in inherited.items() if name not in REMOVED_VARIABLES
    }
    environment["LC_ALL"] = LOCALE
    return environment


def find_shell(environment: Mapping[str, str]) -> str:
    shell = shutil.which("bash", path=environment.get("PATH", os.defpath))
    if shell is None:
        raise CollectError(
            "bash was not found on PATH; doc-truth runs every probe with bash -o pipefail, "
            "so that a failure anywhere in a pipeline fails the probe"
        )
    return shell


def run_probe(
    probe: Probe, *, shell: str, cwd: Path, environment: Mapping[str, str]
) -> ProbeResult:
    started = time.monotonic()
    stdout = _Stream(MAX_STDOUT)
    stderr = _Stream(MAX_STDERR)
    try:
        process = subprocess.Popen(
            [shell, "-o", "pipefail", "-c", probe.command],
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as error:
        return _result(
            probe,
            stdout,
            stderr,
            duration=time.monotonic() - started,
            returncode=None,
            timed_out=False,
            failure=f"could not start: {error.strerror or error}",
        )
    try:
        timed_out = _read_until_done(process, stdout, stderr, deadline=started + probe.timeout)
    finally:
        _stop_group(process)
    return _result(
        probe,
        stdout,
        stderr,
        duration=time.monotonic() - started,
        returncode=process.returncode,
        timed_out=timed_out,
    )


def _read_until_done(
    process: subprocess.Popen[bytes], stdout: _Stream, stderr: _Stream, *, deadline: float
) -> bool:
    assert process.stdout is not None and process.stderr is not None
    streams = {process.stdout.fileno(): stdout, process.stderr.fileno(): stderr}
    timed_out = False
    stopped_at: float | None = None
    try:
        with selectors.DefaultSelector() as selector:
            for fd in streams:
                selector.register(fd, selectors.EVENT_READ)
            while selector.get_map():
                now = time.monotonic()
                if stopped_at is None:
                    # Once the shell has exited, whatever is left in its process group was
                    # started in the background and would keep the pipes open.
                    if process.poll() is not None or now >= deadline:
                        timed_out = process.returncode is None
                        _stop_group(process)
                        stopped_at = now = time.monotonic()
                elif now >= stopped_at + DRAIN_TIME:
                    break
                until = deadline if stopped_at is None else stopped_at + DRAIN_TIME
                for key, _ in selector.select(max(0.0, min(until - now, _POLL_INTERVAL))):
                    chunk = os.read(key.fd, _CHUNK)
                    if not chunk:
                        selector.unregister(key.fd)
                        continue
                    stream = streams[key.fd]
                    stream.take(chunk)
                    if stream is stdout and stdout.truncated:
                        selector.unregister(key.fd)
                        if stopped_at is None:
                            _stop_group(process)
                            stopped_at = time.monotonic()
        if stopped_at is None:
            try:
                process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
    finally:
        process.stdout.close()
        process.stderr.close()
    return timed_out


def _stop_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError, PermissionError:
        process.poll()
        return
    give_up = time.monotonic() + STOP_GRACE
    while time.monotonic() < give_up:
        process.poll()
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError, PermissionError:
            return
        time.sleep(0.02)
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
    # A process stuck in uninterruptible sleep, on a dead network mount for example,
    # ignores even SIGKILL; leave it rather than hang the whole run.
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=STOP_GRACE)


def _result(
    probe: Probe,
    stdout: _Stream,
    stderr: _Stream,
    *,
    duration: float,
    returncode: int | None,
    timed_out: bool,
    failure: str | None = None,
) -> ProbeResult:
    exit_code = returncode if returncode is not None and returncode >= 0 else None
    signal_name = _signal_name(-returncode) if returncode is not None and returncode < 0 else None
    if failure is None:
        failure = _failure(probe, stdout, exit_code, signal_name, timed_out=timed_out)
    return ProbeResult(
        probe=probe,
        stdout=stdout.text(),
        stderr=stderr.text(),
        exit_code=exit_code,
        signal=signal_name,
        duration=duration,
        timed_out=timed_out,
        stdout_truncated=stdout.truncated,
        stderr_truncated=stderr.truncated,
        failure=failure,
    )


def _failure(
    probe: Probe,
    stdout: _Stream,
    exit_code: int | None,
    signal_name: str | None,
    *,
    timed_out: bool,
) -> str | None:
    if timed_out:
        return f"timed out after {probe.timeout:g}s"
    if stdout.truncated:
        return f"printed more than {format_size(MAX_STDOUT)} on standard output"
    if signal_name is not None:
        return f"ended by {signal_name}"
    if exit_code not in probe.success_exit_codes:
        codes = ", ".join(str(code) for code in sorted(probe.success_exit_codes))
        return f"exit code {exit_code} is not in success-exit-codes [{codes}]"
    return None


def _signal_name(number: int) -> str:
    try:
        return signal.Signals(number).name
    except ValueError:
        return f"signal {number}"


def _user_name() -> str:
    uid = os.geteuid()
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)
