import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

MODEL = "claude-sonnet-5-5"
COST_USD = 0.0125
USAGE = {
    "inputTokens": 3,
    "cacheReadInputTokens": 1000,
    "cacheCreationInputTokens": 200,
    "outputTokens": 50,
}


def main() -> int:
    scenario = json.loads(Path(os.environ["FAKE_CLAUDE_SCENARIO"]).read_text(encoding="utf-8"))
    prompt = sys.stdin.buffer.read()
    call = {
        "argv": sys.argv[1:],
        "cwd": os.getcwd(),
        "cwd_entries": os.listdir("."),
        "stdin": prompt.decode(),
    }
    with open(scenario["record"], "a", encoding="utf-8") as record:
        record.write(json.dumps(call) + "\n")
    answers = scenario["answers"]
    for action, *values in scenario["actions"]:
        match action:
            case "out":
                value = values[0]
                line = value if isinstance(value, str) else json.dumps(value)
                sys.stdout.write(line + "\n")
            case "write":
                sys.stdout.write(values[0])
            case "answer":
                key = hashlib.sha256(prompt).hexdigest()
                sys.stdout.write(json.dumps(result_event(answers.get(key, answers.get("*")))))
                sys.stdout.write("\n")
            case "err":
                sys.stderr.write(values[0])
            case "sleep":
                sys.stdout.flush()
                time.sleep(values[0])
            case "child":
                child = subprocess.Popen(["sleep", "30"])
                Path(values[0]).write_text(str(child.pid), encoding="utf-8")
            case "touch":
                Path(values[0]).touch()
            case "exit":
                sys.stdout.flush()
                return int(values[0])
    return 0


def result_event(text: object) -> dict[str, object]:
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": text,
        "total_cost_usd": COST_USD,
        "modelUsage": {MODEL: USAGE},
    }


if __name__ == "__main__":
    sys.exit(main())
