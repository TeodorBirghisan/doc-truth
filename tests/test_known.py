import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from doc_truth.config import (
    Acknowledgement,
    Config,
    ConfigError,
    Doc,
    Probe,
    known_path,
    load_known,
)
from doc_truth.evidence import ProbeResult
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
)
from doc_truth.known import (
    AckError,
    Earlier,
    PreviousReport,
    Tracking,
    acknowledge,
    already_acknowledged,
    append_known,
    covers,
    earlier_from_json,
    earlier_json,
    finding_id,
    identify,
    identity_json,
    known_toml,
    same_finding,
    track,
)
from doc_truth.prompt import DocText
from doc_truth.verify import Dropped

TODAY = date(2026, 11, 2)
LEFT, RIGHT, LINE_SEPARATOR = "\u2018", "\u2019", "\u2028"
OPERATIONS = "docs/operations.md"
APT = "notes/apt.md"
OPERATIONS_LINES = (
    "# Operations",
    "",
    "## 3. What runs automatically",
    "",
    "| every 5 minutes | Nextcloud background jobs | `nextcloud-cron.timer` |",
    "| hourly, 09:00-21:00 | Timeshift snapshot check | `0 9-21 * * *` |",
    "",
    "Not set up yet. The plan is to copy the local repository to Backblaze B2.",
    "Until then, losing both disks loses the backups.",
    "",
    "Unattended upgrades cover security and ESM; other updates are installed by hand.",
)
APT_LINES = (
    "# Apt",
    "",
    "Since 2026-08-24 it also installs from `noble-updates`, so regular",
    "updates arrive by themselves.",
    "",
    "Pinned packages stay on hold.",
)


def doc_text(path: str, lines: Sequence[str]) -> DocText:
    return DocText(doc=Doc(path=Path(path), display_path=path, notes=()), lines=tuple(lines))


DOCS = (doc_text(OPERATIONS, OPERATIONS_LINES), doc_text(APT, APT_LINES))
OUTPUT = """0 * * * * root timeshift --check
@reboot root sleep 10m && timeshift --create --scripted
0 3 * * * root restic backup /srv
nextcloud-cron.timer { OnCalendar=*:0/15 ; }
"""


def probe_result(name: str, *, failure: str | None = None, stdout: str = "") -> ProbeResult:
    return ProbeResult(
        probe=Probe(
            name=name, command="true", timeout=30.0, success_exit_codes=frozenset({0}), notes=None
        ),
        stdout=stdout,
        stderr="",
        exit_code=0 if failure is None else 1,
        signal=None,
        duration=0.1,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        failure=failure,
    )


RESULTS = (probe_result("cron-d", stdout=OUTPUT), probe_result("timers", stdout=OUTPUT))
TIMESHIFT = ProbeQuote(probe="cron-d", quote="0 * * * * root timeshift")
RESTIC = ProbeQuote(probe="cron-d", quote="0 3 * * * root restic")


def finding(
    line: int,
    *,
    end_line: int | None = None,
    quote: str = "quote",
    file: str = OPERATIONS,
    evidence: ProbeQuote | DocQuote | None = None,
    kind: Kind = Kind.CONTRADICTION,
    title: str = "A title",
    confidence: Confidence = Confidence.CONFIRMED,
) -> Finding:
    return Finding(
        kind=kind,
        title=title,
        doc=DocQuote(file=file, line=line, end_line=end_line or line, quote=quote),
        evidence=evidence or ProbeQuote(probe="cron-d", quote="0 * * * * root timeshift"),
        confidence=confidence,
        fix=Fix.DOC,
        reason="A reason.",
    )


def identity(
    found: Finding, docs: Sequence[DocText] = DOCS, results: Sequence[ProbeResult] = RESULTS
) -> Identity:
    return identify(found, docs, results)


def other_doc(line: int, end_line: int | None = None, file: str = APT) -> DocQuote:
    return DocQuote(file=file, line=line, end_line=end_line or line, quote="quote")


def acknowledgement(
    found: Finding, *, until: date | None = None, results: Sequence[ProbeResult] = RESULTS
) -> Acknowledgement:
    return Acknowledgement(
        id=finding_id(identity(found, results=results)),
        title=found.title,
        confidence=found.confidence,
        reason="On purpose.",
        acknowledged=date(2026, 10, 1),
        until=until,
        identity=identity(found, results=results),
    )


def earlier(found: Finding, *, runs_open: int = 1, acknowledged: bool = False) -> Earlier:
    return Earlier(
        id=finding_id(identity(found)),
        title=found.title,
        confidence=found.confidence,
        identity=identity(found),
        runs_open=runs_open,
        acknowledged=acknowledged,
    )


def previous(*items: Earlier) -> PreviousReport:
    return PreviousReport(run="20261026T080000Z", findings=items)


def tracking(
    *findings: Finding,
    dropped: Sequence[Dropped] = (),
    docs: Sequence[DocText] = DOCS,
    results: Sequence[ProbeResult] = RESULTS,
    known: Sequence[Acknowledgement] = (),
    before: PreviousReport | None = None,
    today: date = TODAY,
) -> Tracking:
    return track(
        findings,
        dropped=dropped,
        docs=docs,
        results=results,
        known=known,
        previous=before,
        today=today,
    )


def test_different_words_quoted_from_one_table_row_are_the_same_finding() -> None:
    a = finding(6, quote="hourly, 09:00-21:00")
    b = finding(6, quote="`0 9-21 * * *`")

    assert same_finding(identity(a), identity(b))


def test_a_longer_or_shorter_evidence_quote_is_the_same_finding() -> None:
    a = finding(5, evidence=ProbeQuote(probe="cron-d", quote="nextcloud-cron.timer {"))
    b = finding(5, evidence=ProbeQuote(probe="cron-d", quote="OnCalendar=*:0/15"))

    assert identity(a) == identity(b)
    assert same_finding(identity(a), identity(b))
    assert covers(identity(a), identity(b))


def test_citations_that_share_one_line_are_the_same_finding() -> None:
    one_line = finding(8)
    two_lines = finding(8, end_line=9)

    assert same_finding(identity(one_line), identity(two_lines))


def test_an_edit_elsewhere_in_the_doc_does_not_change_the_finding() -> None:
    moved = doc_text(OPERATIONS, ("# Operations", "Intro added later.", *OPERATIONS_LINES[1:]))

    assert same_finding(identity(finding(6)), identity(finding(7), [moved]))


def test_spacing_and_curly_quotes_in_a_line_do_not_change_the_finding() -> None:
    respaced = doc_text(OPERATIONS, (f"Unattended   upgrades {LEFT}cover{RIGHT} it.",))
    original = doc_text(OPERATIONS, ("Unattended upgrades 'cover' it.",))

    assert same_finding(identity(finding(1), [respaced]), identity(finding(1), [original]))


