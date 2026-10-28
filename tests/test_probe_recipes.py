import http.server
import os
import re
import shlex
import shutil
import socket
import subprocess
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from examples import fenced_blocks

from doc_truth.collect import find_shell, probe_environment, run_probe
from doc_truth.config import Probe, load_config
from doc_truth.evidence import ProbeResult

ROOT = Path(__file__).resolve().parents[1]
RECIPES = ROOT / "docs" / "probes.md"
SITEMAP_URL = "https://example.com/sitemap.xml"
CRON_FILES = "/etc/crontab /etc/cron.d"

SYSTEMD = Path("/run/systemd/system")
USER_MANAGER = Path(f"/run/user/{os.getuid()}/systemd/private")
TIMER_LIST = r"NEXT +LEFT +LAST +PASSED +UNIT +ACTIVATES\n(.*\n)*\d+ timers? listed\.\n"
TIMER_SCHEDULE = r"\S+\.timer [a-z]+ [a-z]+( \{ On\w+=[^;}]*\})* ?\n"
UNIT_LOOPS = ["timer-schedules", "user-timer-schedules", "on-failure"]

# Like a systemd service: no login session, and systemd's default PATH rather than the
# developer's, so a recipe only passes here if it would work under a timer.
SERVICE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
SERVICE_ENVIRONMENT = {
    **{
        name: value
        for name, value in probe_environment(os.environ).items()
        if name not in {"XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"}
    },
    "PATH": SERVICE_PATH,
}


def readable(path: Path) -> bool:
    return os.access(path, os.R_OK | (os.X_OK if path.is_dir() else 0))


@dataclass(frozen=True, slots=True)
class Check:
    output: str
    needs: tuple[Path | str, ...]

    def missing(self) -> list[str]:
        return [
            str(need)
            for need in self.needs
            if not (
                readable(need) if isinstance(need, Path) else shutil.which(need, path=SERVICE_PATH)
            )
        ]


CHECKS = {
    "systemd-timers": Check(TIMER_LIST, needs=(SYSTEMD,)),
    "timer-schedules": Check(f"({TIMER_SCHEDULE})+", needs=(SYSTEMD,)),
    "user-timers": Check(TIMER_LIST, needs=(USER_MANAGER,)),
    "user-timer-schedules": Check(f"({TIMER_SCHEDULE})*", needs=(USER_MANAGER,)),
    "on-failure": Check(r"(\S+\.service OnFailure=.*\n)+", needs=(SYSTEMD,)),
    "cron": Check(
        r"(/etc/(crontab|cron\.d/[^:]+):.*\n)*",
        needs=(Path("/etc/crontab"), Path("/etc/cron.d")),
    ),
    "restic-version": Check(r"restic \S+ .*\n", needs=("restic",)),
    "backup-restic-version": Check(r"restic \S+ .*\n", needs=("/usr/local/bin/restic",)),
    "kubectl-version": Check(
        r"Client Version: v\S+\n(Kustomize Version: v\S+\n)?", needs=("kubectl",)
    ),
    "docker-version": Check(r"(Docker|podman) version .*\n", needs=("docker",)),
}

needs_curl = pytest.mark.skipif(
    shutil.which("curl", path=SERVICE_PATH) is None, reason="needs curl"
)


def load_recipes(directory: Path) -> list[Probe]:
    path = directory / "doc-truth.toml"
    probes: list[Probe] = []
    for example in fenced_blocks(RECIPES, "toml"):
        path.write_text(f'[[docs]]\npath = "ops.md"\n\n{example}', encoding="utf-8")
        probes.extend(load_config(path).probes)
    return probes


@pytest.fixture(scope="module")
def recipes(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Probe]:
    return {probe.name: probe for probe in load_recipes(tmp_path_factory.mktemp("recipes"))}


def run_recipe(
    probe: Probe, cwd: Path, environment: Mapping[str, str] = SERVICE_ENVIRONMENT
) -> ProbeResult:
    shell = find_shell(SERVICE_ENVIRONMENT)
    return run_probe(probe, shell=shell, cwd=cwd, environment=environment)


def test_every_recipe_is_a_probe_with_notes_and_a_check_of_its_own(tmp_path: Path) -> None:
    probes = load_recipes(tmp_path)
    names = [probe.name for probe in probes]

    assert len(names) == len(set(names))
    assert sorted(names) == sorted([*CHECKS, "sitemap"])
    assert [probe.name for probe in probes if not probe.notes] == []


@pytest.mark.parametrize("document", ["README.md", "docs/configuration.md"])
def test_examples_elsewhere_run_the_recipe_of_the_same_name(
    recipes: dict[str, Probe], document: str, tmp_path: Path
) -> None:
    path = tmp_path / "doc-truth.toml"
    shared: list[Probe] = []
    for example in fenced_blocks(ROOT / document, "toml"):
        path.write_text(example, encoding="utf-8")
        shared += [probe for probe in load_config(path).probes if probe.name in recipes]

    assert shared
    assert [probe.command for probe in shared] == [recipes[probe.name].command for probe in shared]


