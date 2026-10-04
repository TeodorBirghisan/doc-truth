import re
from pathlib import Path

import pytest

from doc_truth.collect import LOCALE, MAX_STDERR, MAX_STDOUT, REMOVED_VARIABLES, STOP_GRACE
from doc_truth.config import (
    DEFAULT_MODEL,
    DEFAULT_MODEL_TIMEOUT,
    DOC_KEYS,
    MODEL_KEYS,
    PROBE_KEYS,
    TOP_LEVEL_KEYS,
    load_config,
)
from doc_truth.evidence import format_size
from doc_truth.runs import DEFAULT_OUTPUT_DIR_NAME, EVIDENCE_JSON, EVIDENCE_MARKDOWN, RUNS_DIR_NAME

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
    tables = {"docs": "`[[docs]]`", "probes": "`[[probes]]`", "model": "`[model]`"}
    documented = [*tables.values(), *(f"`{key}`" for key in (*DOC_KEYS, *PROBE_KEYS, *MODEL_KEYS))]

    assert set(tables) == set(TOP_LEVEL_KEYS)
    assert [form for form in documented if form not in reference] == []


def test_the_reference_gives_the_model_defaults() -> None:
    reference = REFERENCE.read_text(encoding="utf-8")

    assert f'| `name` | string | `"{DEFAULT_MODEL}"` |' in reference
    assert f"| `timeout` | number | `{DEFAULT_MODEL_TIMEOUT:g}` |" in reference


def flowed(document: Path) -> str:
    return " ".join(document.read_text(encoding="utf-8").split())


def test_the_reference_describes_how_probes_run() -> None:
    reference = flowed(REFERENCE)
    facts = [
        "`bash -o pipefail`",
        f"`LC_ALL={LOCALE}`",
        *(f"`{name}` removed" for name in REMOVED_VARIABLES),
        f"{STOP_GRACE:g} seconds later",
        f"first {format_size(MAX_STDOUT)} of a probe's standard output",
        f"first {format_size(MAX_STDERR)} of its standard error",
    ]

    assert [fact for fact in facts if fact not in reference] == []


def test_the_readme_describes_the_run_folder() -> None:
    readme = flowed(ROOT / "README.md")
    facts = [
        f"`{DEFAULT_OUTPUT_DIR_NAME}/{RUNS_DIR_NAME}/<UTC time>/`",
        f"`{EVIDENCE_MARKDOWN}`",
        f"`{EVIDENCE_JSON}`",
        "`--output-dir PATH`",
    ]

    assert [fact for fact in facts if fact not in readme] == []
