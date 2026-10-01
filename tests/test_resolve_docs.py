from collections.abc import Callable
from pathlib import Path

import pytest

from doc_truth.config import Config, ConfigError, Doc, load_config, resolve_docs

PROBES = """
[[probes]]
name = "uptime"
command = "uptime"
"""


@pytest.fixture
def config_with(write_config: Callable[[str], Path]) -> Callable[..., Config]:
    def build(*entries: str) -> Config:
        docs = "".join(f"[[docs]]\n{entry}\n\n" for entry in entries)
        return load_config(write_config(docs + PROBES))

    return build


def display_paths(config: Config) -> list[str]:
    return [doc.display_path for doc in resolve_docs(config)]


def resolve_problems(config: Config) -> tuple[str, ...]:
    with pytest.raises(ConfigError) as caught:
        resolve_docs(config)
    return caught.value.problems


def test_a_literal_path_resolves_to_that_file(
    tmp_path: Path, touch: Callable[..., None], config_with: Callable[..., Config]
) -> None:
    touch("README.md")

    assert resolve_docs(config_with('path = "README.md"')) == (
        Doc(path=tmp_path / "README.md", display_path="README.md", notes=()),
    )


def test_patterns_match_recursively_and_in_sorted_order(
    touch: Callable[..., None], config_with: Callable[..., Config]
) -> None:
    touch("runbooks/restore.md", "runbooks/backup.md", "runbooks/deep/dr.md", "runbooks/x.txt")

    assert display_paths(config_with('path = "runbooks/**/*.md"')) == [
        "runbooks/backup.md",
        "runbooks/deep/dr.md",
        "runbooks/restore.md",
    ]


def test_paths_are_relative_to_the_config_file_not_the_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    touch: Callable[..., None],
    config_with: Callable[..., Config],
) -> None:
    touch("README.md", "docs/a.md", "elsewhere/README.md", "elsewhere/docs/b.md")
    config = config_with('path = "README.md"', 'path = "docs/*.md"')
    monkeypatch.chdir(tmp_path / "elsewhere")

    assert [doc.path for doc in resolve_docs(config)] == [
        tmp_path / "README.md",
        tmp_path / "docs/a.md",
    ]


def test_absolute_paths_and_home_directory_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    touch: Callable[..., None],
    config_with: Callable[..., Config],
) -> None:
    touch("shared/ops.md", "home/notes/backup.md")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    config = config_with(
        f'path = "{tmp_path}/shared/*.md"',
        'path = "~/notes/backup.md"',
    )

    assert [doc.path for doc in resolve_docs(config)] == [
        tmp_path / "shared/ops.md",
        tmp_path / "home/notes/backup.md",
    ]


def test_files_outside_the_config_directory_show_their_absolute_path(
    tmp_path: Path, touch: Callable[..., None]
) -> None:
    touch("project/doc-truth.toml", "shared/ops.md")
    config_path = tmp_path / "project/doc-truth.toml"
    config_path.write_text('[[docs]]\npath = "../shared/ops.md"\n' + PROBES, encoding="utf-8")

    assert resolve_docs(load_config(config_path)) == (
        Doc(
            path=tmp_path / "shared/ops.md",
            display_path=str(tmp_path / "shared/ops.md"),
            notes=(),
        ),
    )


def test_hidden_files_match_only_when_the_pattern_names_the_dot(
    touch: Callable[..., None], config_with: Callable[..., Config]
) -> None:
    touch("visible.md", ".hidden.md", ".github/CONTRIBUTING.md", "docs/.draft.md")

    assert display_paths(config_with('path = "**/*.md"')) == ["visible.md"]
    assert display_paths(config_with('path = ".github/*.md"')) == [".github/CONTRIBUTING.md"]


def test_patterns_skip_directories(
    tmp_path: Path, touch: Callable[..., None], config_with: Callable[..., Config]
) -> None:
    touch("docs/a.md")
    (tmp_path / "docs/archive.md").mkdir()

    assert display_paths(config_with('path = "docs/*.md"')) == ["docs/a.md"]


def test_a_file_matched_twice_is_checked_once_with_all_its_notes(
    touch: Callable[..., None], config_with: Callable[..., Config]
) -> None:
    touch("ops.md", "readme.md")
    config = config_with(
        'path = "*.md"\nnotes = "Describes this host."',
        'path = "ops.md"\nnotes = "Section 3 lists every scheduled job."',
        'path = "ops.md"\nnotes = "Describes this host."',
        'path = "readme.md"',
    )

    assert [(doc.display_path, doc.notes) for doc in resolve_docs(config)] == [
        ("ops.md", ("Describes this host.", "Section 3 lists every scheduled job.")),
        ("readme.md", ("Describes this host.",)),
    ]


def test_a_symlink_and_its_target_are_the_same_file(
    tmp_path: Path, touch: Callable[..., None], config_with: Callable[..., Config]
) -> None:
    touch("real.md")
    (tmp_path / "alias.md").symlink_to(tmp_path / "real.md")

    assert display_paths(config_with('path = "*.md"')) == ["alias.md"]


def test_every_path_problem_is_reported_at_once(
    tmp_path: Path, touch: Callable[..., None], config_with: Callable[..., Config]
) -> None:
    touch("README.md")
    (tmp_path / "docs").mkdir()
    config = config_with(
        'path = "missing.md"',
        'path = "README.md"',
        'path = "runbooks/*.md"',
        'path = "docs"',
        'path = "docs/"',
    )

    assert resolve_problems(config) == (
        '[[docs]] #1 "missing.md": file not found',
        '[[docs]] #3 "runbooks/*.md": no files match',
        '[[docs]] #4 "docs": is a directory; to check the Markdown files in it, '
        'use a pattern such as "docs/**/*.md"',
        '[[docs]] #5 "docs/": is a directory; to check the Markdown files in it, '
        'use a pattern such as "docs/**/*.md"',
    )


def test_a_broken_symlink_is_not_found(tmp_path: Path, config_with: Callable[..., Config]) -> None:
    (tmp_path / "gone.md").symlink_to(tmp_path / "deleted.md")

    assert resolve_problems(config_with('path = "gone.md"')) == (
        '[[docs]] #1 "gone.md": file not found',
    )
