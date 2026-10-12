from pathlib import Path

import pytest

from doc_truth.config import Doc, Probe
from doc_truth.evidence import ProbeResult
from doc_truth.findings import Confidence, DocQuote, Finding, Fix, Kind, ProbeQuote
from doc_truth.prompt import DocText
from doc_truth.verify import verify

NBSP = "\u00a0"
LEFT, RIGHT = "\u201c", "\u201d"


def doc_text(name: str, *lines: str) -> DocText:
    return DocText(doc=Doc(path=Path(name), display_path=name, notes=()), lines=lines)


def probe_result(
    name: str,
    *,
    stdout: str = "",
    stderr: str = "",
    command: str = "true",
    notes: str | None = None,
    failure: str | None = None,
) -> ProbeResult:
    return ProbeResult(
        probe=Probe(
            name=name,
            command=command,
            timeout=30.0,
            success_exit_codes=frozenset({0}),
            notes=notes,
        ),
        stdout=stdout,
        stderr=stderr,
        exit_code=0 if failure is None else 1,
        signal=None,
        duration=0.1,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        failure=failure,
    )


DOCS = (
    doc_text(
        "docs/ops.md",
        "# Operations",
        "",
        "restic backs up nightly at 02:00,",
        "then prunes old snapshots.",
        f"Updates are {LEFT}manual{RIGHT} for now.",
        "",
        "Monitoring uses `node_exporter` 1.8.2.",
    ),
    doc_text(
        "notes/apt.md",
        "# apt",
        "",
        "Since 2026-08-24 it also installs",
        "noble-updates.",
        "It doesn't reboot.",
    ),
    doc_text("notes/empty.md"),
)
RESULTS = (
    probe_result(
        "timers",
        stdout="Sat 2026-10-03 03:00:00 CEST\t18h left\trestic-backup.timer\n",
        command="systemctl list-timers --all --no-pager",
        notes="Every timer on the host.",
    ),
    probe_result("exporter", stderr="node_exporter, version 1.9.1 (branch: HEAD)\n"),
    probe_result("apt", stdout='Origins-Pattern "origin=Ubuntu,archive=noble-security";\n'),
    probe_result("user-timers", stdout="restic-backup.timer\n", failure="exit code 1"),
    probe_result("sitemap", stdout="200 application/xml\n", stderr="* Connected to example.org\n"),
)


def doc_quote(
    quote: str, line: int, end_line: int | None = None, *, file: str = "docs/ops.md"
) -> DocQuote:
    end = line if end_line is None else end_line
    return DocQuote(file=file, line=line, end_line=end, quote=quote)


def finding(
    doc: DocQuote | None = None,
    evidence: ProbeQuote | DocQuote | None = None,
    *,
    title: str = "The backup runs at 03:00, not 02:00",
) -> Finding:
    return Finding(
        kind=Kind.CROSS_DOC_CONTRADICTION if isinstance(evidence, DocQuote) else Kind.CONTRADICTION,
        title=title,
        doc=doc or doc_quote("restic backs up nightly at 02:00", 3),
        evidence=evidence or ProbeQuote(probe="timers", quote="03:00:00 CEST"),
        confidence=Confidence.CONFIRMED,
        fix=Fix.DOC,
        reason="The timer fires at 03:00.",
    )


def kept(item: Finding) -> Finding:
    verification = verify([item], DOCS, RESULTS)
    assert verification.dropped == ()
    (result,) = verification.findings
    return result


def dropped(item: Finding) -> tuple[str, ...]:
    verification = verify([item], DOCS, RESULTS)
    assert verification.findings == ()
    (result,) = verification.dropped
    assert result.finding is item
    return result.problems


def test_exact_quotes_keep_the_finding_unchanged() -> None:
    item = finding()

    assert kept(item) == item


@pytest.mark.parametrize(
    ("doc", "evidence"),
    [
        (doc_quote("02:00, then prunes", 3, 4), "03:00:00 CEST"),
        (doc_quote("02:00,\n  then   prunes", 3, 4), "03:00:00 CEST"),
        (doc_quote("restic backs up nightly at 02:00", 3), "CEST 18h left restic-backup.timer"),
        (doc_quote(f"restic backs{NBSP}up", 3), f"03:00:00{NBSP}CEST"),
        (doc_quote(" restic backs up ", 3), "\n03:00:00 CEST\t"),
    ],
)
def test_whitespace_runs_count_as_one_space(doc: DocQuote, evidence: str) -> None:
    item = finding(doc, ProbeQuote(probe="timers", quote=evidence))

    assert kept(item) == item


