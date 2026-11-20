import re
import time

import pytest

from doc_truth.findings import CitedLines, Identity, Kind, ProbeOutput
from doc_truth.redact import (
    BUILT_IN_NAMES,
    BUILT_IN_RULES,
    Redaction,
    Redactor,
    Rule,
    marker,
    redact_identity,
)


# Token-shaped strings are joined at run time: a literal one, or a "+" that Python folds into
# one constant in the .pyc, would stop the push at gitleaks and GitHub push protection.
def joined(*parts: str) -> str:
    return "".join(parts)


GITHUB_TOKEN = joined("ghp", "_", "Ab3dE6gH9jK2mN5pQ8sT1vW4yZ7bC0eF3hJ6")
GITHUB_PAT = joined("github", "_pat_", "11ABCDEFG0", "x" * 20)
GITLAB_TOKEN = joined("glpat", "-", "Zx8Cv7Bn6Mm5Ll4Kk3Jj")
SLACK_TOKEN = joined("xoxb", "-", "1234567890-abcdefABCDEF")
AWS_KEY = joined("AKIA", "QWERTYUIOPASDFGH")
API_KEY = joined("sk", "-", "proj_", "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6")
TAILSCALE_KEY = joined("tskey", "-auth-", "fakefakefake1234")
TELEGRAM_TOKEN = joined("123456789", ":", "AAH", "x" * 32)
JWT = joined("eyJ", "hbGciOiJIUzI1NiJ9", ".eyJ", "zdWIiOiJvcHMifQ", ".", "c2lnbmF0dXJlLXBhcnQ")
PEM_BODY = "ZmFrZSBtYXRlcmlhbA==\nbm90IHJlYWw=\n"
BEGIN, END = joined("-----BEGIN ", "PRIVATE KEY-----"), joined("-----END ", "PRIVATE KEY-----")
PRIVATE_KEY = f"{BEGIN}\n{PEM_BODY}{END}"
PASSWORD = "correct-horse-battery-staple"

REDACTOR = Redactor()


def hide(text: str, redactor: Redactor = REDACTOR) -> tuple[str, tuple[Redaction, ...]]:
    return redactor.redact(text, where="stdout")


def hidden(text: str) -> str:
    return hide(text)[0]


@pytest.mark.parametrize(
    ("text", "secret", "rule"),
    [
        (f"key in the unit:\n{PRIVATE_KEY}\n", PRIVATE_KEY, "private-key"),
        (f"remote = https://{GITHUB_TOKEN}@github.com/ops/infra", GITHUB_TOKEN, "github-token"),
        (f"token {GITHUB_PAT}", GITHUB_PAT, "github-token"),
        (f"CI_JOB={GITLAB_TOKEN}", GITLAB_TOKEN, "gitlab-token"),
        (f"hook {SLACK_TOKEN} posted", SLACK_TOKEN, "slack-token"),
        (f"aws_access_key_id {AWS_KEY}", AWS_KEY, "aws-access-key"),
        (f"OPENAI {API_KEY}", API_KEY, "api-key"),
        (f"tailscale up --authkey {TAILSCALE_KEY}", TAILSCALE_KEY, "tailscale-key"),
        (
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            TELEGRAM_TOKEN,
            "telegram-bot-token",
        ),
        (f"cookie session {JWT};", JWT, "jwt"),
        (f"Repository: rest:https://ops:{PASSWORD}@example.org/backups", PASSWORD, "url-password"),
        (f"Authorization: Bearer {PASSWORD}", PASSWORD, "authorization"),
        (f"Environment=RESTIC_PASSWORD={PASSWORD}", PASSWORD, "assignment"),
    ],
    ids=lambda value: value if value in BUILT_IN_NAMES else "",
)
def test_each_built_in_rule_hides_its_secret(text: str, secret: str, rule: str) -> None:
    redacted, redactions = hide(text)

    assert secret not in redacted
    assert redacted == text.replace(secret, marker(rule))
    assert [redaction.rule for redaction in redactions] == [rule]