def test_editing_the_claims_own_line_makes_a_new_finding() -> None:
    edited = doc_text(
        OPERATIONS,
        (*OPERATIONS_LINES[:5], "| hourly, 08:00-20:00 | Timeshift |", *OPERATIONS_LINES[6:]),
    )

    assert not same_finding(identity(finding(6)), identity(finding(6), [edited]))


@pytest.mark.parametrize(
    ("before", "quoted_before", "after", "quoted_after"),
    [
        ("tool 1.2\n", "tool 1.2", "tool 1.20\n", "tool 1.20"),
        ("nginx active\n", "active", "nginx inactive (dead)\n", "inactive"),
        (
            "backup.timer active waiting OnCalendar=03:00\n",
            "backup.timer active",
            "backup.timer active waiting OnCalendar=04:00\n",
            "backup.timer active",
        ),
    ],
)
def test_an_acknowledgement_ends_when_its_whole_line_of_output_changes(
    before: str, quoted_before: str, after: str, quoted_after: str
) -> None:
    known = acknowledgement(
        finding(6, evidence=ProbeQuote(probe="cron-d", quote=quoted_before)),
        results=[probe_result("cron-d", stdout=before)],
    )
    found = finding(6, evidence=ProbeQuote(probe="cron-d", quote=quoted_after))

    (item,) = tracking(
        found, known=[known], results=[probe_result("cron-d", stdout=after)]
    ).findings

    assert item.acknowledgement is None
    assert item.note is not None
    assert "what it rests on has changed" in item.note


def test_a_quote_that_cuts_a_word_can_be_acknowledged() -> None:
    output = [probe_result("cron-d", stdout="backup.timer OnCalendar=03:00:00\n")]
    cut = finding(6, evidence=ProbeQuote(probe="cron-d", quote="OnCalendar=03:00"))

    (item,) = tracking(cut, known=[acknowledgement(cut, results=output)], results=output).findings

    assert item.acknowledgement is not None


def test_a_quote_across_lines_cites_each_of_them() -> None:
    output = [probe_result("cron-d", stdout="first line\nsecond line\nthird line\n")]
    across = finding(6, evidence=ProbeQuote(probe="cron-d", quote="line second"))

    assert identity(across, results=output).evidence == ProbeOutput(
        probe="cron-d", lines=frozenset({"first line", "second line"})
    )


def test_a_quote_can_come_from_standard_error() -> None:
    result = replace(probe_result("cron-d", stdout="out\n"), stderr="warning: disk\n")
    quoted = finding(6, evidence=ProbeQuote(probe="cron-d", quote="warning: disk"))

    assert identity(quoted, results=[result]).evidence == ProbeOutput(
        probe="cron-d", lines=frozenset({"warning: disk"})
    )


def test_a_quote_nowhere_in_the_output_is_a_bug_verification_should_have_caught() -> None:
    with pytest.raises(ValueError, match="not in the output of probe cron-d"):
        identity(finding(6, evidence=ProbeQuote(probe="cron-d", quote="nope")))


def test_a_shared_code_fence_or_table_rule_does_not_make_two_findings_one() -> None:
    table = doc_text(
        OPERATIONS,
        (
            "| Job |",
            "|---|",
            "| Backup |",
            "",
            "| Port |",
            "|---|",
            "| 443 |",
            "",
            "```",
            "x",
            "```",
        ),
    )

    a = identity(finding(1, end_line=2), [table])
    b = identity(finding(5, end_line=6), [table])

    assert not same_finding(a, b)
    assert a.doc.lines == frozenset({"| Job |"})


def test_a_citation_of_only_punctuation_leaves_out_blank_lines() -> None:
    table = doc_text(OPERATIONS, ("|---|", ""))

    assert identity(finding(1, end_line=2), [table]).doc.lines == frozenset({"|---|"})


def test_a_quote_is_looked_up_in_the_output_of_its_own_probe() -> None:
    other = probe_result("timers", stdout="restic.timer on another probe\n")
    mine = probe_result("cron-d", stdout="restic.timer on this probe\n")
    quoted = finding(6, evidence=ProbeQuote(probe="cron-d", quote="restic.timer"))

    assert identity(quoted, results=[other, mine]).evidence == ProbeOutput(
        probe="cron-d", lines=frozenset({"restic.timer on this probe"})
    )


def test_a_citation_of_only_punctuation_still_has_lines() -> None:
    table = doc_text(OPERATIONS, ("|---|",))

    assert identity(finding(1), [table]).doc.lines == frozenset({"|---|"})


def test_the_same_text_in_another_doc_is_another_finding() -> None:
    other = doc_text("docs/backups.md", OPERATIONS_LINES)

    a = identity(finding(6))
    b = identity(finding(6, file="docs/backups.md"), [other])

    assert not same_finding(a, b)
    assert not covers(a, b)


def test_another_probe_is_another_finding() -> None:
    a = identity(finding(6))
    b = identity(finding(6, evidence=ProbeQuote(probe="timers", quote="0 * * * * root timeshift")))

    assert not same_finding(a, b)
    assert not covers(a, b)


def test_omissions_under_one_heading_are_told_apart_by_their_evidence() -> None:
    boot = finding(
        3,
        kind=Kind.OMISSION,
        evidence=ProbeQuote(probe="cron-d", quote="@reboot root sleep 10m && timeshift --create"),
    )
    boot_longer = finding(
        3,
        kind=Kind.OMISSION,
        evidence=ProbeQuote(
            probe="cron-d", quote="@reboot root sleep 10m && timeshift --create --scripted"
        ),
    )
    backup = finding(
        3,
        kind=Kind.OMISSION,
        evidence=ProbeQuote(probe="cron-d", quote="0 3 * * * root restic backup /srv"),
    )

    assert same_finding(identity(boot), identity(boot_longer))
    assert not same_finding(identity(boot), identity(backup))
    assert not covers(identity(boot), identity(backup))


def test_one_omission_kind_is_enough_to_compare_the_evidence() -> None:
    omission = finding(
        3, kind=Kind.OMISSION, evidence=ProbeQuote(probe="cron-d", quote="@reboot root")
    )
    contradiction = finding(3, evidence=ProbeQuote(probe="cron-d", quote="0 3 * * * root"))

    assert not same_finding(identity(omission), identity(contradiction))
    assert not same_finding(identity(contradiction), identity(omission))


def test_a_cross_doc_finding_is_the_same_with_the_docs_swapped() -> None:
    a = finding(11, kind=Kind.CROSS_DOC_CONTRADICTION, evidence=other_doc(3))
    b = finding(
        3,
        file=APT,
        kind=Kind.CROSS_DOC_CONTRADICTION,
        evidence=other_doc(11, file=OPERATIONS),
    )

    assert same_finding(identity(a), identity(b))
    assert covers(identity(a), identity(b))


def test_a_cross_doc_finding_is_the_same_when_one_side_matches() -> None:
    a = finding(11, kind=Kind.CROSS_DOC_CONTRADICTION, evidence=other_doc(3))
    b = finding(11, kind=Kind.CROSS_DOC_CONTRADICTION, evidence=other_doc(6))

    assert same_finding(identity(a), identity(b))


