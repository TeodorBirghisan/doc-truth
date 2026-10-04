import time
from pathlib import Path


def alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        return False
    return state != "Z"


def gone(pid: int, *, within: float = 3.0) -> bool:
    give_up = time.monotonic() + within
    while alive(pid):
        if time.monotonic() > give_up:
            return False
        time.sleep(0.02)
    return True
