from pathlib import Path

import pytest

from doc_truth.config import Doc
from doc_truth.evidence import FAILED_LABEL
from doc_truth.findings import Confidence, Fix, Kind
from doc_truth.prompt import PROMPT_VERSION, PromptError, build_prompt, split_lines, system_prompt

PROMPTS = Path(__file__).resolve().parents[1] / "src" / "doc_truth" / "prompts"
EVIDENCE = "# Evidence from host `homeserver`\n\nCollected 2026-10-03.\n"


def make_doc(tmp_path: Path, name: str, content: str | bytes, *notes: str) -> Doc:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8", newline="")
    else:
        path.write_bytes(content)
    return Doc(path=path, display_path=name, notes=notes)


def test_the_message_has_every_doc_with_line_numbers_then_the_evidence(tmp_path: Path) -> None:
    docs = [
        make_doc(
            tmp_path, "docs/ops.md", "# Ops\n\nBackups run at 03:00.\n", "Section 3 is complete."
        ),
        make_doc(tmp_path, "notes/a.md", "one line, no line break"),
    ]

    prompt = build_prompt(docs, EVIDENCE)

    assert prompt.user == (
        "# Documents\n\n"
        "## docs/ops.md\n\n"
        "Notes:\n\n"
        "> Section 3 is complete.\n\n"
        "```text\n"
        "1: # Ops\n"
        "2:\n"
        "3: Backups run at 03:00.\n"
        "```\n\n"
        "## notes/a.md\n\n"
        "```text\n"
        "1: one line, no line break\n"
        "```\n\n" + EVIDENCE
    )
    assert prompt.system == system_prompt()
    assert prompt.version == PROMPT_VERSION == 1


def test_line_numbers_are_aligned(tmp_path: Path) -> None:
    doc = make_doc(tmp_path, "a.md", "".join(f"line {number}\n" for number in range(1, 11)))

    user = build_prompt([doc], EVIDENCE).user

    assert " 9: line 9\n10: line 10\n" in user
    assert " 1: line 1\n" in user


def test_every_note_is_quoted(tmp_path: Path) -> None:
    doc = make_doc(tmp_path, "a.md", "x\n", "First note.", "Second note,\nover two lines.")

    user = build_prompt([doc], EVIDENCE).user

    assert "Notes:\n\n> First note.\n\nNotes:\n\n> Second note,\n> over two lines.\n\n" in user


def test_a_doc_with_backticks_gets_a_longer_fence(tmp_path: Path) -> None:
    doc = make_doc(tmp_path, "a.md", "```sh\nrestic snapshots\n```\n")

    user = build_prompt([doc], EVIDENCE).user

    assert "````text\n1: ```sh\n2: restic snapshots\n3: ```\n````" in user


def test_an_empty_doc_is_described(tmp_path: Path) -> None:
    doc = make_doc(tmp_path, "empty.md", "")

    user = build_prompt([doc], EVIDENCE).user

    assert "## empty.md\n\nThe document is empty.\n\n# Evidence" in user


def test_a_byte_order_mark_is_not_part_of_the_first_line(tmp_path: Path) -> None:
    doc = make_doc(tmp_path, "a.md", b"\xef\xbb\xbf# Title\n")

    assert "```text\n1: # Title\n```" in build_prompt([doc], EVIDENCE).user


@pytest.mark.parametrize(
    ("text", "lines"),
    [
        ("", []),
        ("\n", [""]),
        ("a", ["a"]),
        ("a\n", ["a"]),
        ("a\n\nb\n", ["a", "", "b"]),
        ("a\r\nb\rc\nd", ["a", "b", "c", "d"]),
        ("a\fb\x0bc\u2028d\x85e\n", ["a\fb\x0bc\u2028d\x85e"]),
    ],
)
def test_lines_break_where_an_editor_breaks_them(text: str, lines: list[str]) -> None:
    assert split_lines(text) == lines


def test_a_doc_that_isnt_utf8(tmp_path: Path) -> None:
    doc = make_doc(tmp_path, "latin1.md", "café\n".encode("latin-1"))

    with pytest.raises(PromptError, match=r"^latin1\.md: is not valid UTF-8$"):
        build_prompt([doc], EVIDENCE)


def test_a_doc_that_cannot_be_read(tmp_path: Path) -> None:
    doc = make_doc(tmp_path, "secret.md", "x\n")
    doc.path.chmod(0)

    with pytest.raises(PromptError, match=r"^secret\.md: cannot be read: Permission denied$"):
        build_prompt([doc], EVIDENCE)


def test_the_system_prompt_is_the_versioned_file() -> None:
    assert system_prompt() == (PROMPTS / f"check-{PROMPT_VERSION}.md").read_text(encoding="utf-8")


def test_the_system_prompt_names_every_value_the_findings_format_accepts() -> None:
    prompt = system_prompt()
    values = [*Kind, *Confidence, *Fix]

    assert [value for value in values if f"`{value}`" not in prompt] == []


def test_the_system_prompt_uses_the_evidence_wording_for_failed_probes() -> None:
    assert FAILED_LABEL in system_prompt()