def test_a_conflict_with_a_third_doc_is_another_finding() -> None:
    changelog = "notes/changelog.md"
    docs = (*DOCS, doc_text(changelog, ("Regular updates are automatic.",)))
    a = finding(11, kind=Kind.CROSS_DOC_CONTRADICTION, evidence=other_doc(3))
    b = finding(11, kind=Kind.CROSS_DOC_CONTRADICTION, evidence=other_doc(1, file=changelog))

    assert not same_finding(identity(a, docs), identity(b, docs))


def test_an_acknowledged_cross_doc_finding_needs_both_sides_to_match() -> None:
    a = finding(11, kind=Kind.CROSS_DOC_CONTRADICTION, evidence=other_doc(3))
    b = finding(11, kind=Kind.CROSS_DOC_CONTRADICTION, evidence=other_doc(6))

    assert not covers(identity(a), identity(b))


def test_spacing_in_a_line_of_output_does_not_change_the_finding() -> None:
    quoted = finding(6, evidence=ProbeQuote(probe="cron-d", quote="restic.timer 03:00:00"))
    tidy = identity(quoted, results=[probe_result("cron-d", stdout="restic.timer 03:00:00\n")])
    spaced = identity(quoted, results=[probe_result("cron-d", stdout="restic.timer    03:00:00\n")])

    assert tidy == spaced


def test_the_id_does_not_depend_on_the_order_of_a_set() -> None:
    cited = finding(5, end_line=11)

    lines = json.loads(json.dumps(identity_json(identity(cited))))["doc"]["lines"]

    assert lines == sorted(lines)
    assert len(lines) == 5


def test_a_probe_finding_and_a_cross_doc_finding_never_match() -> None:
    probe = identity(finding(11))
    cross_doc = identity(finding(11, kind=Kind.CROSS_DOC_CONTRADICTION, evidence=other_doc(3)))

    assert not same_finding(probe, cross_doc)
    assert not same_finding(cross_doc, probe)
    assert not covers(probe, cross_doc)
    assert not covers(cross_doc, probe)


def test_changed_evidence_is_the_same_finding_but_no_longer_covered() -> None:
    three = identity(
        finding(6, evidence=ProbeQuote(probe="cron-d", quote="timer 03:00:00")),
        results=[probe_result("cron-d", stdout="timer 03:00:00\n")],
    )
    four = identity(
        finding(6, evidence=ProbeQuote(probe="cron-d", quote="timer 04:00:00")),
        results=[probe_result("cron-d", stdout="timer 04:00:00\n")],
    )

    assert same_finding(three, four)
    assert not covers(three, four)


def test_blank_lines_in_a_citation_are_ignored() -> None:
    assert identity(finding(6, end_line=7)).doc.lines == frozenset(
        {"| hourly, 09:00-21:00 | Timeshift snapshot check | `0 9-21 * * *` |"}
    )


def test_the_id_depends_on_the_identity_alone() -> None:
    a = finding(6, title="One title", quote="hourly")
    same = finding(6, title="Another title", quote="`0 9-21 * * *`")
    other = finding(5)

    assert finding_id(identity(a)) == finding_id(identity(same))
    assert finding_id(identity(a)) != finding_id(identity(other))
    assert len(finding_id(identity(a))) == 8


def test_a_finding_with_no_previous_run_is_new() -> None:
    (item,) = tracking(finding(6)).findings

    assert item.runs_open == 1
    assert item.acknowledgement is None
    assert item.note is None


def test_a_finding_in_the_previous_run_adds_to_its_count() -> None:
    (item,) = tracking(finding(6), before=previous(earlier(finding(6), runs_open=3))).findings

    assert item.runs_open == 4


def test_findings_the_model_reorders_keep_their_own_past() -> None:
    a = finding(8, evidence=TIMESHIFT)
    b = finding(8, evidence=RESTIC)
    before = previous(earlier(a, runs_open=2), earlier(b, runs_open=5))

    b_item, a_item = tracking(b, a, before=before).findings

    assert (a_item.id, a_item.runs_open) == (finding_id(identity(a)), 3)
    assert (b_item.id, b_item.runs_open) == (finding_id(identity(b)), 6)


def test_an_identical_finding_is_paired_before_one_that_only_shares_its_line() -> None:
    same = finding(8, evidence=TIMESHIFT)
    neighbour = finding(8, evidence=RESTIC)

    neighbour_item, same_item = tracking(
        neighbour, same, before=previous(earlier(same, runs_open=4))
    ).findings

    assert same_item.runs_open == 5
    assert neighbour_item.runs_open == 1


def test_an_identical_finding_is_paired_before_one_that_covers_more_lines() -> None:
    same = finding(8, evidence=TIMESHIFT)
    before = previous(
        earlier(finding(8, end_line=9, evidence=TIMESHIFT), runs_open=2),
        earlier(same, runs_open=5),
    )

    (item,) = tracking(same, before=before).findings

    assert item.runs_open == 6


def test_a_finding_that_only_shares_its_line_with_an_earlier_one_is_still_open() -> None:
    before = previous(earlier(finding(8, evidence=TIMESHIFT), runs_open=2))

    (item,) = tracking(finding(8, evidence=RESTIC), before=before).findings

    assert item.runs_open == 3


def test_a_finding_on_the_same_output_line_is_paired_before_one_on_another() -> None:
    before = previous(
        earlier(finding(8, evidence=TIMESHIFT), runs_open=2),
        earlier(finding(8, evidence=RESTIC), runs_open=5),
    )

    (item,) = tracking(finding(8, end_line=9, evidence=RESTIC), before=before).findings

    assert item.runs_open == 6


def test_a_new_finding_that_shares_a_line_with_an_open_one_is_new() -> None:
    open_one = finding(8, evidence=TIMESHIFT)

    _, added = tracking(
        open_one, finding(8, evidence=RESTIC), before=previous(earlier(open_one, runs_open=3))
    ).findings

    assert added.runs_open == 1


def test_a_fixed_finding_that_shares_a_line_with_an_open_one_is_no_longer_reported() -> None:
    open_one = finding(8, evidence=TIMESHIFT)
    fixed = finding(8, evidence=RESTIC)

    result = tracking(open_one, before=previous(earlier(open_one), earlier(fixed)))

    assert [item.id for item in result.no_longer_reported] == [finding_id(identity(fixed))]


def test_earlier_findings_that_share_an_id_do_not_pass_it_on_twice() -> None:
    a = finding(8, evidence=TIMESHIFT)
    b = finding(8, evidence=RESTIC)
    before = previous(replace(earlier(a), id="shared"), replace(earlier(b), id="shared"))

    a_item, b_item = tracking(a, b, before=before).findings

    assert a_item.id == "shared"
    assert b_item.id == finding_id(identity(b))


