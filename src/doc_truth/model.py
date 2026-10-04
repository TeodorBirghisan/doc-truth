import json
import os
import selectors
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import IO

from doc_truth.collect import MAX_STDERR, stop_process_group
from doc_truth.config import ModelSettings
from doc_truth.evidence import format_size
from doc_truth.prompt import Prompt

CLAUDE = "claude"
CLAUDE_ARGUMENTS = (
    "--print",
    "--safe-mode",
    "--tools=",
    "--strict-mcp-config",
    "--disable-slash-commands",
    "--no-session-persistence",
    "--output-format=stream-json",
    "--verbose",
)
MAX_OUTPUT = 16 * 1024 * 1024
PROMPT_TOO_LONG = "Prompt is too long"

_CHUNK = 65536


class ModelError(Exception):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Answer:
    text: str
    models: tuple[str, ...]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration: float


def ask_claude(prompt: Prompt, settings: ModelSettings) -> Answer:
    executable = shutil.which(CLAUDE)
    if executable is None:
        raise ModelError(
            "the claude command was not found on PATH; comparing docs with evidence needs "
            "Claude Code installed and logged in"
        )
    command = [
        executable,
        *CLAUDE_ARGUMENTS,
        f"--model={settings.name}",
        f"--system-prompt={prompt.system}",
    ]
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="doc-truth-") as empty_dir:
        try:
            process = subprocess.Popen(
                command,
                cwd=empty_dir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as error:
            raise ModelError(f"could not start claude: {error.strerror or error}") from None
        try:
            events, stderr = _exchange(process, prompt.user.encode(), timeout=settings.timeout)
        finally:
            stop_process_group(process)
    return _answer(events, process.returncode, stderr, duration=time.monotonic() - started)


def _exchange(
    process: subprocess.Popen[bytes], prompt: bytes, *, timeout: float
) -> tuple[list[Mapping[str, object]], str]:
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    deadline = time.monotonic() + timeout
    writer = threading.Thread(target=_write_and_close, args=(process.stdin, prompt), daemon=True)
    writer.start()
    events: list[Mapping[str, object]] = []
    pending = bytearray()
    received = 0
    stderr = bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            selector.register(process.stderr, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ModelError(_timed_out(timeout))
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fd, _CHUNK)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    elif key.fileobj is process.stderr:
                        stderr += chunk[: max(0, MAX_STDERR - len(stderr))]
                    else:
                        received += len(chunk)
                        if received > MAX_OUTPUT:
                            raise ModelError(
                                f"claude printed more than {format_size(MAX_OUTPUT)}; stopped it"
                            )
                        pending += chunk
                        *lines, rest = pending.split(b"\n")
                        pending = bytearray(rest)
                        for line in lines:
                            _take(line, events)
        _take(pending, events)
        try:
            process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise ModelError(_timed_out(timeout)) from None
    finally:
        process.stdout.close()
        process.stderr.close()
    return events, stderr.decode("utf-8", errors="replace")


def _write_and_close(pipe: IO[bytes], data: bytes) -> None:
    # claude may exit before reading everything, for example when it isn't logged in;
    # its exit code and message then say why, so a broken pipe here isn't the error to report.
    with suppress(OSError):
        pipe.write(data)
    with suppress(OSError):
        pipe.close()


def _take(line: bytes | bytearray, events: list[Mapping[str, object]]) -> None:
    if not line.strip():
        return
    try:
        event = json.loads(line)
    except ValueError:
        raise ModelError(f"claude printed a line that isn't JSON: {_excerpt(line)}") from None
    if not isinstance(event, dict):
        raise ModelError(f"claude printed JSON that isn't an event: {_excerpt(line)}")
    _refuse_tools(event, tools_checked=any(_is_init(seen) for seen in events))
    events.append(event)


def _refuse_tools(event: Mapping[str, object], *, tools_checked: bool) -> None:
    if _is_init(event):
        tools = event.get("tools")
        servers = event.get("mcp_servers")
        if tools != [] or servers != []:
            raise ModelError(
                "claude offered the model tools, so doc-truth stopped it before it could use "
                f"them (tools: {_names(tools)}; MCP servers: {_names(servers)})"
            )
        return
    if event.get("type") not in ("assistant", "result"):
        return
    if not tools_checked:
        raise ModelError(
            "claude answered without first listing the model's tools, so doc-truth could not "
            "check that it has none"
        )
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    for block in content if isinstance(content, list) else ():
        kind = block.get("type") if isinstance(block, dict) else None
        if isinstance(kind, str) and kind.endswith("tool_use"):
            name = block.get("name") if isinstance(block, dict) else None
            raise ModelError(f"the model tried to use a tool ({_names([name])}); stopped it")


def _answer(
    events: Sequence[Mapping[str, object]], returncode: int | None, stderr: str, *, duration: float
) -> Answer:
    results = [event for event in events if event.get("type") == "result"]
    if not results:
        raise ModelError(f"claude exited with code {returncode} without an answer{_detail(stderr)}")
    result = results[-1]
    text = result.get("result")
    if result.get("is_error") is not False or returncode != 0 or not isinstance(text, str):
        message = text if isinstance(text, str) and text.strip() else f"exit code {returncode}"
        if message.startswith(PROMPT_TOO_LONG):
            message += (
                ": the docs and evidence don't fit in the model's context window; "
                "check fewer docs at a time"
            )
        raise ModelError(f"claude failed: {message}{_detail(stderr)}")
    usage = result.get("modelUsage")
    models = usage if isinstance(usage, dict) else {}
    return Answer(
        text=text,
        models=tuple(models),
        input_tokens=sum(
            _count(model, key)
            for model in models.values()
            for key in ("inputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")
        ),
        output_tokens=sum(_count(model, "outputTokens") for model in models.values()),
        cost_usd=_number(result.get("total_cost_usd")),
        duration=duration,
    )


def _is_init(event: Mapping[str, object]) -> bool:
    return event.get("type") == "system" and event.get("subtype") == "init"


def _count(model: object, key: str) -> int:
    return int(_number(model.get(key))) if isinstance(model, dict) else 0


def _number(value: object) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _names(value: object) -> str:
    if not isinstance(value, list):
        return "not listed"
    names = [item.get("name") if isinstance(item, dict) else item for item in value]
    return ", ".join(str(name) for name in names) or "none"


def _timed_out(timeout: float) -> str:
    return (
        f"claude did not answer within {timeout:g} seconds; "
        "raise timeout in [model] if the model needs longer"
    )


def _excerpt(line: bytes | bytearray) -> str:
    text = line.decode("utf-8", errors="replace").strip()
    return json.dumps(text if len(text) <= 200 else text[:200] + "…", ensure_ascii=False)


def _detail(stderr: str) -> str:
    text = stderr.strip()
    return f"\n{text}" if text else ""
