import ipaddress
import json
import re
import textwrap
from pathlib import Path

import pytest

from doc_truth.evidence import evidence_markdown
from doc_truth.findings import DocQuote, Kind, ProbeQuote
from evals.cases import CASES_DIR, Case, CaseError, case_directories, load_case
from evals.score import score

CASE_NAMES = [path.name for path in case_directories()]

_ALLOWED_NETWORKS = [
    ipaddress.ip_network(network)
    for network in (
        "0.0.0.0/32",
        "127.0.0.0/8",
        "100.64.0.0/10",
        "192.0.2.0/24",
        "198.51.100.0/24",
        "203.0.113.0/24",
    )
]
_IPV4 = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
_URL_HOST = re.compile(r"https?://([^/\s:`'\"]+)")


def flowed(text: str) -> str:
    return " ".join(text.split())


def doc_lines(case: Case, file: str, start: int, end: int) -> str:
    (doc,) = [doc for doc in case.docs if doc.display_path == file]
    return flowed(" ".join(doc.path.read_text(encoding="utf-8").splitlines()[start - 1 : end]))


def test_the_suite_has_the_agreed_cases() -> None:
    assert CASE_NAMES == [
        "apt-scope-cross-doc",
        "clean",
        "failed-user-probe",
        "haystack",
        "history-note",
        "omission-claimed-complete",
        "omission-not-claimed",
        "other-host-path",
        "stale-status",
        "timeshift-cron-contradiction",
    ]


def test_the_readme_describes_every_case() -> None:
    readme = (CASES_DIR.parent / "README.md").read_text(encoding="utf-8")
    listed = re.findall(r"^\| `([a-z0-9-]+)` \|", readme, flags=re.MULTILINE)
    haystack = load_case(CASES_DIR / "haystack")
    size = re.search(r"among (\d+) docs and (\d+) probes", readme)

    assert sorted(listed) == CASE_NAMES
    assert size is not None
    assert (int(size[1]), int(size[2])) == (len(haystack.docs), len(haystack.config.probes))


def test_the_reference_answers_cover_every_kind_of_finding() -> None:
    kinds = {
        finding.kind for name in CASE_NAMES for finding in load_case(CASES_DIR / name).reference
    }

    assert kinds == set(Kind)


@pytest.mark.parametrize("name", CASE_NAMES)
def test_the_reference_answer_scores_perfectly(name: str) -> None:
    case = load_case(CASES_DIR / name)

    assert score(case.expected, case.reference).passed


@pytest.mark.parametrize("name", CASE_NAMES)
def test_the_reference_quotes_are_where_they_say(name: str) -> None:
    case = load_case(CASES_DIR / name)
    outputs = {result.probe.name: result.stdout + result.stderr for result in case.evidence.results}

    for finding in case.reference:
        doc = finding.doc
        assert flowed(doc.quote) in doc_lines(case, doc.file, doc.line, doc.end_line)
        evidence = finding.evidence
        if isinstance(evidence, ProbeQuote):
            assert flowed(evidence.quote) in flowed(outputs[evidence.probe])
        else:
            assert isinstance(evidence, DocQuote)
            lines = doc_lines(case, evidence.file, evidence.line, evidence.end_line)
            assert flowed(evidence.quote) in lines


@pytest.mark.parametrize("name", CASE_NAMES)
def test_the_evidence_renders_every_probe(name: str) -> None:
    case = load_case(CASES_DIR / name)

    markdown = evidence_markdown(case.evidence)

    for probe in case.config.probes:
        assert f"\n## {probe.name}\n" in markdown


@pytest.mark.parametrize("name", CASE_NAMES)
def test_the_case_uses_only_documentation_addresses(name: str) -> None:
    for path in (CASES_DIR / name).rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for address in _IPV4.findall(text):
            ip = ipaddress.ip_address(address)
            assert any(ip in network for network in _ALLOWED_NETWORKS), (path, address)
        for host in _URL_HOST.findall(text):
            assert host.endswith((".example.org", ".example.com")), (path, host)
        assert ".ts.net" not in text, path


MINIMAL = {
    "doc-truth.toml": """
        [[docs]]
        path = "docs/a.md"

        [[probes]]
        name = "timers"
        command = "systemctl list-timers"

        [[probes]]
        name = "slow"
        command = "find /"
        timeout = 5
        """,
    "docs/a.md": "# A\n\nThe backup runs at 02:00.\n",
    "evidence.toml": """
        [[results]]
        probe = "timers"
        exit-code = 0
        stdout = "backup.timer 03:00\\n"

        [[results]]
        probe = "slow"
        timed-out = true
        """,
    "expected.toml": """
        [[must-find]]
        id = "backup"
        doc = ["docs/a.md:3"]
        evidence = ["probe:timers"]
        confidence = "confirmed"

        [[must-not-find]]
        id = "slow"
        evidence = ["probe:slow"]
        """,
    "reference.json": json.dumps({"findings": []}),
}


def write_case(directory: Path, **changes: str) -> Path:
    for name, text in {**MINIMAL, **changes}.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return directory


def test_a_minimal_case_loads(tmp_path: Path) -> None:
    case = load_case(write_case(tmp_path / "minimal"))

    assert case.name == "minimal"
    assert [result.failure for result in case.evidence.results] == [None, "timed out after 5s"]
    assert case.evidence.results[1].signal == "SIGTERM"
    (backup,) = case.expected.must_find
    assert (backup.probes, backup.doc[0].start, backup.doc[0].end) == (("timers",), 3, 3)
    assert case.expected.must_not_find[0].probes == ("slow",)


