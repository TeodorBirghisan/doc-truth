import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

from doc_truth.config import Acknowledgement, Probe
from doc_truth.evidence import Evidence, ProbeResult
from doc_truth.findings import (
    CitedLines,
    Confidence,
    DocQuote,
    Finding,
    Fix,
    Identity,
    Kind,
    ProbeOutput,
    ProbeQuote,
    normalised,
    parse_findings,
)
from doc_truth.known import Earlier, Tracked, earlier_json, finding_id, identity_json
from doc_truth.model import Answer
from doc_truth.report import Report, report_json, report_markdown, summary
from doc_truth.verify import Dropped

GOLDEN = Path(__file__).parent / "golden"
EEST = timezone(timedelta(hours=3))


def probe_result(name: str, *, failure: str | None = None) -> ProbeResult:
    return ProbeResult(
        probe=Probe(
            name=name, command="true", timeout=30.0, success_exit_codes=frozenset({0}), notes=None
        ),
        stdout="",
        stderr="",
        exit_code=0 if failure is None else 1,
        signal=None,
        duration=0.1,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        failure=failure,
    )


def evidence(*results: ProbeResult) -> Evidence:
    return Evidence(
        tool_version="0.1.0",
        host="homeserver",
        user="ops",
        timezone="EEST",
        utc_offset="+03:00",
        started_at=datetime(2026, 10, 13, 10, 5, 9, 250000, tzinfo=EEST),
        finished_at=datetime(2026, 10, 13, 7, 5, 11, tzinfo=UTC),
        config_path=Path("/etc/doc-truth/doc-truth.toml"),
        results=results,
    )


def doc(file: str, line: int, quote: str, end_line: int | None = None) -> DocQuote:
    return DocQuote(
        file=file, line=line, end_line=line if end_line is None else end_line, quote=quote
    )


def finding(
    title: str,
    at: DocQuote,
    evidence: ProbeQuote | DocQuote,
    *,
    kind: Kind = Kind.CONTRADICTION,
    confidence: Confidence = Confidence.CONFIRMED,
    fix: Fix = Fix.DOC,
    reason: str = "The evidence shows otherwise.",
) -> Finding:
    return Finding(
        kind=kind,
        title=title,
        doc=at,
        evidence=evidence,
        confidence=confidence,
        fix=fix,
        reason=reason,
    )


def answer(*models: str, input_tokens: int = 0, output_tokens: int = 0, cost: float = 0) -> Answer:
    return Answer(
        text='{"findings": []}',
        models=models,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        duration=12.34567,
    )


def identity_of(found: Finding) -> Identity:
    evidence = found.evidence
    return Identity(
        kind=found.kind,
        doc=CitedLines(file=found.doc.file, lines=frozenset({normalised(found.doc.quote)})),
        evidence=(
            ProbeOutput(probe=evidence.probe, lines=frozenset({normalised(evidence.quote)}))
            if isinstance(evidence, ProbeQuote)
            else CitedLines(file=evidence.file, lines=frozenset({normalised(evidence.quote)}))
        ),
    )


def tracked(
    found: Finding,
    *,
    runs_open: int = 1,
    acknowledgement: Acknowledgement | None = None,
    note: str | None = None,
) -> Tracked:
    return Tracked(
        id=finding_id(identity_of(found)) if acknowledgement is None else acknowledgement.id,
        finding=found,
        identity=identity_of(found),
        runs_open=runs_open,
        acknowledgement=acknowledgement,
        note=note,
    )


def tracking_json(
    found: Finding, *, runs_open: int = 1, note: str | None = None
) -> dict[str, object]:
    identity = identity_of(found)
    return {
        "id": finding_id(identity),
        "runs_open": runs_open,
        "acknowledged": False,
        "note": note,
        "identity": identity_json(identity),
    }


