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
      | \$\{ [A-Za-z_][A-Za-z0-9_]* (?: :? [-=?+] (?: \$\{? [A-Za-z_][A-Za-z0-9_]* \}? )? )? \}
      | \$\( [^)]* \) | < [^>]* > | \{\{ [^}]* \}\}
      | \*+ | redacted
    )?
    ["']?
    [`,;)\]}.]*
    """
)
_MARKER = re.compile(r"\[REDACTED:[a-z0-9-]+\]")
_KEY_EDGE = re.compile(r"-----(?:BEGIN|END) [A-Z0-9 ]{0,40}PRIVATE KEY-----")
_KEY_LEFTOVER = re.compile(r"[A-Za-z0-9+/=]+|-----END [A-Z0-9 ]{0,40}PRIVATE KEY-----")
_SCHEMES = "(?:bearer|basic|token|digest|negotiate|ntlm)"
_UNLESS_EMPTY = r"(?:[ \t]++(?!(?-i:[A-Z_][A-Z0-9_]*=(?!=))))?"
_AFTER_A_VALUE = "`,;)]}."


@dataclass(frozen=True, slots=True, kw_only=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    skips_placeholders: bool = False
    spans_lines: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class Redaction:
    rule: str
    where: str
    line: int


def _rule(
    name: str, pattern: str, *, skips_placeholders: bool = False, spans_lines: bool = False
) -> Rule:
    return Rule(
        name=name,
        pattern=re.compile(pattern),
        skips_placeholders=skips_placeholders,
        spans_lines=spans_lines,
    )


BUILT_IN_RULES = (
    _rule(
        "private-key",
        r"(?s)-----BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY-----"
        r".*?(?:-----END [A-Z0-9 ]{0,40}PRIVATE KEY-----|\Z)",
        spans_lines=True,
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
        rf"(?i)(?<![A-Za-z0-9_-])(?:Proxy-)?Authorization:[ \t]*(?:{_SCHEMES}[ \t]+)?"
        rf"(?P<{SECRET_GROUP}>(?!{_SCHEMES}(?![^\s\"']))"
        rf"(?:\"[^\"\n]*\"|'[^'\n]*'|[^\s\"'](?:[^\"'\n]*[^\s\"'])?))",
        skips_placeholders=True,
    ),
    _rule(
        "assignment",
        rf"(?i)(?P<quote>[\"'])?(?<![A-Za-z0-9_.-])[A-Za-z0-9_.-]*{_NAME_END}"
        rf"(?(quote)|[\"']?)(?:[ \t]*:[ \t]*|[ \t]+=[ \t]*|={_UNLESS_EMPTY})"
        rf"(?P<{SECRET_GROUP}>"
        rf"(?(quote)(?:\\.|(?!(?P=quote))[^\\\n])*"
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
        segments = _between_markers(text)
        found = sorted(
            (start, end, priority)
            for priority, rule in enumerate(self.rules)
            for start, end in self._matches(rule, text, segments)
        )
        merged: list[tuple[int, int, int]] = []
        for start, end, priority in found:
            if merged and start < merged[-1][1]:
                first, last, earlier = merged[-1]
                merged[-1] = (first, max(last, end), min(earlier, priority))
            else:
                merged.append((start, end, priority))
        return [(start, end, self.rules[priority]) for start, end, priority in merged]

    def _matches(
        self, rule: Rule, text: str, segments: list[tuple[int, int]]
    ) -> list[tuple[int, int]]:
        group = SECRET_GROUP if SECRET_GROUP in rule.pattern.groupindex else 0
        spans = []
        for segment_start, segment_end in segments:
            for match in rule.pattern.finditer(text, segment_start, segment_end):
                start, end = match.span(group)
                secret = text[start:end]
                if (
                    start == end
                    or (rule.skips_placeholders and _NOT_A_SECRET.fullmatch(secret))
                    or self._allowed(secret)
                ):
                    continue
                spans.append((start, end))
        return spans

    def _allowed(self, secret: str) -> bool:
        bare = _bare(secret)
        return any(allowed.fullmatch(secret) or allowed.fullmatch(bare) for allowed in self.allow)


def _between_markers(text: str) -> list[tuple[int, int]]:
    segments = []
    position = 0
    for found in _MARKER.finditer(text):
        segments.append((position, found.start()))
        position = found.end()
    segments.append((position, len(text)))
    return segments


def _bare(secret: str) -> str:
    value = secret.rstrip(_AFTER_A_VALUE)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def redact_identity(identity: Identity, redactor: Redactor) -> Identity:
    evidence = identity.evidence
    if not isinstance(evidence, ProbeOutput):
        return identity
    lines = sorted(evidence.lines)
    hides_keys = any(rule.spans_lines for rule in redactor.rules)
    if hides_keys and any(_KEY_EDGE.search(line) for line in lines):
        # Stored lines have no order, so what's left of a hidden key is recognised by its shape.
        lines = [line for line in lines if not _KEY_LEFTOVER.fullmatch(line)]
    redacted = frozenset(redactor.redact(line, where="evidence")[0] for line in lines)
    return replace(identity, evidence=replace(evidence, lines=redacted))


def marker(rule: str) -> str:
    return f"[REDACTED:{rule}]"
