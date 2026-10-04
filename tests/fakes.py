import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

FAKE_CLAUDE = Path(__file__).with_name("fake_claude.py")
INIT = {"type": "system", "subtype": "init", "tools": [], "mcp_servers": []}
ANSWER = (("out", INIT), ("answer",))
NO_FINDINGS = '{"findings": []}'


class FakeClaude:
    def __init__(self, directory: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._scenario = directory / "scenario.json"
        self._record = directory / "calls.jsonl"
        bin_dir = directory / "bin"
        bin_dir.mkdir()
        script = bin_dir / "claude"
        script.write_text(
            f"#!{sys.executable}\nimport runpy\n"
            f"runpy.run_path({str(FAKE_CLAUDE)!r}, run_name='__main__')\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
        monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", str(self._scenario))
        self.play(*ANSWER)

    def play(self, *actions: Sequence[object], answers: Mapping[str, str] | None = None) -> None:
        scenario = {
            "record": str(self._record),
            "actions": actions,
            "answers": {"*": NO_FINDINGS} if answers is None else dict(answers),
        }
        self._scenario.write_text(json.dumps(scenario), encoding="utf-8")

    def calls(self) -> list[dict[str, Any]]:
        if not self._record.exists():
            return []
        return [json.loads(line) for line in self._record.read_text(encoding="utf-8").splitlines()]