@pytest.mark.parametrize("name", CHECKS)
def test_the_recipe_works_on_this_host(
    recipes: dict[str, Probe], name: str, tmp_path: Path
) -> None:
    check = CHECKS[name]
    if missing := check.missing():
        pytest.skip(f"needs {', '.join(missing)}")

    result = run_recipe(recipes[name], tmp_path)

    assert result.failure is None, result.stderr
    assert re.fullmatch(check.output, result.stdout), result.stdout


def fake_systemctl(directory: Path, cases: str) -> dict[str, str]:
    bin_dir = directory / "bin"
    bin_dir.mkdir()
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(f'#!/bin/sh\ncase "$*" in\n{cases}esac\n', encoding="utf-8")
    systemctl.chmod(0o755)
    return {**SERVICE_ENVIRONMENT, "PATH": f"{bin_dir}{os.pathsep}{SERVICE_PATH}"}


def test_the_timer_schedules_print_what_the_page_shows(
    recipes: dict[str, Probe], tmp_path: Path
) -> None:
    environment = fake_systemctl(
        tmp_path,
        """\
  *list-units*)
    echo "apt-daily.timer loaded active waiting Daily apt download activities"
    echo "fstrim.timer loaded inactive dead Discard unused filesystem blocks once a week"
    echo "motd-news.timer loaded active waiting Message of the Day" ;;
  *apt-daily.timer*)
    echo "{ OnCalendar=*-*-* 06,18:00:00 ; next_elapse=Wed 2026-10-28 18:21:52 UTC }" ;;
  *fstrim.timer*)
    echo "{ OnCalendar=Mon *-*-* 00:00:00 ; next_elapse=(null) }" ;;
  *motd-news.timer*)
    echo "{ OnStartupUSec=1min ; next_elapse=1min 1.659946s }"
    echo "{ OnCalendar=*-*-* 00,12:00:00 ; next_elapse=Wed 2026-10-28 23:55:01 UTC }" ;;
""",
    )

    result = run_recipe(recipes["timer-schedules"], tmp_path, environment)

    assert result.failure is None, result.stderr
    assert result.stdout in fenced_blocks(RECIPES, "text")


@pytest.mark.parametrize("name", UNIT_LOOPS)
def test_a_unit_loop_asks_only_about_loaded_units(
    recipes: dict[str, Probe], name: str, tmp_path: Path
) -> None:
    environment = fake_systemctl(
        tmp_path,
        """\
  *--state=loaded*)
    echo "a.timer loaded active waiting A"; echo "a.service loaded active running A" ;;
  *list-units*)
    echo "a.timer loaded active waiting A"; echo "a.service loaded active running A"
    echo "ghost.timer not-found inactive dead ghost.timer"
    echo "ghost.service not-found inactive dead ghost.service" ;;
  *) echo "{ OnCalendar=daily ; next_elapse=0 }" ;;
""",
    )

    result = run_recipe(recipes[name], tmp_path, environment)

    assert result.failure is None, result.stderr
    assert "a." in result.stdout
    assert "ghost" not in result.stdout


@pytest.mark.parametrize("name", UNIT_LOOPS)
def test_a_unit_loop_fails_when_systemctl_show_fails(
    recipes: dict[str, Probe], name: str, tmp_path: Path
) -> None:
    environment = fake_systemctl(
        tmp_path,
        """\
  *list-units*) echo "a.timer loaded active waiting A"; echo "a.service loaded active running A" ;;
  *) echo "Failed to connect to bus: No medium found" >&2; exit 1 ;;
""",
    )

    result = run_recipe(recipes[name], tmp_path, environment)

    assert result.exit_code == 1
    assert result.failed
    assert "No medium found" in result.stderr


@pytest.mark.skipif(not SYSTEMD.is_dir(), reason="needs systemd")
@pytest.mark.parametrize(
    ("name", "unit_type"), [("timer-schedules", "timer"), ("on-failure", "service")]
)
def test_a_unit_loop_leaves_out_units_that_are_not_loaded(
    recipes: dict[str, Probe], name: str, unit_type: str, tmp_path: Path
) -> None:
    listing = subprocess.run(
        ["systemctl", "list-units", f"--type={unit_type}", "--all", "--plain", "--no-legend"],
        capture_output=True,
        text=True,
        check=True,
        env=SERVICE_ENVIRONMENT,
    )
    not_loaded = {
        unit for unit, state, *_ in map(str.split, listing.stdout.splitlines()) if state != "loaded"
    }
    if not not_loaded:
        pytest.skip(f"every {unit_type} unit on this host is loaded")

    result = run_recipe(recipes[name], tmp_path)

    assert result.failure is None, result.stderr
    assert not_loaded.isdisjoint(line.split()[0] for line in result.stdout.splitlines())