def test_every_built_in_rule_has_a_case_above() -> None:
    assert BUILT_IN_NAMES == (
        "private-key",
        "github-token",
        "gitlab-token",
        "slack-token",
        "aws-access-key",
        "api-key",
        "tailscale-key",
        "telegram-bot-token",
        "jwt",
        "url-password",
        "authorization",
        "assignment",
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            f"https://ops:{PASSWORD}@example.org/",
            "https://ops:[REDACTED:url-password]@example.org/",
        ),
        (
            f"authorization: basic {PASSWORD}\n",
            "authorization: basic [REDACTED:authorization]\n",
        ),
        (
            f'curl -H "Authorization: Token {PASSWORD}"',
            'curl -H "Authorization: Token [REDACTED:authorization]"',
        ),
        (f"db_password: {PASSWORD}", "db_password: [REDACTED:assignment]"),
        (f'"password": "{PASSWORD}",', '"password": [REDACTED:assignment],'),
        ("password: 'two words'", "password: [REDACTED:assignment]"),
        (
            'Environment="SMTP_PASSWD=a b" TZ=UTC',
            'Environment="SMTP_PASSWD=[REDACTED:assignment]" TZ=UTC',
        ),
        (
            '"Env": ["POSTGRES_PASSWORD=it\'s ok", "TZ=UTC"]',
            '"Env": ["POSTGRES_PASSWORD=[REDACTED:assignment]", "TZ=UTC"]',
        ),
        ("echo 'token=abc' done", "echo 'token=[REDACTED:assignment]' done"),
        ("client_secret = abc123", "client_secret = [REDACTED:assignment]"),
        ("X-API-KEY: abc123", "X-API-KEY: [REDACTED:assignment]"),
        ("access_key=abc123 region=eu", "access_key=[REDACTED:assignment] region=eu"),
        ("ssh private_key: abc123", "ssh private_key: [REDACTED:assignment]"),
        ("PASSWORD=$RESTIC_PASSWORD", "PASSWORD=[REDACTED:assignment]"),
        ("PASSWORD=$(x)tail", "PASSWORD=[REDACTED:assignment]"),
        ('PASSWORD="${PREFIX}"hunter2', "PASSWORD=[REDACTED:assignment]"),
        (
            "Environment=DJANGO_SECRET_KEY=abc123",
            "Environment=DJANGO_SECRET_KEY=[REDACTED:assignment]",
        ),
        ("SECRET_KEY_BASE=abc123", "SECRET_KEY_BASE=[REDACTED:assignment]"),
        ('"Env": ["DB_PASSWORD=pa\\"ss tail"]', '"Env": ["DB_PASSWORD=[REDACTED:assignment]"]'),
        ('{"password":"abc\\"def gh"}', '{"password":[REDACTED:assignment]}'),
        ('"cmd TOKEN=abc"', '"cmd TOKEN=[REDACTED:assignment]'),
        ("https://ops:p@ss@example.org/", "https://ops:[REDACTED:url-password]@example.org/"),
        (
            "https://ops:pw@example.org/path@v1?q=a@b",
            "https://ops:[REDACTED:url-password]@example.org/path@v1?q=a@b",
        ),
        (
            "https://ops:pw@example.org?q=a@b",
            "https://ops:[REDACTED:url-password]@example.org?q=a@b",
        ),
        (
            "Proxy-Authorization: Basic dXNlcjpwYXNz",
            "Proxy-Authorization: Basic [REDACTED:authorization]",
        ),
        ("Authorization: NTLM TlRMTVNTUAAB", "Authorization: NTLM [REDACTED:authorization]"),
    ],
)
def test_a_rule_with_a_secret_group_hides_only_the_value(text: str, expected: str) -> None:
    assert hidden(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "automountServiceAccountToken: false",
        "RESTIC_PASSWORD_FILE=/etc/restic/password",
        "PasswordAuthentication no",
        "token_endpoint=https://example.org/oauth/token",
        "password=",
        'password: ""',
        "secret: true",
        "api_key: null",
        "token: none",
        "password = off",
        "PASSWORD=${RESTIC_PASSWORD}",
        'PASSWORD="${RESTIC_PASSWORD:-}"',
        '"PASSWORD=$(cat /run/secrets/db)"',
        '"PASSWORD="',
        '"automountServiceAccountToken": false',
        "export RESTIC_PASSWORD=$(cat /root/.restic-password) restic backup",
        "password: <password>",
        'password: "<changeme>",',
        "token: {{token}}",
        "password: ********",
        "password: REDACTED",
        "client-key-data: DATA+OMITTED",
        "`password=`",
        "https://example.org:8443/status",
        "https://ops:${RESTIC_PASSWORD}@example.org/",
        "rest:https://ops:<password>@example.org/backups",
        "ssh://git@example.org/ops/infra.git",
        "postgres://ops@example.org/db",
        "sk-short-and-not-a-key",
        "xoxb-short",
        "tskey-auth",
        "eyJhbGciOiJIUzI1NiJ9 on its own",
        joined("robot123456789:", "A" * 35),
        joined("123456789:", "A" * 40, " is longer than a bot token"),
        joined("eyJ", "hbGciOiJIUzI1NiJ9", "eyJ", "zdWIiOiJvcHMifQ", ".", "c2lnbmF0dXJl"),
        "AKIAQWERTYUIOPASDFGHJ is too long for an access key",
        "image ghcr.io/ops/app@sha256:" + "9f86d081884c7d659a2feaa0c55ad015" * 2,
        "commit 2142b00c1f4e8b9d6a7e3f5c0b1d2e4f6a8c9b0d",
        "uuid 123e4567-e89b-12d3-a456-426614174000",
        "-----BEGIN " + "PUBLIC KEY-----\nMIIBIjANBg\n-----END PUBLIC KEY-----",
        "-----BEGIN " + "CERTIFICATE-----\nMIIDdzCCAl+g\n-----END CERTIFICATE-----",
        "Authorization: Bearer",
        "X-Authorization-Mode: strict",
        "PWD=/home/ops",
        "OLDPWD=/srv",
        "PASSWORD=[REDACTED:github-token]",
        "https://ops:[REDACTED:url-password]@example.org/",
        "Bearer tokens are rotated weekly",
    ],
)
def test_near_misses_are_left_alone(text: str) -> None:
    assert hide(text) == (text, ())


