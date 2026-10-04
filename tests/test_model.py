import os
import time
from pathlib import Path

import pytest
from fake_claude import COST_USD, MODEL
from fakes import INIT, NO_FINDINGS, FakeClaude
from processes import gone

from doc_truth import model as model_module
from doc_truth.collect import MAX_STDERR
from doc_truth.config import ModelSettings
from doc_truth.model import ModelError, ask_claude
from doc_truth.prompt import Prompt

PROMPT = Prompt(version=1, system="Compare the docs with the evidence.", user="# Documents\n")
SETTINGS = ModelSettings()
TEXT = {"type": "assistant", "message": {"content": [{"type": "text", "text": "Checking."}]}}


def failed_result(text: str) -> dict[str, object]:
    return {"type": "result", "subtype": "success", "is_error": True, "result": text}


def ask_failing(settings: ModelSettings = SETTINGS) -> str:
    with pytest.raises(ModelError) as caught:
        ask_claude(PROMPT, settings)
    return str(caught.value)


def test_the_answer_comes_from_the_result_event(fake_claude: FakeClaude) -> None:
    fake_claude.play(("out", INIT), ("out", TEXT), ("answer",))

    answer = ask_claude(PROMPT, SETTINGS)

    assert answer.text == NO_FINDINGS
    assert answer.models == (MODEL,)
    assert (answer.input_tokens, answer.output_tokens) == (1203, 50)
    assert answer.cost_usd == COST_USD
    assert 0 < answer.duration < 10


def test_claude_runs_with_every_tool_disabled(fake_claude: FakeClaude) -> None:
    ask_claude(PROMPT, ModelSettings(name="opus"))

    (call,) = fake_claude.calls()
    assert call["argv"] == [
        "--print",
        "--safe-mode",
        "--tools=",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--output-format=stream-json",
        "--verbose",
        "--model=opus",
        "--system-prompt=Compare the docs with the evidence.",
    ]


def test_the_prompt_goes_to_standard_input(fake_claude: FakeClaude) -> None:
    user = "# Documents\n" + "a line of a long document\n" * 100_000

    ask_claude(Prompt(version=1, system="x", user=user), SETTINGS)

    assert fake_claude.calls()[0]["stdin"] == user


def test_claude_runs_in_an_empty_folder_that_is_removed_afterwards(
    fake_claude: FakeClaude,
) -> None:
    ask_claude(PROMPT, SETTINGS)

    (call,) = fake_claude.calls()
    assert call["cwd_entries"] == []
    assert Path(call["cwd"]).name.startswith("doc-truth-")
    assert call["cwd"] != os.getcwd()
    assert not Path(call["cwd"]).exists()


@pytest.mark.parametrize(
    ("init", "listed"),
    [
        ({**INIT, "tools": ["Bash", "Read"]}, "tools: Bash, Read; MCP servers: none"),
        (
            {**INIT, "mcp_servers": [{"name": "github", "status": "connected"}]},
            "tools: none; MCP servers: github",
        ),
        ({"type": "system", "subtype": "init"}, "tools: not listed; MCP servers: not listed"),
    ],
)
def test_offered_tools_stop_claude_at_once(
    fake_claude: FakeClaude, tmp_path: Path, init: dict[str, object], listed: str
) -> None:
    went_on = tmp_path / "went-on"
    fake_claude.play(("out", init), ("sleep", 5), ("touch", str(went_on)), ("answer",))
    started = time.monotonic()

    message = ask_failing()

    assert message == (
        "claude offered the model tools, so doc-truth stopped it before it could use them "
        f"({listed})"
    )
    assert time.monotonic() - started < 4
    assert not went_on.exists()


@pytest.mark.parametrize("kind", ["tool_use", "server_tool_use"])
def test_a_tool_call_stops_claude(fake_claude: FakeClaude, kind: str) -> None:
    call = {"type": "assistant", "message": {"content": [{"type": kind, "name": "WebFetch"}]}}
    fake_claude.play(("out", INIT), ("out", call), ("sleep", 5), ("answer",))

    assert ask_failing() == "the model tried to use a tool (WebFetch); stopped it"


@pytest.mark.parametrize("first", [("out", TEXT), ("answer",)])
def test_an_answer_before_the_tool_list_is_refused(
    fake_claude: FakeClaude, first: tuple[object, ...]
) -> None:
    fake_claude.play(first, ("out", INIT))

    assert ask_failing() == (
        "claude answered without first listing the model's tools, so doc-truth could not "
        "check that it has none"
    )


def test_other_events_are_ignored(fake_claude: FakeClaude) -> None:
    status = {"type": "system", "subtype": "status"}
    odd_message = {"type": "assistant", "message": "not an object"}
    odd_content = {"type": "assistant", "message": {"content": ["text", {"no": "type"}]}}
    fake_claude.play(
        ("out", status),
        ("out", ""),
        ("out", INIT),
        ("out", odd_message),
        ("out", odd_content),
        ("answer",),
    )

    assert ask_claude(PROMPT, SETTINGS).text == NO_FINDINGS


def test_the_last_line_needs_no_line_break(fake_claude: FakeClaude) -> None:
    fake_claude.play(
        ("out", INIT),
        ("write", '{"type": "result", "is_error": false, "result": "{}", "modelUsage": {}}'),
    )

    answer = ask_claude(PROMPT, SETTINGS)

    assert (answer.text, answer.models, answer.cost_usd) == ("{}", (), 0.0)


