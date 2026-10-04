import pytest

from doc_truth.compare import ATTEMPTS, InvalidAnswerError, compare
from doc_truth.model import Answer, ModelError
from doc_truth.prompt import Prompt

PROMPT = Prompt(version=1, system="The rules.", user="# Documents\n\nThe docs and evidence.\n")
VALID = '{"findings": []}'


def answer(text: str) -> Answer:
    return Answer(
        text=text, models=("m",), input_tokens=10, output_tokens=2, cost_usd=0.01, duration=1.0
    )


class ScriptedModel:
    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.prompts: list[Prompt] = []

    def __call__(self, prompt: Prompt) -> Answer:
        self.prompts.append(prompt)
        return answer(self.texts.pop(0))


def test_a_valid_answer_is_used_at_once() -> None:
    model = ScriptedModel(VALID)

    comparison = compare(PROMPT, model)

    assert comparison.findings == ()
    assert comparison.answers == (answer(VALID),)
    assert model.prompts == [PROMPT]


def test_an_unusable_answer_is_asked_again_with_its_problems() -> None:
    model = ScriptedModel('{"findings": [{}]}', VALID)

    comparison = compare(PROMPT, model)

    assert comparison.answers == (answer('{"findings": [{}]}'), answer(VALID))
    retry = model.prompts[1]
    assert (retry.version, retry.system) == (PROMPT.version, PROMPT.system)
    assert retry.user == (
        PROMPT.user + "\n\n# A rejected answer\n\n"
        "An earlier answer to this message was rejected for these problems:\n\n"
        "- findings[0]: missing kind\n"
        "- findings[0]: missing title\n"
        "- findings[0]: missing doc\n"
        "- findings[0]: missing evidence\n"
        "- findings[0]: missing confidence\n"
        "- findings[0]: missing fix\n"
        "- findings[0]: missing reason\n\n"
        "Avoid them, and answer with only the JSON object your instructions describe.\n"
    )


def test_two_unusable_answers_in_a_row_fail() -> None:
    model = ScriptedModel("Nothing to report.", "[]")

    with pytest.raises(InvalidAnswerError) as caught:
        compare(PROMPT, model)

    assert ATTEMPTS == len(model.prompts) == 2
    assert caught.value.answers == (answer("Nothing to report."), answer("[]"))
    assert caught.value.problems == ("the answer must be a JSON object, found an array",)
    assert str(caught.value) == (
        "the model's answer was unusable 2 times in a row; the last one had these problems:\n"
        "  - the answer must be a JSON object, found an array"
    )
    assert "Expecting value" in model.prompts[1].user


def test_a_failed_call_is_not_retried() -> None:
    def failing(prompt: Prompt) -> Answer:
        raise ModelError("claude failed: Not logged in")

    with pytest.raises(ModelError, match="Not logged in"):
        compare(PROMPT, failing)