def test_results_follow_the_order_of_the_probes(tmp_path: Path) -> None:
    first, second = MINIMAL["evidence.toml"].split("\n\n")

    case = load_case(write_case(tmp_path / "c", **{"evidence.toml": f"{second}\n\n{first}"}))

    assert [result.probe.name for result in case.evidence.results] == ["timers", "slow"]


def test_an_exit_code_outside_success_exit_codes_fails_the_probe(tmp_path: Path) -> None:
    evidence = MINIMAL["evidence.toml"].replace("exit-code = 0", "exit-code = 1")

    case = load_case(write_case(tmp_path / "c", **{"evidence.toml": evidence}))

    assert case.evidence.results[0].failure == "exit code 1 is not in success-exit-codes [0]"


@pytest.mark.parametrize(
    ("file", "old", "new", "message"),
    [
        ("evidence.toml", 'probe = "slow"', 'probe = "fast"', "probe must name a probe"),
        ("evidence.toml", 'probe = "slow"', 'probe = "timers"', "already has a result"),
        (
            "evidence.toml",
            "timed-out = true",
            "exit-code = 0\ntimed-out = true",
            "either exit-code",
        ),
        ("evidence.toml", "timed-out = true", "", "either exit-code"),
        ("evidence.toml", "timed-out = true", "timed-out = 1", "timed-out must be a boolean"),
        ("evidence.toml", "exit-code = 0", 'exit-code = "0"', "exit-code must be an integer"),
        ("evidence.toml", "stdout = ", "stdout = 3 #", "stdout and stderr must be strings"),
        ("evidence.toml", "exit-code = 0", "exit-code = 0\nduration = 1", "unknown keys duration"),
        ("expected.toml", "docs/a.md:3", "docs/a.md:4", "outside docs/a.md's 3 lines"),
        ("expected.toml", "docs/a.md:3", "docs/a.md:3-2", "outside docs/a.md's 3 lines"),
        ("expected.toml", "docs/a.md:3", "docs/b.md:1", "docs/b.md is not one of the case's docs"),
        ("expected.toml", "docs/a.md:3", "docs/a.md", "is not FILE:LINE or FILE:START-END"),
        ("expected.toml", "probe:timers", "probe:cron", "no probe named cron"),
        ("expected.toml", 'id = "slow"', 'id = "backup"', "id backup is already used"),
        ("expected.toml", 'id = "slow"', 'id = "Slow"', "id must be a lowercase slug"),
        ("expected.toml", '"confirmed"', '"suspect"', "can only require confidence"),
        ("expected.toml", '"confirmed"', '"certain"', "confidence must be"),
        ("expected.toml", 'doc = ["docs/a.md:3"]', "", "must-find needs doc locations"),
        ("expected.toml", 'evidence = ["probe:slow"]', "", "or it would match every finding"),
        (
            "expected.toml",
            'evidence = ["probe:slow"]',
            'evidence = "probe:slow"',
            "must be an array",
        ),
        (
            "expected.toml",
            "[[must-not-find]]",
            "[[must-not-find]]\nnote = 3",
            "note must be a string",
        ),
        ("expected.toml", "[[must-not-find]]", "[[must-not]]", "unknown keys must-not"),
        ("reference.json", "[]", "[{}]", "invalid findings"),
        ("reference.json", "[]", "[", "Expecting value"),
    ],
)
def test_broken_cases_are_rejected(
    tmp_path: Path, file: str, old: str, new: str, message: str
) -> None:
    text = MINIMAL[file]
    assert old in text
    directory = write_case(tmp_path / "broken", **{file: text.replace(old, new, 1)})

    with pytest.raises(CaseError, match=r"^case broken: ") as caught:
        load_case(directory)

    assert message in str(caught.value)


def test_a_result_is_needed_for_every_probe(tmp_path: Path) -> None:
    evidence = MINIMAL["evidence.toml"].split("\n\n")[0]

    with pytest.raises(CaseError, match=r"evidence.toml: no result for slow$"):
        load_case(write_case(tmp_path / "c", **{"evidence.toml": evidence}))


def test_a_case_without_results_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CaseError, match=r"needs \[\[results\]\] tables"):
        load_case(write_case(tmp_path / "c", **{"evidence.toml": ""}))


def test_a_broken_config_is_reported_with_the_case_name(tmp_path: Path) -> None:
    with pytest.raises(CaseError, match=r"^case c: .*no \[\[probes\]\] entries"):
        load_case(
            write_case(tmp_path / "c", **{"doc-truth.toml": '[[docs]]\npath = "docs/a.md"\n'})
        )


@pytest.mark.parametrize(
    ("file", "text", "message"),
    [
        ("evidence.toml", "results = [1]\n", "[[results]] #1: must be a table"),
        ("expected.toml", "must-find = 1\n", "must-find must be [[must-find]] tables"),
        ("expected.toml", "allowed = [1]\n", "[[allowed]] #1: must be a table"),
    ],
)
def test_entries_must_be_tables(tmp_path: Path, file: str, text: str, message: str) -> None:
    with pytest.raises(CaseError) as caught:
        load_case(write_case(tmp_path / "c", **{file: text}))

    assert message in str(caught.value)
