import re
from pathlib import Path


def fenced_blocks(document: Path, language: str) -> list[str]:
    text = document.read_text(encoding="utf-8")
    pattern = rf"^```{re.escape(language)}\n(.*?)^```$"
    return re.findall(pattern, text, flags=re.MULTILINE | re.DOTALL)