@pytest.mark.parametrize(
    "text",
    [
        f"{PRIVATE_KEY}\nAuthorization: Bearer {GITHUB_TOKEN}",
        f"GITHUB_TOKEN={GITHUB_TOKEN} https://ops:{PASSWORD}@example.org/",
        f'Environment="RESTIC_PASSWORD={PASSWORD}" TOKEN={JWT} AWS={AWS_KEY}',
        f"{SLACK_TOKEN} {GITLAB_TOKEN} {API_KEY} {TAILSCALE_KEY} /bot{TELEGRAM_TOKEN}/",
    ],
    ids=["key-and-header", "token-and-url", "environment", "other-tokens"],
)
def test_hiding_twice_changes_nothing(text: str) -> None:
    once = hidden(text)

    assert hide(once) == (once, ())


def test_an_identity_hides_its_probe_lines_and_keeps_its_doc_lines() -> None:
    doc = CitedLines(file="docs/ops.md", lines=frozenset({f"password: {PASSWORD}"}))
    identity = Identity(
        kind=Kind.CONTRADICTION,
        doc=doc,
        evidence=ProbeOutput(probe="env", lines=frozenset({f"PASSWORD={PASSWORD} KEEP=7"})),
    )

    assert redact_identity(identity, REDACTOR) == Identity(
        kind=Kind.CONTRADICTION,
        doc=doc,
        evidence=ProbeOutput(
            probe="env", lines=frozenset({"PASSWORD=[REDACTED:assignment] KEEP=7"})
        ),
    )