def test_the_last_result_wins(fake_claude: FakeClaude) -> None:
    first = {"type": "result", "is_error": False, "result": "first"}
    fake_claude.play(("out", INIT), ("out", first), ("answer",))

    assert ask_claude(PROMPT, SETTINGS).text == NO_FINDINGS


def test_odd_usage_counts_as_nothing(fake_claude: FakeClaude) -> None:
    result = {
        "type": "result",
        "is_error": False,
        "result": "{}",
        "total_cost_usd": "free",
        "modelUsage": {"m1": "odd", "m2": {"inputTokens": "many", "outputTokens": 7}},
    }
    fake_claude.play(("out", INIT), ("out", result))

    answer = ask_claude(PROMPT, SETTINGS)

    assert (answer.models, answer.input_tokens, answer.output_tokens) == (("m1", "m2"), 0, 7)
    assert answer.cost_usd == 0.0


def test_not_logged_in(fake_claude: FakeClaude) -> None:
    fake_claude.play(
        ("out", INIT), ("out", failed_result("Not logged in · Please run /login")), ("exit", 1)
    )

    assert ask_failing() == "claude failed: Not logged in · Please run /login"


def test_a_prompt_that_is_too_long_gets_advice(fake_claude: FakeClaude) -> None:
    fake_claude.play(("out", INIT), ("out", failed_result("Prompt is too long")), ("exit", 1))

    assert ask_failing() == (
        "claude failed: Prompt is too long: the docs and evidence don't fit in the model's "
        "context window; check fewer docs at a time"
    )


@pytest.mark.parametrize(
    ("result", "exit_code", "message"),
    [
        ({"is_error": True, "result": "API Error: 529"}, 0, "claude failed: API Error: 529"),
        ({"is_error": False, "result": "{}"}, 1, "claude failed: {}"),
        ({"result": "{}"}, 0, "claude failed: {}"),
        ({"is_error": False, "result": 7}, 0, "claude failed: exit code 0"),
        ({"is_error": True, "result": " "}, 1, "claude failed: exit code 1"),
    ],
)
def test_a_failed_result(
    fake_claude: FakeClaude, result: dict[str, object], exit_code: int, message: str
) -> None:
    fake_claude.play(("out", INIT), ("out", {"type": "result", **result}), ("exit", exit_code))

    assert ask_failing() == message


def test_an_exit_without_an_answer_shows_standard_error(fake_claude: FakeClaude) -> None:
    fake_claude.play(("out", INIT), ("err", "error: unknown option '--safe-mode'\n"), ("exit", 3))

    assert ask_failing() == (
        "claude exited with code 3 without an answer\nerror: unknown option '--safe-mode'"
    )


def test_standard_error_is_capped(fake_claude: FakeClaude) -> None:
    fake_claude.play(("out", INIT), ("err", "x" * (MAX_STDERR + 100)), ("exit", 3))

    assert ask_failing().split("\n", 1)[1] == "x" * MAX_STDERR


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("Loading…", 'claude printed a line that isn\'t JSON: "Loading…"'),
        ("[1, 2]", 'claude printed JSON that isn\'t an event: "[1, 2]"'),
        ("x" * 300, f'claude printed a line that isn\'t JSON: "{"x" * 200}…"'),
    ],
)
def test_output_that_isnt_an_event_is_refused(
    fake_claude: FakeClaude, line: str, message: str
) -> None:
    fake_claude.play(("out", INIT), ("out", line), ("answer",))

    assert ask_failing() == message


def test_too_much_output_stops_claude(
    fake_claude: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(model_module, "MAX_OUTPUT", 1000)
    fake_claude.play(("out", INIT), ("out", TEXT), ("out", TEXT), ("out", " " * 1000), ("answer",))

    assert ask_failing() == "claude printed more than 1000 bytes; stopped it"


def test_a_timeout_stops_claude_and_everything_it_started(
    fake_claude: FakeClaude, tmp_path: Path, quick_stop: None
) -> None:
    pid_file = tmp_path / "child.pid"
    fake_claude.play(("out", INIT), ("child", str(pid_file)), ("sleep", 30), ("answer",))
    started = time.monotonic()

    message = ask_failing(ModelSettings(timeout=0.5))

    assert message == (
        "claude did not answer within 0.5 seconds; raise timeout in [model] if the model needs "
        "longer"
    )
    assert time.monotonic() - started < 3
    assert gone(int(pid_file.read_text()))


def test_a_timeout_after_the_output_closes(fake_claude: FakeClaude) -> None:
    script = Path(os.environ["PATH"].split(os.pathsep)[0]) / "claude"
    script.write_text("#!/bin/sh\nexec >&- 2>&-\nsleep 30\n", encoding="utf-8")

    assert ask_failing(ModelSettings(timeout=0.5)).startswith("claude did not answer within 0.5")


def test_claude_must_be_on_the_path(
    fake_claude: FakeClaude, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))

    assert ask_failing() == (
        "the claude command was not found on PATH; comparing docs with evidence needs "
        "Claude Code installed and logged in"
    )


def test_claude_that_cannot_start(fake_claude: FakeClaude) -> None:
    script = Path(os.environ["PATH"].split(os.pathsep)[0]) / "claude"
    script.write_text("#!/nonexistent/interpreter\n", encoding="utf-8")

    assert ask_failing() == "could not start claude: No such file or directory"