def test_a_finding_seen_before_keeps_its_id_whatever_the_model_quotes() -> None:
    first = finding(8)
    (seen,) = tracking(first).findings
    longer = finding(8, end_line=9)

    (item,) = tracking(longer, before=previous(earlier(first))).findings

    assert item.id == seen.id
    assert finding_id(identity(longer)) != seen.id


def test_two_findings_that_match_one_earlier_finding_do_not_share_its_id() -> None:
    first = finding(8, end_line=9)
    one = finding(8)
    other = finding(9)

    one_item, other_item = tracking(one, other, before=previous(earlier(first))).findings

    assert one_item.id == finding_id(identity(first))
    assert other_item.id == finding_id(identity(other))


def test_findings_under_one_acknowledgement_share_its_id() -> None:
    known = replace(acknowledgement(finding(8, evidence=TIMESHIFT)), id="in-the-file")

    one, other = tracking(
        finding(8, evidence=TIMESHIFT),
        finding(8, end_line=9, evidence=TIMESHIFT),
        known=[known],
    ).findings

    assert (one.id, other.id) == ("in-the-file", "in-the-file")


def test_an_open_finding_does_not_take_the_id_of_an_acknowledged_one() -> None:
    covered = finding(8, evidence=TIMESHIFT)
    open_one = finding(8, evidence=RESTIC)
    known = replace(acknowledgement(covered), id="in-the-file")
    before = previous(
        replace(earlier(open_one), id="in-the-file"), replace(earlier(covered), id="in-the-file")
    )

    open_item, covered_item = tracking(open_one, covered, known=[known], before=before).findings

    assert covered_item.id == "in-the-file"
    assert open_item.id == finding_id(identity(open_one))


def test_a_new_finding_has_the_id_of_its_identity() -> None:
    (item,) = tracking(finding(6)).findings

    assert item.id == finding_id(identity(finding(6)))


def test_an_acknowledged_finding_shows_the_id_in_the_known_file() -> None:
    known = replace(acknowledgement(finding(6)), id="in-the-file")

    (item,) = tracking(finding(6), known=[known]).findings

    assert item.id == "in-the-file"


def test_a_live_acknowledgement_covers_a_finding() -> None:
    known = acknowledgement(finding(6))

    (item,) = tracking(finding(6), known=[known]).findings

    assert item.acknowledgement == known
    assert item.note is None


@pytest.mark.parametrize(
    ("until", "covered"),
    [
        (date(2026, 11, 3), True),
        (TODAY, True),
        (date(2026, 11, 1), False),
    ],
)
def test_an_acknowledgement_holds_through_its_last_day(until: date, covered: bool) -> None:
    (item,) = tracking(finding(6), known=[acknowledgement(finding(6), until=until)]).findings

    assert (item.acknowledgement is not None) == covered
    assert (item.note is None) == covered


def test_acknowledging_a_suspect_does_not_cover_it_once_it_is_confirmed() -> None:
    known = acknowledgement(finding(6, confidence=Confidence.SUSPECT))

    (item,) = tracking(finding(6), known=[known]).findings

    assert item.acknowledgement is None
    assert item.note == (
        "An acknowledgement from 2026-10-01 was given when this was only suspect. "
        "It's confirmed now, so it counts again. Its reason was: On purpose."
    )


@pytest.mark.parametrize(
    ("acknowledged_as", "found_as"),
    [
        (Confidence.SUSPECT, Confidence.SUSPECT),
        (Confidence.CONFIRMED, Confidence.CONFIRMED),
        (Confidence.CONFIRMED, Confidence.SUSPECT),
    ],
)
def test_an_acknowledgement_covers_a_finding_as_sure_or_less_sure(
    acknowledged_as: Confidence, found_as: Confidence
) -> None:
    known = acknowledgement(finding(6, confidence=acknowledged_as))

    (item,) = tracking(finding(6, confidence=found_as), known=[known]).findings

    assert item.acknowledgement == known
    assert item.note is None


def test_a_confirmed_acknowledgement_covers_a_finding_a_suspect_one_no_longer_does() -> None:
    suspect = acknowledgement(finding(6, confidence=Confidence.SUSPECT))
    confirmed = acknowledgement(finding(6))

    (item,) = tracking(finding(6), known=[suspect, confirmed]).findings

    assert item.acknowledgement == confirmed


def test_an_expired_acknowledgement_counts_again_and_says_so() -> None:
    known = acknowledgement(finding(6), until=date(2026, 10, 15))

    (item,) = tracking(finding(6), known=[known]).findings

    assert item.note == (
        "An acknowledgement of this ran out on 2026-10-15, so it counts again. "
        "Its reason was: On purpose."
    )


def test_a_live_acknowledgement_wins_over_an_expired_one_for_the_same_finding() -> None:
    expired = acknowledgement(finding(6), until=date(2026, 10, 15))
    live = acknowledgement(finding(6))

    (item,) = tracking(finding(6), known=[expired, live]).findings

    assert item.acknowledgement == live


def test_changed_evidence_on_an_acknowledged_finding_counts_again_and_says_so() -> None:
    before = [probe_result("cron-d", stdout="timer *-*-* 03:00:00\n")]
    known = acknowledgement(
        finding(6, evidence=ProbeQuote(probe="cron-d", quote="*-*-* 03:00:00")), results=before
    )
    found = finding(6, evidence=ProbeQuote(probe="cron-d", quote="*-*-* 04:00:00"))
    after = [probe_result("cron-d", stdout="timer *-*-* 04:00:00\n")]

    (item,) = tracking(found, known=[known], results=after).findings

    assert item.acknowledgement is None
    assert item.note == (
        "An acknowledgement from 2026-10-01 is on record for this line, but what it rests on has "
        "changed, so this counts again. Its reason was: On purpose."
    )


def test_editing_a_cited_doc_line_ends_an_acknowledgement_even_if_another_still_matches() -> None:
    before = doc_text(OPERATIONS, ("## Backups", "Runs at 02:00."))
    after = doc_text(OPERATIONS, ("## Backups", "Runs at 05:00."))
    cited = finding(1, end_line=2)
    known = replace(
        acknowledgement(cited),
        identity=identity(cited, [before]),
    )

    (item,) = tracking(cited, known=[known], docs=[after]).findings

    assert item.acknowledgement is None
    assert item.note is not None
    assert "what it rests on has changed" in item.note


def test_a_cross_doc_acknowledgement_ends_when_the_other_doc_changes() -> None:
    cross_doc = finding(11, kind=Kind.CROSS_DOC_CONTRADICTION, evidence=other_doc(3, 4))
    known = acknowledgement(cross_doc)
    edited = doc_text(APT, (*APT_LINES[:3], "updates arrive some other way.", *APT_LINES[4:]))

    (item,) = tracking(
        finding(11, kind=Kind.CROSS_DOC_CONTRADICTION, evidence=other_doc(3)),
        known=[known],
        docs=[doc_text(OPERATIONS, OPERATIONS_LINES), edited],
    ).findings

    assert item.acknowledgement is None


