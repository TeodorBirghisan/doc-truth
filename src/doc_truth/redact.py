import re
from dataclasses import dataclass, replace

from doc_truth.findings import Identity, ProbeOutput

SECRET_GROUP = "secret"

_NAME_END = (
    r"(?:password|passwd|secret(?:[_-]?key(?:[_-]?base)?)?|token"
    r"|api[_-]?key|access[_-]?key|private[_-]?key)"
)
_NOT_A_SECRET = re.compile(
    r"""(?ix)
    ["']?
    (?: true | false | yes | no | on | off | null | none | nil
      | \$\{ [^}]* \} | \$\( [^)]* \) | < [^>]* > | \{\{ [^}]* \}\}
      | \*+ | redacted | \[ redacted: [a-z0-9-]+ \]
    )?
    ["']?
    [`,;)\]}.]*
    """
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    skips_placeholders: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class Redaction:
    rule: str
    where: str
    line: int


def _rule(name: str, pattern: str, *, skips_placeholders: bool = False) -> Rule:
    return Rule(name=name, pattern=re.compile(pattern), skips_placeholders=skips_placeholders)


BUILT_IN_RULES = (
    _rule(
        "private-key",
        r"(?s)-----BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY-----"
        r".*?(?:-----END [A-Z0-9 ]{0,40}PRIVATE KEY-----|\Z)",
    ),
    _rule(
        "github-token",
        r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})",
    ),
    _rule("gitlab-token", r"(?<![A-Za-z0-9_-])glpat-[A-Za-z0-9_-]{20,}"),
    _rule("slack-token", r"(?<![A-Za-z0-9_-])xox[abeoprs]-[A-Za-z0-9-]{10,}"),
    _rule("aws-access-key", r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Za-z0-9])"),
    _rule("api-key", r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{32,}"),
    _rule("tailscale-key", r"(?<![A-Za-z0-9_-])tskey-[a-z]+-[A-Za-z0-9-]{10,}"),
    _rule(
        "telegram-bot-token",
        r"(?:(?<=/bot)|(?<![A-Za-z0-9_-]))[0-9]{8,10}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])",
    ),
    _rule(
        "jwt",
        r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",
    ),
    _rule(
        "url-password",
        rf"://[^\s/:@]*:(?P<{SECRET_GROUP}>[^\s/?#]+)@",
        skips_placeholders=True,
    ),
    _rule(
        "authorization",
        rf"(?i)(?<![A-Za-z0-9_-])(?:Proxy-)?Authorization:[ \t]*[A-Za-z][A-Za-z0-9-]*[ \t]+"
        rf"(?P<{SECRET_GROUP}>[^\s\"']+)",
        skips_placeholders=True,
    ),
    _rule(
        "assignment",
        rf"(?i)(?P<quote>[\"'])?(?<![A-Za-z0-9_.-])[A-Za-z0-9_.-]*{_NAME_END}"
        rf"(?(quote)|[\"']?)[ \t]*[=:][ \t]*(?P<{SECRET_GROUP}>"
        rf"(?(quote)(?:\\.|(?!(?P=quote))[^\\\n])+"
        rf"|(?:\"(?:\\.|[^\"\\\n])*\"(?![^\s,;)\]}}])"
        rf"|'(?:\\.|[^'\\\n])*'(?![^\s,;)\]}}])"
        rf"|\$\([^()\n]*\)(?![^\s\"])"
        rf"|(?:\"[^\"\n]*\"|'[^'\n]*'|\S)+)))",
        skips_placeholders=True,
    ),
)
BUILT_IN_NAMES = tuple(rule.name for rule in BUILT_IN_RULES)


@dataclass(frozen=True, slots=True, kw_only=True)
class Redactor:
    rules: tuple[Rule, ...] = BUILT_IN_RULES
    allow: tuple[re.Pattern[str], ...] = ()

    def redact(self, text: str, *, where: str) -> tuple[str, tuple[Redaction, ...]]:
        spans = self._spans(text)
        if not spans:
            return text, ()
        pieces: list[str] = []
        redactions: list[Redaction] = []
        position = 0
        line = 1
        for start, end, rule in spans:
            line += text.count("\n", position, start)
            redactions.append(Redaction(rule=rule.name, where=where, line=line))
            pieces += [text[position:start], marker(rule.name)]
            line += text.count("\n", start, end)
            position = end
        pieces.append(text[position:])
        return "".join(pieces), tuple(redactions)

    def _spans(self, text: str) -> list[tuple[int, int, Rule]]:
        found = sorted(
            (start, end, priority)
            for priority, rule in enumerate(self.rules)
            for start, end in self._matches(rule, text)
        )
        merged: list[tuple[int, int, int]] = []
        for start, end, priority in found:
            if merged and start < merged[-1][1]:
                first, last, earlier = merged[-1]
                merged[-1] = (first, max(last, end), min(earlier, priority))
            else:
                merged.append((start, end, priority))
        return [(start, end, self.rules[priority]) for start, end, priority in merged]

    def _matches(self, rule: Rule, text: str) -> list[tuple[int, int]]:
        group = SECRET_GROUP if SECRET_GROUP in rule.pattern.groupindex else 0
        spans = []
        for match in rule.pattern.finditer(text):
            start, end = match.span(group)
            secret = text[start:end]
            if (
                start == end
                or (rule.skips_placeholders and _NOT_A_SECRET.fullmatch(secret))
                or any(allowed.fullmatch(secret) for allowed in self.allow)
            ):
                continue
            spans.append((start, end))
        return spans


def redact_identity(identity: Identity, redactor: Redactor) -> Identity:
    evidence = identity.evidence
    if not isinstance(evidence, ProbeOutput):
        return identity
    lines = frozenset(redactor.redact(line, where="evidence")[0] for line in evidence.lines)
    return replace(identity, evidence=replace(evidence, lines=lines))


def marker(rule: str) -> str:
    return f"[REDACTED:{rule}]"