OPERATIONS = "docs/operations.md"
APT = "docs/apt.md"
SUSPECT_UPDATES = finding(
    "Unattended upgrades may run on another schedule",
    doc(OPERATIONS, 9, "Upgrades run every Sunday."),
    ProbeQuote(probe="apt-timers", quote="apt-daily-upgrade.timer"),
    kind=Kind.STALE_STATUS,
    confidence=Confidence.SUSPECT,
    fix=Fix.HOST,
    reason="The timer exists, but its schedule isn't shown.",
)
APT_SCOPE = finding(
    "The apt notes still call noble-updates manual",
    doc(APT, 4, "noble-updates is installed by hand"),
    doc(OPERATIONS, 20, "Since 2026-08-24 it also installs\nnoble-updates.", 21),
    kind=Kind.CROSS_DOC_CONTRADICTION,
)
EXPORTER = finding(
    "node_exporter is\n  version 1.9.1,   not 1.8.2",
    doc(OPERATIONS, 12, "Monitoring uses `node_exporter`\n1.8.2.", 13),
    ProbeQuote(probe="exporter", quote="node_exporter, version 1.9.1 ```"),
    reason="```json\nThe doc pins 1.8.2; the binary reports 1.9.1.",
)
BACKUP = finding(
    "Backup timer runs at 03:00, not 02:00",
    doc(OPERATIONS, 3, "restic backs up nightly at 02:00"),
    ProbeQuote(probe="systemd-timers", quote="*-*-* 03:00:00"),
)
SNAPSHOTS = finding(
    "Snapshots run hourly, not daily",
    doc(OPERATIONS, 15, "Snapshots run daily."),
    ProbeQuote(probe="systemd-timers", quote="timeshift-hourly.timer"),
)
SNAPSHOTS_KNOWN = Acknowledgement(
    id="1f2e3d4c",
    title=SNAPSHOTS.title,
    confidence=Confidence.CONFIRMED,
    reason="Hourly on purpose\n  until the migration ends.",
    acknowledged=date(2026, 10, 1),
    until=date(2026, 12, 1),
    identity=identity_of(SNAPSHOTS),
)
OLD_NOTE = (
    "An acknowledgement of this ran out on 2026-10-01, so it counts again. "
    "Its reason was: Waiting for the new exporter."
)
FIXED = Earlier(
    id="aaaa1111",
    title="Caddy\nlistens on 8443",
    confidence=Confidence.CONFIRMED,
    identity=identity_of(BACKUP),
    runs_open=2,
    acknowledged=False,
)
FIXED_AND_KNOWN = Earlier(
    id="bbbb2222",
    title="Grafana is on 11",
    confidence=Confidence.CONFIRMED,
    identity=identity_of(BACKUP),
    runs_open=0,
    acknowledged=True,
)
UNCHECKED = Earlier(
    id="cccc3333",
    title="No user timers are set up",
    confidence=Confidence.CONFIRMED,
    identity=identity_of(BACKUP),
    runs_open=4,
    acknowledged=False,
)
LEFT_THE_CONFIG = Earlier(
    id="dddd4444",
    title="The old runbook says nightly",
    confidence=Confidence.CONFIRMED,
    identity=identity_of(BACKUP),
    runs_open=1,
    left_config=True,
)
DROPPED_ON_A_FAILED_PROBE = Dropped(
    finding=finding(
        "No user timers are set up",
        doc(OPERATIONS, 30, "User timers back up the laptop."),
        ProbeQuote(probe="user-timers", quote="0 timers listed."),
        kind=Kind.OMISSION,
    ),
    problems=('evidence: probe "user-timers" failed, so it is no evidence',),
)
DROPPED_WITH_INVENTED_NAMES = Dropped(
    finding=finding(
        "Caddy\nlistens on 8443",
        doc("docs/net`work.md", 2, "Caddy listens on 443"),
        ProbeQuote(probe='caddy\n"ports"', quote="```\n:8443"),
    ),
    problems=(
        'doc: "docs/net`work.md" is not one of the checked docs',
        'evidence: no probe is called "caddy\\n\\"ports\\""',
    ),
)


def full_report() -> Report:
    return Report(
        evidence=evidence(
            probe_result("systemd-timers"),
            probe_result("exporter"),
            probe_result("user-timers", failure="exit code 1 is not in success-exit-codes [0]"),
            probe_result("sitemap", failure="timed out after 15s"),
        ),
        docs=(OPERATIONS, APT),
        prompt_version=1,
        requested_model="sonnet",
        answers=(
            answer("claude-sonnet-5-5", input_tokens=12000, output_tokens=900, cost=0.031),
            answer(
                "claude-haiku-5-5",
                "claude-sonnet-5-5",
                input_tokens=3210,
                output_tokens=120,
                cost=0.0125,
            ),
        ),
        findings=(
            tracked(SUSPECT_UPDATES),
            tracked(APT_SCOPE),
            tracked(EXPORTER, runs_open=3, note=OLD_NOTE),
            tracked(BACKUP),
            tracked(SNAPSHOTS, runs_open=5, acknowledgement=SNAPSHOTS_KNOWN),
        ),
        dropped=(DROPPED_ON_A_FAILED_PROBE, DROPPED_WITH_INVENTED_NAMES),
        finished_at=datetime(2026, 10, 13, 7, 6, 2, tzinfo=UTC),
        previous_run="20261006T070500Z",
        no_longer_reported=(FIXED, FIXED_AND_KNOWN),
        not_rechecked=(UNCHECKED, LEFT_THE_CONFIG),
    )