def cron_recipe(recipes: dict[str, Probe], *paths: Path) -> Probe:
    probe = recipes["cron"]
    assert CRON_FILES in probe.command
    return replace(probe, command=probe.command.replace(CRON_FILES, shlex.join(map(str, paths))))


def test_the_cron_recipe_lists_every_line_but_comments(
    recipes: dict[str, Probe], tmp_path: Path
) -> None:
    crontab = tmp_path / "crontab"
    crontab.write_text("# m h dom mon dow user command\n\nSHELL=/bin/sh\n", encoding="utf-8")
    jobs = tmp_path / "cron.d"
    jobs.mkdir()
    (jobs / "backup").write_text(
        "  # nightly\n\t\n0 2 * * * root restic backup\n", encoding="utf-8"
    )
    linked = tmp_path / "prune"
    linked.write_text("0 4 * * 0 root restic forget\n", encoding="utf-8")
    (jobs / "prune").symlink_to(linked)

    result = run_recipe(cron_recipe(recipes, crontab, jobs), tmp_path)

    assert result.failure is None
    assert sorted(result.stdout.splitlines()) == sorted(
        [
            f"{crontab}:SHELL=/bin/sh",
            f"{jobs}/backup:0 2 * * * root restic backup",
            f"{jobs}/prune:0 4 * * 0 root restic forget",
        ]
    )


def test_the_cron_recipe_succeeds_when_there_are_no_jobs(
    recipes: dict[str, Probe], tmp_path: Path
) -> None:
    crontab = tmp_path / "crontab"
    crontab.write_text("# m h dom mon dow user command\n", encoding="utf-8")
    jobs = tmp_path / "cron.d"
    jobs.mkdir()

    result = run_recipe(cron_recipe(recipes, crontab, jobs), tmp_path)

    assert (result.exit_code, result.stdout, result.failure) == (1, "", None)


def test_the_cron_recipe_fails_when_a_file_is_missing(
    recipes: dict[str, Probe], tmp_path: Path
) -> None:
    crontab = tmp_path / "crontab"
    crontab.write_text("SHELL=/bin/sh\n", encoding="utf-8")

    result = run_recipe(cron_recipe(recipes, crontab, tmp_path / "cron.d"), tmp_path)

    assert result.exit_code == 2
    assert result.failed


@pytest.mark.parametrize("name", ["restic-version", "kubectl-version", "docker-version"])
def test_a_tool_missing_from_path_fails_its_probe(
    recipes: dict[str, Probe], name: str, tmp_path: Path
) -> None:
    result = run_recipe(recipes[name], tmp_path, {**SERVICE_ENVIRONMENT, "PATH": str(tmp_path)})

    assert result.exit_code == 127
    assert result.failed


class Site(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/sitemap.xml":
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
        elif self.path == "/old-sitemap.xml":
            self.send_response(301)
            self.send_header("Location", "/sitemap.xml")
        else:
            self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def site() -> Iterator[str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join()
    server.server_close()


@pytest.fixture
def curl_environment(tmp_path: Path) -> dict[str, str]:
    # The recipe's -q must keep a user's .curlrc out; no_proxy keeps a proxy out of the tests.
    (tmp_path / ".curlrc").write_text("fail\nlocation\n", encoding="utf-8")
    return {**SERVICE_ENVIRONMENT, "CURL_HOME": str(tmp_path), "no_proxy": "*"}


def sitemap_recipe(recipes: dict[str, Probe], url: str) -> Probe:
    probe = recipes["sitemap"]
    assert SITEMAP_URL in probe.command
    return replace(probe, command=probe.command.replace(SITEMAP_URL, url))


@needs_curl
@pytest.mark.parametrize(
    ("path", "answer"),
    [
        ("/sitemap.xml", "status=200 type=application/xml redirect="),
        ("/old-sitemap.xml", "status=301 type= redirect={site}/sitemap.xml"),
        ("/missing.xml", "status=404 type= redirect="),
    ],
    ids=["ok", "redirect", "not-found"],
)
def test_the_http_recipe_records_any_answer(
    recipes: dict[str, Probe],
    site: str,
    curl_environment: dict[str, str],
    tmp_path: Path,
    path: str,
    answer: str,
) -> None:
    result = run_recipe(sitemap_recipe(recipes, site + path), tmp_path, curl_environment)

    assert result.failure is None, result.stderr
    assert result.stdout == answer.format(site=site)


@needs_curl
def test_the_http_recipe_fails_without_an_answer(
    recipes: dict[str, Probe], curl_environment: dict[str, str], tmp_path: Path
) -> None:
    # Bound but not listening, so connections are refused and no other process can take the port.
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]
        result = run_recipe(
            sitemap_recipe(recipes, f"http://127.0.0.1:{port}/"), tmp_path, curl_environment
        )

    assert result.exit_code == 7
    assert result.failed