def test_an_acknowledgement_needs_its_line_still_printed_however_the_model_quotes() -> None:
    before = [probe_result("cron-d", stdout="restic.timer *-*-* 03:00:00\n")]
    known = acknowledgement(
        finding(6, evidence=ProbeQuote(probe="cron-d", quote="restic.timer *-*-* 03:00:00")),
        results=before,
    )
    shorter_quote = finding(6, evidence=ProbeQuote(probe="cron-d", quote="restic.timer"))
    moved = probe_result("cron-d", stdout="restic.timer *-*-* 04:00:00\n")

    (item,) = tracking(shorter_quote, known=[known], results=[moved]).findings

    assert item.acknowledgement is None


def test_an_acknowledgement_holds_however_the_model_quotes_the_same_line() -> None:
    output = [probe_result("cron-d", stdout="restic.timer *-*-* 03:00:00\n")]
    known = acknowledgement(
        finding(6, evidence=ProbeQuote(probe="cron-d", quote="restic.timer *-*-*")), results=output
    )
    found = finding(6, evidence=ProbeQuote(probe="cron-d", quote="03:00:00"))
    spaced = probe_result("cron-d", stdout="restic.timer     *-*-*   03:00:00\n")

    (item,) = tracking(found, known=[known], results=[spaced]).findings

    assert item.acknowledgement == known


def test_an_acknowledgement_can_find_its_line_on_standard_error() -> None:
    known = acknowledgement(finding(6))
    moved = replace(probe_result("cron-d"), stderr="0 * * * * root timeshift --check\n")

    (item,) = tracking(finding(6), known=[known], results=[moved]).findings

    assert item.acknowledgement is not None


def test_every_line_an_acknowledgement_recorded_must_still_be_printed() -> None:
    before = [probe_result("cron-d", stdout="backup runs\nat 03:00\n")]
    across = finding(6, evidence=ProbeQuote(probe="cron-d", quote="runs at 03:00"))
    known = acknowledgement(across, results=before)
    found = finding(6, evidence=ProbeQuote(probe="cron-d", quote="backup runs"))
    after = [probe_result("cron-d", stdout="backup runs\nat 04:00\n")]

    (item,) = tracking(found, known=[known], results=after).findings

    assert item.acknowledgement is None


def test_another_probe_printing_a_recorded_line_does_not_keep_an_acknowledgement_alive() -> None:
    before = [probe_result("cron-d", stdout="backup runs\nat 03:00\n")]
    across = finding(6, evidence=ProbeQuote(probe="cron-d", quote="runs at 03:00"))
    known = acknowledgement(across, results=before)
    found = finding(6, evidence=ProbeQuote(probe="cron-d", quote="backup runs"))
    mine = probe_result("cron-d", stdout="backup runs\nat 04:00\n")
    other = probe_result("timers", stdout="at 03:00\n")

    (item,) = tracking(found, known=[known], results=[mine, other]).findings

    assert item.acknowledgement is None


def test_an_acknowledgement_is_not_kept_alive_by_another_probes_output() -> None:
    known = acknowledgement(finding(6))
    other = probe_result("timers", stdout="0 * * * * root timeshift --check\n")
    mine = probe_result("cron-d", stdout="0 * * * * root timeshift something else\n")

    (item,) = tracking(
        finding(6, evidence=ProbeQuote(probe="cron-d", quote="0 * * * * root timeshift")),
        known=[known],
        results=[other, mine],
    ).findings

    assert item.acknowledgement is None


def test_a_cross_doc_acknowledgement_has_no_output_to_look_in() -> None:
    cross_doc = finding(11, kind=Kind.CROSS_DOC_CONTRADICTION, evidence=other_doc(3))

    (item,) = tracking(cross_doc, known=[acknowledgement(cross_doc)], results=[]).findings

    assert item.acknowledgement is not None


def test_an_acknowledgement_does_not_cover_another_claim_while_its_own_line_is_printed() -> None:
    both = [probe_result("cron-d", stdout="restic.timer 03:00:00\nfstrim.timer weekly\n")]
    known = acknowledgement(
        finding(6, evidence=ProbeQuote(probe="cron-d", quote="restic.timer 03:00:00")), results=both
    )
    other_claim = finding(6, evidence=ProbeQuote(probe="cron-d", quote="fstrim.timer weekly"))

    (item,) = tracking(other_claim, known=[known], results=both).findings

    assert item.acknowledgement is None
    assert item.note == (
        "An acknowledgement from 2026-10-01 is on record for this line, but for other evidence, "
        "so it doesn't cover this. Its reason was: On purpose."
    )


def test_an_acknowledged_omission_does_not_cover_the_next_one_under_its_heading() -> None:
    known = acknowledgement(
        finding(3, kind=Kind.OMISSION, evidence=ProbeQuote(probe="cron-d", quote="@reboot root"))
    )
    next_one = finding(
        3, kind=Kind.OMISSION, evidence=ProbeQuote(probe="cron-d", quote="0 3 * * * root")
    )

    (item,) = tracking(next_one, known=[known]).findings

    assert item.acknowledgement is None
    assert item.note is None


def test_an_acknowledgement_for_another_omission_says_nothing() -> None:
    known = acknowledgement(
        finding(3, kind=Kind.OMISSION, evidence=ProbeQuote(probe="cron-d", quote="@reboot root"))
    )
    found = finding(3, kind=Kind.OMISSION, evidence=ProbeQuote(probe="cron-d", quote="0 3 * * *"))

    (item,) = tracking(found, known=[known]).findings

    assert item.acknowledgement is None
    assert item.note is None


def test_a_finding_that_is_gone_while_its_probe_works_is_no_longer_reported() -> None:
    gone = earlier(finding(6), runs_open=2)

    result = tracking(before=previous(gone))

    assert result.no_longer_reported == (gone,)
    assert result.not_rechecked == ()


def test_an_acknowledgement_with_nothing_to_match_is_no_longer_reported() -> None:
    known = acknowledgement(finding(6))

    (item,) = tracking(known=[known]).no_longer_reported

    assert (item.id, item.title, item.acknowledged) == (known.id, known.title, True)


def test_an_acknowledgement_with_nothing_to_match_keeps_its_confidence() -> None:
    known = acknowledgement(finding(6, confidence=Confidence.SUSPECT))

    (item,) = tracking(known=[known]).no_longer_reported

    assert item.confidence is Confidence.SUSPECT


def test_an_open_finding_on_another_output_line_is_not_filed_under_a_gone_acknowledgement() -> None:
    known = acknowledgement(finding(8, evidence=TIMESHIFT))
    other = finding(8, evidence=RESTIC)

    gone = tracking(known=[known], before=previous(earlier(other, runs_open=5))).no_longer_reported

    assert [(item.id, item.runs_open, item.acknowledged) for item in gone] == [
        (known.id, 0, True),
        (finding_id(identity(other)), 5, False),
    ]


def test_every_gone_acknowledgement_on_one_doc_line_is_listed() -> None:
    one = acknowledgement(finding(8, evidence=TIMESHIFT))
    other = acknowledgement(finding(8, evidence=RESTIC))

    gone = tracking(known=[one, other]).no_longer_reported

    assert [item.id for item in gone] == [one.id, other.id]


