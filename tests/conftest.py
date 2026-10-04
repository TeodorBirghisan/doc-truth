import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest
from fakes import FakeClaude

from doc_truth import collect as collect_module


@pytest.fixture
def write_config(tmp_path: Path) -> Callable[[str], Path]:
    def write(text: str) -> Path:
        path = tmp_path / "doc-truth.toml"
        path.write_text(textwrap.dedent(text), encoding="utf-8")
        return path

    return write


@pytest.fixture
def touch(tmp_path: Path) -> Callable[..., None]:
    def create(*names: str) -> None:
        for name in names:
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Doc\n", encoding="utf-8")

    return create


@pytest.fixture
def fake_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeClaude:
    directory = tmp_path / "fake-claude"
    directory.mkdir()
    return FakeClaude(directory, monkeypatch)


@pytest.fixture
def quick_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(collect_module, "STOP_GRACE", 0.2)
    monkeypatch.setattr(collect_module, "DRAIN_TIME", 0.2)
