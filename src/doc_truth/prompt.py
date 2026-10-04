import re
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files

from doc_truth.config import Doc
from doc_truth.evidence import blockquote, fence

PROMPT_VERSION = 1

_LINE_BREAK = re.compile(r"\r\n|\r|\n")


class PromptError(Exception):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Prompt:
    version: int
    system: str
    user: str


def build_prompt(docs: Sequence[Doc], evidence_markdown: str) -> Prompt:
    blocks = ["# Documents"]
    for doc in docs:
        blocks.extend(_doc_blocks(doc))
    return Prompt(
        version=PROMPT_VERSION,
        system=system_prompt(),
        user="\n\n".join(blocks) + "\n\n" + evidence_markdown,
    )


def system_prompt() -> str:
    resource = files("doc_truth").joinpath("prompts", f"check-{PROMPT_VERSION}.md")
    return resource.read_text(encoding="utf-8")


def split_lines(text: str) -> list[str]:
    lines = _LINE_BREAK.split(text)
    if lines[-1] == "":
        lines.pop()
    return lines


def _doc_blocks(doc: Doc) -> list[str]:
    blocks = [f"## {doc.display_path}"]
    for notes in doc.notes:
        blocks.append("Notes:\n\n" + blockquote(notes))
    lines = split_lines(_read(doc))
    if not lines:
        blocks.append("The document is empty.")
        return blocks
    width = len(str(len(lines)))
    numbered = "".join(
        f"{number:>{width}}:{' ' if line else ''}{line}\n"
        for number, line in enumerate(lines, start=1)
    )
    blocks.append(fence(numbered, "text"))
    return blocks


def _read(doc: Doc) -> str:
    try:
        return doc.path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise PromptError(f"{doc.display_path}: is not valid UTF-8") from None
    except OSError as error:
        raise PromptError(
            f"{doc.display_path}: cannot be read: {error.strerror or error}"
        ) from None