ONE_PROBE = evidence(probe_result("systemd-timers"))
ONE_CALL = (answer("claude-sonnet-5-5", input_tokens=1500, output_tokens=40, cost=0.004),)


def small_report(
    *,
    collected: Evidence = ONE_PROBE,
    docs: tuple[str, ...] = (OPERATIONS,),
    answers: tuple[Answer, ...] = ONE_CALL,
    findings: tuple[Finding, ...] = (),
    dropped: tuple[Dropped, ...] = (),
) -> Report:
    return Report(
        evidence=collected,
        docs=docs,
        prompt_version=1,
        requested_model="sonnet",
        answers=answers,
        findings=tuple(tracked(found) for found in findings),
        dropped=dropped,
        finished_at=datetime(2026, 10, 13, 7, 5, 40, tzinfo=UTC),
    )


def test_the_markdown_report() -> None:
    assert report_markdown(full_report()) == (GOLDEN / "report.md").read_text(encoding="utf-8")


def test_a_clean_report_says_so_and_lists_what_was_checked() -> None:
    assert report_markdown(small_report()) == (
        "# doc-truth report for `homeserver`\n"
        "\n"
        "**No findings.**\n"
        "\n"
        "Checked 2026-10-13 07:05:09 UTC by doc-truth 0.1.0: 1 doc, 1 probe.\n"
        "Model: claude-sonnet-5-5 (1 call, 1,500 tokens in, 40 out, "
        "$0.00 as reported by Claude Code).\n"
        "\n"
        "## Docs checked\n"
        "\n"
        "- `docs/operations.md`\n"
    )


def test_findings_are_ordered_by_confidence_then_by_doc_and_line() -> None:
    report = full_report()

    assert [item.finding for item in report.confirmed] == [BACKUP, EXPORTER, APT_SCOPE]
    assert [item.finding for item in report.suspect] == [SUSPECT_UPDATES]
    assert [item.finding for item in report.acknowledged] == [SNAPSHOTS]


def test_findings_in_one_doc_go_by_first_line_then_last_line_then_model_order() -> None:
    later = replace(BACKUP, title="later", doc=doc(OPERATIONS, 5, "restic"))
    longest = replace(BACKUP, title="longest", doc=doc(OPERATIONS, 2, "restic", 9))
    two_lines = replace(BACKUP, title="two lines", doc=doc(OPERATIONS, 3, "nightly", 4))
    first_tie = replace(BACKUP, title="first tie", doc=doc(OPERATIONS, 3, "restic"))
    second_tie = replace(BACKUP, title="second tie", doc=doc(OPERATIONS, 3, "backs up"))

    report = small_report(findings=(later, longest, two_lines, first_tie, second_tie))

    assert [item.finding.title for item in report.confirmed] == [
        "longest",
        "first tie",
        "second tie",
        "two lines",
        "later",
    ]


def test_the_summary_counts_in_words() -> None:
    assert summary(full_report()) == (
        "4 findings: 3 confirmed, 1 suspect. 3 new. 1 acknowledged. 2 no longer reported. "
        "2 not rechecked. 2 probes failed. 2 findings dropped."
    )
    assert summary(
        small_report(
            collected=evidence(probe_result("x", failure="timed out after 30s")),
            findings=(BACKUP,),
            dropped=(DROPPED_ON_A_FAILED_PROBE,),
        )
    ) == ("1 finding: 1 confirmed, 0 suspect. 1 probe failed. 1 finding dropped.")
    assert summary(small_report(findings=(SUSPECT_UPDATES,))) == (
        "1 finding: 0 confirmed, 1 suspect."
    )
    assert summary(small_report()) == "No findings."


def test_the_summary_only_counts_new_findings_when_there_is_a_run_to_compare_with() -> None:
    compared = replace(small_report(findings=(BACKUP,)), previous_run="20261006T070500Z")
    repeat = replace(compared, findings=(tracked(BACKUP, runs_open=2),))
    clean = replace(small_report(), previous_run="20261006T070500Z")

    assert summary(compared) == "1 finding: 1 confirmed, 0 suspect. 1 new."
    assert summary(repeat) == "1 finding: 1 confirmed, 0 suspect. 0 new."
    assert summary(clean) == "No findings."


