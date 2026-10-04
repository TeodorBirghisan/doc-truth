from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from doc_truth.findings import Finding, FindingsError, parse_answer
from doc_truth.model import Answer
from doc_truth.prompt import Prompt

ATTEMPTS = 2


@dataclass(frozen=True, slots=True, kw_only=True)
class Comparison:
    findings: tuple[Finding, ...]
    answers: tuple[Answer, ...]


class InvalidAnswerError(Exception):
    def __init__(self, problems: Sequence[str], answers: Sequence[Answer]) -> None:
        self.problems = tuple(problems)
        self.answers = tuple(answers)
        listed = "\n".join(f"  - {problem}" for problem in self.problems)
        super().__init__(
            f"the model's answer was unusable {len(self.answers)} times in a row; "
            f"the last one had these problems:\n{listed}"
        )


def compare(prompt: Prompt, ask: Callable[[Prompt], Answer]) -> Comparison:
    answers: list[Answer] = []
    request = prompt
    while True:
        answer = ask(request)
        answers.append(answer)
        try:
            return Comparison(findings=parse_answer(answer.text), answers=tuple(answers))
        except FindingsError as error:
            if len(answers) == ATTEMPTS:
                raise InvalidAnswerError(error.problems, answers) from None
            request = with_rejection(prompt, error.problems)


def with_rejection(prompt: Prompt, problems: Sequence[str]) -> Prompt:
    listed = "\n".join(f"- {problem}" for problem in problems)
    return replace(
        prompt,
        user=(
            f"{prompt.user}\n\n# A rejected answer\n\n"
            "An earlier answer to this message was rejected for these problems:\n\n"
            f"{listed}\n\n"
            "Avoid them, and answer with only the JSON object your instructions describe.\n"
        ),
    )