@pytest.mark.parametrize(
    "quote",
    [
        'Updates are "manual"',
        f"Updates are {LEFT}manual{RIGHT}",
        f'are {LEFT}manual"',
    ],
)
def test_curly_and_straight_quotes_are_the_same(quote: str) -> None:
    item = finding(doc_quote(quote, 5))

    assert kept(item) == item


def test_a_curly_apostrophe_is_a_straight_one() -> None:
    item = finding(doc_quote("It doesn\u2019t reboot", 5, file="notes/apt.md"))

    assert kept(item) == item


def test_curly_quotes_match_straight_ones_in_probe_output() -> None:
    item = finding(evidence=ProbeQuote(probe="apt", quote=f"Origins-Pattern {LEFT}origin=Ubuntu"))

    assert kept(item) == item


@pytest.mark.parametrize(
    "doc",
    [
        doc_quote("Restic backs up nightly at 02:00", 3),
        doc_quote("Updates are \u2018manual\u2019", 5),
        doc_quote("restic backs up nightly at 02:00.", 3),
        doc_quote("restic backs up nightly ... 02:00", 3),
        doc_quote("restic backs up nightly \u2026 02:00", 3),
        doc_quote("restic backsup", 3),
        doc_quote("Monitoring uses node_exporter 1.8.2", 7),
        doc_quote("Since 2026\u201308\u201324", 3, file="notes/apt.md"),
    ],
)
def test_case_punctuation_dashes_and_backticks_must_match_exactly(doc: DocQuote) -> None:
    assert dropped(finding(doc)) == (f"doc: the quote is not in {doc.location}",)


def test_backticks_match_when_they_are_quoted() -> None:
    item = finding(doc_quote("Monitoring uses `node_exporter` 1.8.2", 7))

    assert kept(item) == item


@pytest.mark.parametrize(
    ("cited", "narrowed"),
    [
        ((2, 4), (3, 4)),
        ((1, 7), (3, 4)),
        ((3, 4), (3, 4)),
        ((3, 9), (3, 4)),
    ],
)
def test_the_location_narrows_to_the_lines_the_quote_covers(
    cited: tuple[int, int], narrowed: tuple[int, int]
) -> None:
    item = finding(doc_quote("nightly at 02:00,\nthen prunes", *cited))

    result = kept(item)

    assert (result.doc.line, result.doc.end_line) == narrowed
    assert result.doc.quote == item.doc.quote


@pytest.mark.parametrize(
    ("quote", "narrowed"),
    [
        ("00,\nthen pru", (3, 4)),
        ("old snap", (4, 4)),
        ("Operations", (1, 1)),
        ("1.8.2.", (7, 7)),
    ],
)
def test_a_quote_inside_words_narrows_to_their_lines(quote: str, narrowed: tuple[int, int]) -> None:
    result = kept(finding(doc_quote(quote, 1, 7)))

    assert (result.doc.line, result.doc.end_line) == narrowed


@pytest.mark.parametrize(
    "doc",
    [
        doc_quote("then prunes old snapshots", 3),
        doc_quote("02:00,\nthen prunes", 3),
        doc_quote("Operations", 2),
    ],
    ids=["elsewhere-in-the-doc", "runs-past-the-cited-lines", "blank-line"],
)
def test_a_quote_must_be_inside_the_cited_lines(doc: DocQuote) -> None:
    assert dropped(finding(doc)) == (f"doc: the quote is not in {doc.location}",)


@pytest.mark.parametrize(
    ("doc", "problem"),
    [
        (doc_quote("x", 8), "doc: docs/ops.md has no line 8; it ends at line 7"),
        (doc_quote("x", 8, 9), "doc: docs/ops.md has no line 8; it ends at line 7"),
        (doc_quote("x", 1, file="notes/empty.md"), "doc: notes/empty.md is empty"),
        (
            doc_quote("x", 1, file="docs/other.md"),
            'doc: "docs/other.md" is not one of the checked docs',
        ),
        (doc_quote("x", 1, file="ops.md"), 'doc: "ops.md" is not one of the checked docs'),
    ],
)
def test_a_doc_quote_must_cite_lines_of_a_checked_doc(doc: DocQuote, problem: str) -> None:
    assert dropped(finding(doc)) == (problem,)