def test_an_acknowledged_finding_leaves_the_counts_and_shows_its_reason() -> None:
    report = replace(
        small_report(), findings=(tracked(SNAPSHOTS, acknowledgement=SNAPSHOTS_KNOWN),)
    )

    markdown = report_markdown(report)

    assert report.confirmed == ()
    assert summary(report) == "No findings. 1 acknowledged."
    assert "· Confirmed, acknowledged on 2026-10-01 until 2026-12-01 ·" in markdown
    assert "\n\nReason: Hourly on purpose until the migration ends.\n\n" in markdown
    assert "`docs/operations.md:15` says:" in markdown


def test_an_acknowledgement_without_an_end_date_says_so() -> None:
    forever = replace(SNAPSHOTS_KNOWN, until=None)
    report = replace(small_report(), findings=(tracked(SNAPSHOTS, acknowledgement=forever),))

    assert "· Confirmed, acknowledged on 2026-10-01 · Contradiction ·" in report_markdown(report)


def test_a_known_entry_that_left_the_config_says_to_delete_it_not_that_it_goes_away() -> None:
    report = replace(
        small_report(), not_rechecked=(replace(FIXED_AND_KNOWN, from_known=True, left_config=True),)
    )

    assert (
        ": Grafana is on 11 (its doc or probe left the config; delete its entry to stop "
        "listing it)\n" in report_markdown(report)
    )
    assert "only this once" not in report_markdown(report)


def test_earlier_titles_cannot_start_a_line_of_their_own() -> None:
    report = replace(small_report(), no_longer_reported=(FIXED,))

    assert "\n- `aaaa1111` in `docs/operations.md`: Caddy listens on 8443\n" in report_markdown(
        report
    )


def test_the_requested_model_is_named_when_claude_code_lists_none() -> None:
    markdown = report_markdown(small_report(answers=(answer(),)))

    assert "\nModel: sonnet (1 call, 0 tokens in, 0 out, $0.00 as reported" in markdown


