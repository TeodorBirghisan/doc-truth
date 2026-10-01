import re
from pathlib import Path

import pytest

from doc_truth.config import DOC_KEYS, PROBE_KEYS, TOP_LEVEL_KEYS, load_config

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "docs" / "configuration.md"


def toml_examples(document: Path) -> list[str]:
    text = document.read_text(encoding="utf-8")
    return re.findall(r"^```toml\n(.*?)^```$", text, flags=re.MULTILINE | re.DOTALL)


@pytest.mark.parametrize("document", ["README.md", "docs/configuration.md"])
def test_toml_examples_are_valid_configs(tmp_path: Path, document: str) -> None:
    examples = toml_examples(ROOT / document)
    assert examples, f"{document} has no TOML examples"

    for example in examples:
        path = tmp_path / "doc-truth.toml"
        path.write_text(example, encoding="utf-8")
        load_config(path)


def test_the_reference_documents_every_key() -> None:
    reference = REFERENCE.read_text(encoding="utf-8")
    documented = [f"`[[{key}]]`" for key in TOP_LEVEL_KEYS]
    documented += [f"`{key}`" for key in (*DOC_KEYS, *PROBE_KEYS)]

    assert [form for form in documented if form not in reference] == []