def test_a_gone_acknowledgement_takes_its_count_only_from_its_own_finding() -> None:
    unrelated = finding(11, evidence=RESTIC)
    known = acknowledgement(finding(8))

    gone = tracking(
        known=[known],
        before=previous(earlier(finding(8), runs_open=2), earlier(unrelated, runs_open=9)),
    ).no_longer_reported

    assert [(item.id, item.runs_open) for item in gone] == [
        (known.id, 2),
        (finding_id(identity(unrelated)), 9),
    ]


def test_an_expired_acknowledgement_with_nothing_to_match_is_not_called_acknowledged() -> None:
    known = acknowledgement(finding(6), until=date(2026, 10, 1))

    (item,) = tracking(known=[known]).no_longer_reported

    assert not item.acknowledged


def test_renewing_an_acknowledgement_does_not_list_the_finding_twice() -> None:
    expired = acknowledgement(finding(6), until=date(2026, 10, 1))
    renewed = acknowledgement(finding(6))

    (item,) = tracking(known=[expired, renewed]).no_longer_reported

    assert item.acknowledged


def test_a_finding_whose_acknowledgement_was_deleted_is_not_called_acknowledged() -> None:
    item = earlier(finding(6), acknowledged=True)

    (gone,) = tracking(before=previous(item)).no_longer_reported

    assert not gone.acknowledged


def test_an_earlier_finding_is_not_lost_when_only_its_acknowledgement_matches_a_current_one() -> (
    None
):
    both_lines = finding(8, end_line=9)
    first_line = earlier(finding(8))
    second_line = finding(9)

    result = tracking(second_line, known=[acknowledgement(both_lines)], before=previous(first_line))

    assert result.no_longer_reported == (first_line,)


def test_an_acknowledged_finding_that_goes_unchecked_keeps_its_count() -> None:
    known = acknowledgement(finding(6))
    broken = probe_result("cron-d", failure="timed out after 30s")

    (item,) = tracking(
        known=[known], before=previous(earlier(finding(6), runs_open=5)), results=[broken]
    ).not_rechecked

    assert item.runs_open == 5
    assert item.acknowledged


def test_an_earlier_finding_and_its_acknowledgement_are_listed_once() -> None:
    (item,) = tracking(
        known=[acknowledgement(finding(6))], before=previous(earlier(finding(6)))
    ).no_longer_reported

    assert item.acknowledged


def test_a_finding_still_reported_is_not_listed_as_gone() -> None:
    result = tracking(
        finding(6), known=[acknowledgement(finding(6))], before=previous(earlier(finding(6)))
    )

    assert result.no_longer_reported == ()
    assert result.not_rechecked == ()


def test_a_failed_probe_never_reads_as_no_longer_reported() -> None:
    gone = earlier(finding(6))

    result = tracking(
        before=previous(gone), results=[probe_result("cron-d", failure="timed out after 30s")]
    )

    assert result.no_longer_reported == ()
    assert result.not_rechecked == (gone,)


def test_a_probe_that_left_the_config_means_not_rechecked() -> None:
    gone = earlier(finding(6))

    result = tracking(before=previous(gone), results=[probe_result("timers")])

    assert result.not_rechecked == (replace(gone, left_config=True),)


def test_a_doc_that_left_the_config_means_not_rechecked() -> None:
    gone = earlier(finding(6))

    result = tracking(before=previous(gone), docs=[doc_text(APT, APT_LINES)])

    assert result.not_rechecked == (replace(gone, left_config=True),)


def test_an_other_doc_that_left_the_config_means_not_rechecked() -> None:
    gone = earlier(finding(11, kind=Kind.CROSS_DOC_CONTRADICTION, evidence=other_doc(3)))

    result = tracking(before=previous(gone), docs=[doc_text(OPERATIONS, OPERATIONS_LINES)])

    assert result.not_rechecked == (replace(gone, left_config=True),)


def test_a_dropped_finding_with_the_same_sources_means_not_rechecked() -> None:
    gone = earlier(finding(6))
    dropped = Dropped(finding=finding(6, quote="not in the doc"), problems=("doc: no",))

    result = tracking(before=previous(gone), dropped=[dropped])

    assert result.no_longer_reported == ()
    assert result.not_rechecked == (gone,)


def test_a_dropped_cross_doc_finding_with_the_same_docs_means_not_rechecked() -> None:
    cross_doc = finding(11, kind=Kind.CROSS_DOC_CONTRADICTION, evidence=other_doc(3))
    swapped = finding(
        3, file=APT, kind=Kind.CROSS_DOC_CONTRADICTION, evidence=other_doc(11, file=OPERATIONS)
    )
    gone = earlier(cross_doc)

    for dropped in (cross_doc, swapped):
        result = tracking(
            before=previous(gone), dropped=[Dropped(finding=dropped, problems=("doc: no",))]
        )
        assert result.not_rechecked == (gone,)


@pytest.mark.parametrize(
    "unrelated",
    [
        finding(1, file=APT),
        finding(6, evidence=ProbeQuote(probe="timers", quote="x")),
        finding(6, evidence=other_doc(3)),
    ],
)
def test_a_dropped_finding_about_something_else_changes_nothing(unrelated: Finding) -> None:
    gone = earlier(finding(6))
    dropped = Dropped(finding=unrelated, problems=("doc: no",))

    assert tracking(before=previous(gone), dropped=[dropped]).no_longer_reported == (gone,)


def test_a_dropped_cross_doc_finding_about_another_doc_changes_nothing() -> None:
    gone = earlier(finding(11, kind=Kind.CROSS_DOC_CONTRADICTION, evidence=other_doc(3)))
    unrelated = finding(
        11, kind=Kind.CROSS_DOC_CONTRADICTION, evidence=other_doc(3, file="notes/other.md")
    )
    dropped = Dropped(finding=unrelated, problems=("evidence: no",))

    assert tracking(before=previous(gone), dropped=[dropped]).no_longer_reported == (gone,)


def test_a_not_rechecked_acknowledgement_keeps_its_flag() -> None:
    known = acknowledgement(finding(6))

    (item,) = tracking(known=[known], results=[]).not_rechecked

    assert item.acknowledged
    assert item.from_known
    assert item.left_config


def config_in(directory: Path, name: str = "doc-truth.toml") -> Config:
    return Config(path=directory / name, base_dir=directory, docs=(), probes=())


def write_known(directory: Path, text: str) -> None:
    (directory / "doc-truth-known.toml").write_text(text, encoding="utf-8")


VALID_ENTRY = """
[[known]]
id = "a1b2c3d4"
title = "A title"
kind = "contradiction"
confidence = "confirmed"
reason = "On purpose."
acknowledged = 2026-11-02
doc = "docs/operations.md"
lines = ["A line."]
probe = "timers"
evidence-lines = ["A quote."]
"""