def test_the_json_report() -> None:
    data = json.loads(report_json(full_report()))

    assert data == {
        "format": 2,
        "doc_truth_version": "0.1.0",
        "prompt_version": 1,
        "host": "homeserver",
        "started_at": "2026-10-13T07:05:09Z",
        "finished_at": "2026-10-13T07:06:02Z",
        "config": "/etc/doc-truth/doc-truth.toml",
        "compared_with": "20261006T070500Z",
        "counts": {
            "confirmed": 3,
            "suspect": 1,
            "new": 3,
            "acknowledged": 1,
            "no_longer_reported": 2,
            "not_rechecked": 2,
            "dropped": 2,
            "failed_probes": 2,
        },
        "model": {
            "requested": "sonnet",
            "calls": [
                {
                    "models": ["claude-sonnet-5-5"],
                    "input_tokens": 12000,
                    "output_tokens": 900,
                    "cost_usd": 0.031,
                    "duration": 12.346,
                },
                {
                    "models": ["claude-haiku-5-5", "claude-sonnet-5-5"],
                    "input_tokens": 3210,
                    "output_tokens": 120,
                    "cost_usd": 0.0125,
                    "duration": 12.346,
                },
            ],
        },
        "docs": ["docs/operations.md", "docs/apt.md"],
        "failed_probes": [
            {"name": "user-timers", "failure": "exit code 1 is not in success-exit-codes [0]"},
            {"name": "sitemap", "failure": "timed out after 15s"},
        ],
        "findings": [
            {
                **tracking_json(BACKUP),
                "kind": "contradiction",
                "title": "Backup timer runs at 03:00, not 02:00",
                "doc": {
                    "file": "docs/operations.md",
                    "line": 3,
                    "end_line": 3,
                    "quote": "restic backs up nightly at 02:00",
                },
                "evidence": {"probe": "systemd-timers", "quote": "*-*-* 03:00:00"},
                "confidence": "confirmed",
                "fix": "doc",
                "reason": "The evidence shows otherwise.",
            },
            {
                **tracking_json(EXPORTER, runs_open=3, note=OLD_NOTE),
                "kind": "contradiction",
                "title": "node_exporter is\n  version 1.9.1,   not 1.8.2",
                "doc": {
                    "file": "docs/operations.md",
                    "line": 12,
                    "end_line": 13,
                    "quote": "Monitoring uses `node_exporter`\n1.8.2.",
                },
                "evidence": {"probe": "exporter", "quote": "node_exporter, version 1.9.1 ```"},
                "confidence": "confirmed",
                "fix": "doc",
                "reason": "```json\nThe doc pins 1.8.2; the binary reports 1.9.1.",
            },
            {
                **tracking_json(APT_SCOPE),
                "kind": "cross-doc-contradiction",
                "title": "The apt notes still call noble-updates manual",
                "doc": {
                    "file": "docs/apt.md",
                    "line": 4,
                    "end_line": 4,
                    "quote": "noble-updates is installed by hand",
                },
                "evidence": {
                    "file": "docs/operations.md",
                    "line": 20,
                    "end_line": 21,
                    "quote": "Since 2026-08-24 it also installs\nnoble-updates.",
                },
                "confidence": "confirmed",
                "fix": "doc",
                "reason": "The evidence shows otherwise.",
            },
            {
                **tracking_json(SUSPECT_UPDATES),
                "kind": "stale-status",
                "title": "Unattended upgrades may run on another schedule",
                "doc": {
                    "file": "docs/operations.md",
                    "line": 9,
                    "end_line": 9,
                    "quote": "Upgrades run every Sunday.",
                },
                "evidence": {"probe": "apt-timers", "quote": "apt-daily-upgrade.timer"},
                "confidence": "suspect",
                "fix": "host",
                "reason": "The timer exists, but its schedule isn't shown.",
            },
            {
                **tracking_json(SNAPSHOTS, runs_open=5),
                "id": "1f2e3d4c",
                "acknowledged": True,
                "acknowledgement": {
                    "reason": "Hourly on purpose\n  until the migration ends.",
                    "acknowledged": "2026-10-01",
                    "until": "2026-12-01",
                },
                "kind": "contradiction",
                "title": "Snapshots run hourly, not daily",
                "doc": {
                    "file": "docs/operations.md",
                    "line": 15,
                    "end_line": 15,
                    "quote": "Snapshots run daily.",
                },
                "evidence": {"probe": "systemd-timers", "quote": "timeshift-hourly.timer"},
                "confidence": "confirmed",
                "fix": "doc",
                "reason": "The evidence shows otherwise.",
            },
        ],
        "no_longer_reported": [earlier_json(FIXED), earlier_json(FIXED_AND_KNOWN)],
        "not_rechecked": [earlier_json(UNCHECKED), earlier_json(LEFT_THE_CONFIG)],
        "dropped": [
            {
                "finding": {
                    "kind": "omission",
                    "title": "No user timers are set up",
                    "doc": {
                        "file": "docs/operations.md",
                        "line": 30,
                        "end_line": 30,
                        "quote": "User timers back up the laptop.",
                    },
                    "evidence": {"probe": "user-timers", "quote": "0 timers listed."},
                    "confidence": "confirmed",
                    "fix": "doc",
                    "reason": "The evidence shows otherwise.",
                },
                "problems": ['evidence: probe "user-timers" failed, so it is no evidence'],
            },
            {
                "finding": {
                    "kind": "contradiction",
                    "title": "Caddy\nlistens on 8443",
                    "doc": {
                        "file": "docs/net`work.md",
                        "line": 2,
                        "end_line": 2,
                        "quote": "Caddy listens on 443",
                    },
                    "evidence": {"probe": 'caddy\n"ports"', "quote": "```\n:8443"},
                    "confidence": "confirmed",
                    "fix": "doc",
                    "reason": "The evidence shows otherwise.",
                },
                "problems": [
                    'doc: "docs/net`work.md" is not one of the checked docs',
                    'evidence: no probe is called "caddy\\n\\"ports\\""',
                ],
            },
        ],
    }


def test_the_json_findings_use_the_format_the_model_answers_in() -> None:
    report = full_report()
    data = json.loads(report_json(report))

    assert parse_findings({"findings": data["findings"]}) == tuple(
        item.finding for item in (*report.confirmed, *report.suspect, *report.acknowledged)
    )
    assert parse_findings({"findings": [item["finding"] for item in data["dropped"]]}) == tuple(
        item.finding for item in report.dropped
    )


def test_the_json_keeps_text_readable() -> None:
    report = small_report(docs=("docs/café.md",), findings=())

    text = report_json(report)

    assert '"docs/café.md"' in text
    assert text.endswith("}\n")


def test_an_acknowledged_finding_says_how_sure_the_model_is() -> None:
    suspect = replace(SNAPSHOTS, confidence=Confidence.SUSPECT)
    report = replace(small_report(), findings=(tracked(suspect, acknowledgement=SNAPSHOTS_KNOWN),))

    assert "· Suspect, acknowledged on 2026-10-01 until 2026-12-01 ·" in report_markdown(report)