def test_an_identity_between_docs_is_left_alone() -> None:
    lines = CitedLines(file="docs/ops.md", lines=frozenset({f"password: {PASSWORD}"}))
    identity = Identity(kind=Kind.CROSS_DOC_CONTRADICTION, doc=lines, evidence=lines)

    assert redact_identity(identity, REDACTOR) is identity


def test_text_with_nothing_to_hide_comes_back_as_it_was() -> None:
    text = "restic-backup.timer  *-*-* 03:00:00\n"

    assert hide(text) == (text, ())


def test_a_private_key_is_hidden_whole_even_when_the_output_was_cut_off() -> None:
    cut_off = PRIVATE_KEY.removesuffix(END)

    assert hidden(f"before\n{cut_off}") == "before\n[REDACTED:private-key]"


def test_any_kind_of_private_key_is_hidden() -> None:
    key = PRIVATE_KEY.replace(" PRIVATE", " OPENSSH PRIVATE")

    assert hidden(key) == "[REDACTED:private-key]"


def test_two_keys_are_hidden_separately() -> None:
    assert hidden(f"{PRIVATE_KEY}\nbetween\n{PRIVATE_KEY}\n") == (
        "[REDACTED:private-key]\nbetween\n[REDACTED:private-key]\n"
    )


def test_overlapping_matches_become_one_marker_named_by_the_earlier_rule() -> None:
    redacted, redactions = hide(f"GITHUB_TOKEN={GITHUB_TOKEN}")

    assert redacted == "GITHUB_TOKEN=[REDACTED:github-token]"
    assert [redaction.rule for redaction in redactions] == ["github-token"]


def test_a_match_that_starts_inside_another_extends_it() -> None:
    redactor = Redactor(
        rules=(
            Rule(name="first", pattern=re.compile("aaa-b")),
            Rule(name="second", pattern=re.compile("b-ccc")),
        )
    )

    assert hide("x aaa-b-ccc y", redactor) == (
        "x [REDACTED:first] y",
        (Redaction(rule="first", where="stdout", line=1),),
    )


def test_a_match_inside_another_is_hidden_with_it() -> None:
    redactor = Redactor(
        rules=(
            Rule(name="outer", pattern=re.compile("aaa-bbb-ccc")),
            Rule(name="inner", pattern=re.compile("bbb")),
        )
    )

    assert hidden_by(redactor, "x aaa-bbb-ccc y") == "x [REDACTED:outer] y"


def test_a_rule_of_your_own_hides_placeholder_values_too() -> None:
    redactor = Redactor(rules=(Rule(name="mode", pattern=re.compile(r"mode=(?P<secret>\w+)")),))

    assert hidden_by(redactor, "mode=none") == "mode=[REDACTED:mode]"


def test_adjacent_matches_stay_separate() -> None:
    redactor = Redactor(
        rules=(
            Rule(name="first", pattern=re.compile("aaa")),
            Rule(name="second", pattern=re.compile("bbb")),
        )
    )

    assert hide("aaabbb", redactor)[0] == "[REDACTED:first][REDACTED:second]"


def test_each_hidden_value_is_listed_in_order_with_its_line() -> None:
    text = (
        f"first line\nAuthorization: Bearer {PASSWORD}\n"
        f"{PRIVATE_KEY}\n"
        f"third secret PASSWORD={PASSWORD} and token={PASSWORD}\n"
    )

    redacted, redactions = REDACTOR.redact(text, where="stderr")

    assert PASSWORD not in redacted
    assert redactions == (
        Redaction(rule="authorization", where="stderr", line=2),
        Redaction(rule="private-key", where="stderr", line=3),
        Redaction(rule="assignment", where="stderr", line=7),
        Redaction(rule="assignment", where="stderr", line=7),
    )