def test_a_probe_quote_may_come_from_standard_error() -> None:
    item = finding(evidence=ProbeQuote(probe="exporter", quote="node_exporter, version 1.9.1"))

    assert kept(item) == item


@pytest.mark.parametrize(
    ("probe", "quote"),
    [
        ("sitemap", "application/xml * Connected"),
        ("timers", "systemctl list-timers"),
        ("timers", "Every timer on the host."),
        ("timers", "timers"),
        ("timers", "node_exporter, version 1.9.1"),
        ("timers", "18h left restic-backup.timer restic-backup.service"),
    ],
    ids=[
        "stdout-into-stderr",
        "the-command",
        "the-notes",
        "the-name",
        "another-probes-output",
        "more-than-the-output",
    ],
)
def test_a_probe_quote_must_be_in_one_stream_of_its_output(probe: str, quote: str) -> None:
    assert dropped(finding(evidence=ProbeQuote(probe=probe, quote=quote))) == (
        f'evidence: the quote is not in the output of probe "{probe}"',
    )


def test_a_failed_probe_is_no_evidence_even_when_the_quote_is_there() -> None:
    evidence = ProbeQuote(probe="user-timers", quote="restic-backup.timer")

    assert dropped(finding(evidence=evidence)) == (
        'evidence: probe "user-timers" failed, so it is no evidence',
    )


@pytest.mark.parametrize(
    ("probe", "problem"),
    [
        ("http", 'evidence: no probe is called "http"'),
        ('a"b\nc', 'evidence: no probe is called "a\\"b\\nc"'),
    ],
)
def test_a_probe_quote_must_name_a_probe(probe: str, problem: str) -> None:
    assert dropped(finding(evidence=ProbeQuote(probe=probe, quote="x"))) == (problem,)


def test_another_docs_quote_is_checked_and_narrowed_like_the_doc() -> None:
    evidence = doc_quote("it also installs\nnoble-updates", 1, 5, file="notes/apt.md")
    item = finding(doc_quote(f"Updates are {LEFT}manual{RIGHT}", 5), evidence)

    result = kept(item)

    assert result.evidence == doc_quote(
        "it also installs\nnoble-updates", 3, 4, file="notes/apt.md"
    )
    assert result.doc == item.doc


def test_a_bad_quote_from_another_doc_is_an_evidence_problem() -> None:
    evidence = doc_quote("noble-security", 3, 4, file="notes/apt.md")

    assert dropped(finding(evidence=evidence)) == (
        "evidence: the quote is not in notes/apt.md:3-4",
    )


def test_every_problem_is_listed_doc_first() -> None:
    item = finding(doc_quote("at 04:00", 3), ProbeQuote(probe="http", quote="200"))

    assert dropped(item) == (
        "doc: the quote is not in docs/ops.md:3",
        'evidence: no probe is called "http"',
    )


def test_kept_and_dropped_findings_keep_their_order() -> None:
    first = finding(title="first")
    bad = finding(doc_quote("at 04:00", 3), title="bad")
    second = finding(doc_quote("02:00", 1, 7), title="second")
    worse = finding(evidence=ProbeQuote(probe="nope", quote="x"), title="worse")

    verification = verify([first, bad, second, worse], DOCS, RESULTS)

    assert [item.title for item in verification.findings] == ["first", "second"]
    assert [item.finding.title for item in verification.dropped] == ["bad", "worse"]


def test_no_findings_verify_to_nothing() -> None:
    verification = verify([], DOCS, RESULTS)

    assert (verification.findings, verification.dropped) == ((), ())


@pytest.mark.parametrize(
    ("quote", "location"),
    [
        (doc_quote("x", 3), "docs/ops.md:3"),
        (doc_quote("x", 3, 4), "docs/ops.md:3-4"),
    ],
)
def test_a_doc_quote_location_shows_a_range_only_when_there_is_one(
    quote: DocQuote, location: str
) -> None:
    assert quote.location == location