def test_no_known_file_means_nothing_is_known(tmp_path: Path) -> None:
    assert load_known(config_in(tmp_path)) == ()


def test_the_known_file_is_named_after_the_config(tmp_path: Path) -> None:
    assert known_path(config_in(tmp_path)) == tmp_path / "doc-truth-known.toml"
    assert known_path(config_in(tmp_path, "ops.toml")) == tmp_path / "ops-known.toml"


def test_a_known_file_with_only_comments_is_fine(tmp_path: Path) -> None:
    write_known(tmp_path, "# Nothing left.\n")

    assert load_known(config_in(tmp_path)) == ()


def test_a_known_entry_loads(tmp_path: Path) -> None:
    write_known(tmp_path, VALID_ENTRY + "until = 2026-12-01\n")

    assert load_known(config_in(tmp_path)) == (
        Acknowledgement(
            id="a1b2c3d4",
            title="A title",
            confidence=Confidence.CONFIRMED,
            reason="On purpose.",
            acknowledged=date(2026, 11, 2),
            until=date(2026, 12, 1),
            identity=Identity(
                kind=Kind.CONTRADICTION,
                doc=CitedLines(file="docs/operations.md", lines=frozenset({"A line."})),
                evidence=ProbeOutput(probe="timers", lines=frozenset({"A quote."})),
            ),
        ),
    )


def test_a_cross_doc_known_entry_loads(tmp_path: Path) -> None:
    write_known(
        tmp_path,
        '[[known]]\nid = "x"\ntitle = "t"\nkind = "cross-doc-contradiction"\n'
        'confidence = "suspect"\nreason = "r"\n'
        'acknowledged = 2026-11-02\ndoc = "a.md"\nlines = ["A"]\n'
        'other-doc = "b.md"\nother-lines = ["B", "C"]\n',
    )

    (entry,) = load_known(config_in(tmp_path))

    assert entry.until is None
    assert entry.identity.evidence == CitedLines(file="b.md", lines=frozenset({"B", "C"}))


def test_hand_edited_spacing_is_normalised_when_the_file_loads(tmp_path: Path) -> None:
    write_known(
        tmp_path,
        VALID_ENTRY.replace('"A line."', '"A   line."').replace('"A quote."', '"A  quote."'),
    )

    (entry,) = load_known(config_in(tmp_path))

    assert entry.identity.doc.lines == frozenset({"A line."})
    assert entry.identity.evidence == ProbeOutput(probe="timers", lines=frozenset({"A quote."}))


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (('"A title"', "3"), "title must be a string, found an integer"),
        (('reason = "On purpose."', 'reason = "  "'), "reason must not be empty"),
        (('reason = "On purpose."\n', ""), "missing reason"),
        (('id = "a1b2c3d4"\n', ""), "missing id"),
        (('title = "A title"\n', ""), "missing title"),
        (('kind = "contradiction"\n', ""), "missing kind"),
        (('"contradiction"', '"typo"'), "kind must be one of"),
        (('confidence = "confirmed"\n', ""), "missing confidence"),
        (('"confirmed"', '"typo"'), "confidence must be one of"),
        (("acknowledged = 2026-11-02\n", ""), "missing acknowledged"),
        (
            ("2026-11-02", '"today"'),
            "acknowledged must be a date such as 2026-12-01, found a string",
        ),
        (("2026-11-02", "2026-11-02T10:00:00"), "found a date-time"),
        (('doc = "docs/operations.md"\n', ""), "missing doc"),
        (('lines = ["A line."]\n', ""), "missing lines"),
        (('["A line."]', "[]"), "lines must be an array of lines, found an array"),
        (('["A line."]', '"A line."'), "lines must be an array of lines, found a string"),
        (('["A line."]', '["  "]'), "lines must contain only lines of text"),
        (('["A line."]', "[1]"), "lines must contain only lines of text"),
        (('probe = "timers"\n', ""), "must have either probe or other-doc"),
        (('evidence-lines = ["A quote."]\n', ""), "missing evidence-lines"),
        (("reason =", 'reazon = "x"\nreason ='), 'unknown key "reazon" (did you mean "reason"?)'),
    ],
)
def test_an_invalid_known_entry_is_reported_with_where_it_is(
    tmp_path: Path, change: tuple[str, str], problem: str
) -> None:
    write_known(tmp_path, VALID_ENTRY.replace(*change))

    with pytest.raises(ConfigError) as caught:
        load_known(config_in(tmp_path))

    assert problem in str(caught.value)
    assert str(caught.value).startswith(str(tmp_path / "doc-truth-known.toml"))
    assert "[[known]] #1" in str(caught.value)


@pytest.mark.parametrize(
    ("extra", "problem"),
    [
        ('other-doc = "b.md"\nother-lines = ["B"]\n', "must have either probe or other-doc"),
        ('other-lines = ["B"]\n', "other-lines goes with other-doc, not with probe"),
    ],
)
def test_a_known_entry_cannot_mix_its_two_kinds_of_evidence(
    tmp_path: Path, extra: str, problem: str
) -> None:
    write_known(tmp_path, VALID_ENTRY + extra)

    with pytest.raises(ConfigError, match=problem):
        load_known(config_in(tmp_path))


def test_evidence_does_not_go_with_another_doc(tmp_path: Path) -> None:
    write_known(
        tmp_path,
        VALID_ENTRY.replace('probe = "timers"\n', 'other-doc = "b.md"\nother-lines = ["B"]\n'),
    )

    with pytest.raises(ConfigError, match="evidence-lines goes with probe, not with other-doc"):
        load_known(config_in(tmp_path))


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("known = 3\n", "known must be [[known]] tables"),
        ("[known]\nid = 'x'\n", "[known] must be written [[known]]"),
        ("other = 1\n", 'unknown key "other"'),
        ("known = [1]\n", "[[known]] #1: must be a table, found an integer"),
        ("[[known]\n", "invalid TOML"),
    ],
)
def test_a_known_file_of_the_wrong_shape_is_an_error(
    tmp_path: Path, text: str, problem: str
) -> None:
    write_known(tmp_path, text)

    with pytest.raises(ConfigError) as caught:
        load_known(config_in(tmp_path))

    assert problem in str(caught.value)


@pytest.mark.parametrize(
    "text",
    [
        "plain",
        'quotes " and \\ backslashes',
        "a line\nbreak and a\ttab",
        "control \x01 and delete \x7f characters",
        "a NUL \x00 from a probe's output",
        f"café - unicode {LINE_SEPARATOR} too",
        "[[known]] # looks like TOML",
    ],
)
def test_anything_ack_writes_loads_back_the_same(tmp_path: Path, text: str) -> None:
    found = Acknowledgement(
        id="a1b2c3d4",
        title=text,
        confidence=Confidence.SUSPECT,
        reason=text,
        acknowledged=TODAY,
        until=date(2026, 12, 1),
        identity=Identity(
            kind=Kind.CROSS_DOC_CONTRADICTION,
            doc=CitedLines(file=f"docs/{text}.md", lines=frozenset({"line one", "line two"})),
            evidence=CitedLines(file="b.md", lines=frozenset({"other"})),
        ),
    )
    path = tmp_path / "doc-truth-known.toml"

    append_known(path, found)

    assert load_known(config_in(tmp_path)) == (found,)