def test_an_allowed_value_is_kept() -> None:
    redactor = Redactor(allow=(re.compile("default"),))

    assert hide("cancellationToken: default", redactor) == ("cancellationToken: default", ())


def test_allow_must_match_the_whole_value() -> None:
    redactor = Redactor(allow=(re.compile("default"),))

    assert hidden_by(redactor, "token: default-password") == "token: [REDACTED:assignment]"


def test_allow_works_for_every_rule() -> None:
    redactor = Redactor(allow=(re.compile(re.escape(GITHUB_TOKEN)),))

    assert hide(f"see {GITHUB_TOKEN}", redactor)[1] == ()


def hidden_by(redactor: Redactor, text: str) -> str:
    return hide(text, redactor)[0]


def test_a_rule_without_a_secret_group_hides_the_whole_match() -> None:
    redactor = Redactor(rules=(Rule(name="ticket", pattern=re.compile(r"TICKET-\d+")),))

    assert hidden_by(redactor, "see TICKET-42 now") == "see [REDACTED:ticket] now"


def test_a_secret_group_that_matched_nothing_hides_nothing() -> None:
    redactor = Redactor(rules=(Rule(name="optional", pattern=re.compile(r"pin:(?P<secret>\d*)")),))

    assert hide("pin: and pin:", redactor) == ("pin: and pin:", ())


def test_no_rules_hide_nothing() -> None:
    text = f"PASSWORD={PASSWORD}"

    assert hide(text, Redactor(rules=())) == (text, ())


def test_the_marker_names_the_rule() -> None:
    assert marker("assignment") == "[REDACTED:assignment]"


def test_built_in_rules_have_distinct_names() -> None:
    assert len(set(BUILT_IN_NAMES)) == len(BUILT_IN_RULES)


MEBIBYTE = 1024 * 1024


@pytest.mark.parametrize(
    "text",
    [
        "a" * MEBIBYTE,
        "password" * (MEBIBYTE // 8),
        "password " * (MEBIBYTE // 9),
        "token" + "\t" * MEBIBYTE,
        "password=${" + "}" * MEBIBYTE + "x",
        "password=$(" + ")" * MEBIBYTE + "x",
        "password=<" + ">" * MEBIBYTE + "x",
        "password={{" + "}" * MEBIBYTE + "x",
        "password=" + "*" * MEBIBYTE + "x",
        "password='" + "'" * MEBIBYTE,
        '"password"' + ":" * MEBIBYTE,
        "://" + "a:" * (MEBIBYTE // 2),
        "://a:" + "b" * MEBIBYTE,
        "://:" * (MEBIBYTE // 4),
        "eyJ" + "a" * MEBIBYTE,
        ("eyJ" + "a" * 8 + ".") * (MEBIBYTE // 12),
        f"{BEGIN}\n" * (MEBIBYTE // 17),
        "-----BEGIN " + "A" * MEBIBYTE,
        "Authorization:" + " " * MEBIBYTE,
        "tskey-" + "a" * MEBIBYTE,
        "1234567890:" * (MEBIBYTE // 11),
        "ghp_" * (MEBIBYTE // 4),
        "sk-" + "-" * MEBIBYTE,
        'password="' + '\\"' * (MEBIBYTE // 2),
        '"password=' + '\\"' * (MEBIBYTE // 2),
        'password="\\"' * (MEBIBYTE // 12),
        "password=" + 'a"' * (MEBIBYTE // 2),
        "password=" + "'" * MEBIBYTE,
        "://a:" + "@" * MEBIBYTE,
        "Authorization: " + "a" * MEBIBYTE,
        "Proxy-Authorization:" * (MEBIBYTE // 20),
    ],
    ids=lambda text: repr(text[:24]),
)
def test_a_mebibyte_of_worst_case_output_is_redacted_quickly(text: str) -> None:
    started = time.perf_counter()
    hide(text)

    assert time.perf_counter() - started < 5
