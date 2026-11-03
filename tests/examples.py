import re
from pathlib import Path


def fenced_in(text: str, language: str) -> list[str]:
    pattern = rf"^```{re.escape(language)}\n(.*?)^```$"
    return re.findall(pattern, text, flags=re.MULTILINE | re.DOTALL)


def fenced_blocks(document: Path, language: str) -> list[str]:
    return fenced_in(document.read_text(encoding="utf-8"), language)


def config_examples(document: Path) -> list[str]:
    return [
        example
        for example in fenced_blocks(document, "toml")
        if not example.startswith("[[known]]")
    ]