def test_ack_appends_and_leaves_what_is_there_alone(tmp_path: Path) -> None:
    write_known(tmp_path, "# My own comment\n" + VALID_ENTRY.rstrip("\n"))
    path = tmp_path / "doc-truth-known.toml"
    first = load_known(config_in(tmp_path))[0]
    second = acknowledge(earlier(finding(6)), reason="Second reason.", today=TODAY, until=None)

    append_known(path, second)

    text = path.read_text(encoding="utf-8")
    assert text.startswith("# My own comment\n")
    assert 'evidence-lines = ["A quote."]\n\n[[known]]\n' in text
    assert load_known(config_in(tmp_path)) == (first, second)


def test_a_new_known_file_explains_itself(tmp_path: Path) -> None:
    path = tmp_path / "doc-truth-known.toml"

    append_known(path, acknowledge(earlier(finding(6)), reason="r", today=TODAY, until=None))

    assert path.read_text(encoding="utf-8").startswith(
        "# Findings acknowledged with `doc-truth ack`. Commit this file with your docs.\n"
        "# Delete a [[known]] table to bring its finding back.\n\n[[known]]\n"
    )


def test_an_unwritable_known_file_is_an_ack_error(tmp_path: Path) -> None:
    with pytest.raises(AckError, match=r"cannot write .*missing"):
        append_known(
            tmp_path / "missing" / "doc-truth-known.toml",
            acknowledge(earlier(finding(6)), reason="r", today=TODAY, until=None),
        )


def test_an_entry_is_readable_toml() -> None:
    found = acknowledge(
        earlier(finding(6)), reason="On purpose.", today=TODAY, until=date(2026, 12, 1)
    )

    assert known_toml(found) == (
        "[[known]]\n"
        f'id = "{found.id}"\n'
        'title = "A title"\n'
        'kind = "contradiction"\n'
        'confidence = "confirmed"\n'
        'reason = "On purpose."\n'
        "acknowledged = 2026-11-02\n"
        "until = 2026-12-01\n"
        'doc = "docs/operations.md"\n'
        'lines = ["| hourly, 09:00-21:00 | Timeshift snapshot check | `0 9-21 * * *` |"]\n'
        'probe = "cron-d"\n'
        'evidence-lines = ["0 * * * * root timeshift --check"]\n'
    )


@pytest.mark.parametrize(
    "found",
    [
        finding(6),
        finding(3, kind=Kind.OMISSION),
        finding(11, kind=Kind.CROSS_DOC_CONTRADICTION, evidence=other_doc(3)),
    ],
)
def test_an_earlier_finding_survives_the_json_report(found: Finding) -> None:
    item = replace(earlier(found, runs_open=4, acknowledged=True), confidence=Confidence.SUSPECT)

    assert earlier_from_json(json.loads(json.dumps(earlier_json(item)))) == item


@pytest.mark.parametrize(
    "entry",
    [
        {"id": 1, "title": "t", "confidence": "suspect", "runs_open": 1, "identity": {}},
        {"id": "x", "title": 1, "confidence": "suspect", "runs_open": 1, "identity": {}},
        {"id": "x", "title": "t", "confidence": "suspect", "runs_open": "1", "identity": {}},
        {"id": "x", "title": "t", "confidence": "suspect", "runs_open": 1, "identity": 1},
        {"id": "x", "title": "t", "confidence": "typo", "runs_open": 1, "identity": {}},
        {
            "id": "x",
            "title": "t",
            "confidence": "suspect",
            "runs_open": 1,
            "identity": {
                "kind": "contradiction",
                "doc": {"file": "f", "lines": "not a list"},
                "evidence": {"probe": "p", "lines": ["q"]},
            },
        },
        {
            "id": "x",
            "title": "t",
            "confidence": "suspect",
            "runs_open": 1,
            "identity": {
                "kind": "contradiction",
                "doc": 1,
                "evidence": {"probe": "p", "lines": ["q"]},
            },
        },
        {
            "id": "x",
            "title": "t",
            "confidence": "suspect",
            "runs_open": 1,
            "identity": {
                "kind": "contradiction",
                "doc": {"file": "f", "lines": ["l"]},
                "evidence": 1,
            },
        },
        {
            "id": "x",
            "title": "t",
            "confidence": "suspect",
            "runs_open": 1,
            "identity": {
                "kind": "typo",
                "doc": {"file": "f", "lines": ["l"]},
                "evidence": {"probe": "p", "lines": ["q"]},
            },
        },
    ],
)
def test_a_malformed_earlier_finding_is_a_value_error(entry: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        earlier_from_json(entry)


def test_a_finding_acknowledged_in_the_report_is_already_acknowledged() -> None:
    entry = replace(acknowledgement(finding(8)), id="on-file")
    shown = replace(earlier(finding(8, end_line=9), acknowledged=True), id="on-file")

    assert entry.identity != shown.identity
    assert already_acknowledged(shown, [entry], TODAY)


def test_the_same_identity_is_already_acknowledged_before_any_new_report() -> None:
    entry = acknowledgement(finding(6))

    assert already_acknowledged(earlier(finding(6)), [entry], TODAY)


def test_a_finding_that_counts_again_can_be_acknowledged_again() -> None:
    entry = acknowledgement(finding(8))
    same_id_counting = replace(earlier(finding(8, end_line=9)), id=entry.id)

    assert not already_acknowledged(same_id_counting, [entry], TODAY)


def test_a_suspect_entry_does_not_count_for_a_finding_that_is_now_confirmed() -> None:
    entry = acknowledgement(finding(6, confidence=Confidence.SUSPECT))

    assert not already_acknowledged(earlier(finding(6)), [entry], TODAY)
    assert already_acknowledged(earlier(finding(6, confidence=Confidence.SUSPECT)), [entry], TODAY)


def test_a_confirmed_entry_counts_for_a_finding_that_is_now_suspect() -> None:
    entry = acknowledgement(finding(6))

    assert already_acknowledged(earlier(finding(6, confidence=Confidence.SUSPECT)), [entry], TODAY)


def test_an_expired_entry_does_not_count_as_already_acknowledged() -> None:
    entry = acknowledgement(finding(6), until=date(2026, 10, 1))

    assert not already_acknowledged(earlier(finding(6)), [entry], TODAY)
    assert not already_acknowledged(earlier(finding(6), acknowledged=True), [entry], TODAY)


def test_a_reason_that_is_not_valid_text_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "doc-truth-known.toml"
    found = acknowledge(earlier(finding(6)), reason="bad \udcff", today=TODAY, until=None)

    with pytest.raises(AckError, match="isn't valid UTF-8"):
        append_known(path, found)

    assert not path.exists()
