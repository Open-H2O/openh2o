# SPDX-License-Identifier: AGPL-3.0-or-later
"""The files an operator edits or runs must say true things and ask for no hand edits.

One group per fault:

* A site reached only from its own computer can clear the site-address warning.
* The sample settings file matches what the settings read.
* ``.gitignore`` ignores what the native guide creates.
* No file the repository ships names the maintainer's own site.
* A demonstration target refuses on a protected site unless the checkout is the
  demonstration host, in the Makefile and in each script behind it.
* ``make install-cron`` writes this checkout's paths itself and keeps one block, and the
  Caddyfile takes its site address from the environment.

The shell parts run the real scripts in a temporary checkout with stand-ins for ``docker``
and ``crontab``, so nothing here touches a real schedule, container or database.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from django.contrib.sites.models import Site
from django.test import override_settings

from core.checks import SITE_IDENTITY_WARNING_ID, check_site_identity_is_set
from core.models import SiteConfig
from core.site_identity import PLACEHOLDER, apply_site_identity, derive_domain

REPO = Path(__file__).resolve().parent.parent
REAL_HOST = "water.example.org"
AGENCY = "Valley Irrigation District"

BASH = shutil.which("bash") or "bash"


def _text(relative: str) -> str:
    return (REPO / relative).read_text()


# -- Row: a site only its own computer reaches ---------------------------------


class TestSiteAddressOnASingleComputer:
    def test_a_localhost_only_list_gives_localhost(self):
        assert derive_domain(["localhost"]) == "localhost"

    def test_the_first_loopback_name_is_the_fallback(self):
        # Production appends 127.0.0.1 and localhost after the operator's own values.
        assert derive_domain(["127.0.0.1", "localhost"]) == "127.0.0.1"
        assert derive_domain(["localhost", "127.0.0.1"]) == "localhost"

    def test_a_public_host_wins_over_a_loopback_one(self):
        assert derive_domain(["localhost", REAL_HOST]) == REAL_HOST
        assert derive_domain([REAL_HOST, "127.0.0.1", "localhost"]) == REAL_HOST

    def test_a_wildcard_and_the_unspecified_address_still_name_no_host(self):
        assert derive_domain(["*"]) is None
        assert derive_domain(["0.0.0.0", "*.example.org"]) is None  # noqa: S104

    @override_settings(ALLOWED_HOSTS=["localhost"])
    def test_check_is_quiet_once_the_name_is_set(self, db):
        Site.objects.update_or_create(
            pk=1, defaults={"name": PLACEHOLDER, "domain": PLACEHOLDER}
        )
        Site.objects.clear_cache()
        SiteConfig.objects.create(agency_name=AGENCY)

        assert apply_site_identity() is True
        site = Site.objects.get(pk=1)
        assert (site.name, site.domain) == (AGENCY, "localhost")
        assert check_site_identity_is_set(None) == [], (
            "a site whose only address is localhost still gets the example.com warning"
        )

    @override_settings(ALLOWED_HOSTS=["localhost"])
    def test_the_hint_says_what_a_one_computer_site_does(self, db):
        Site.objects.update_or_create(
            pk=1, defaults={"name": PLACEHOLDER, "domain": PLACEHOLDER}
        )
        Site.objects.clear_cache()

        (warning,) = check_site_identity_is_set(None)
        assert warning.id == SITE_IDENTITY_WARNING_ID
        assert "localhost" in warning.hint, warning.hint


# -- Rows: the sample settings file --------------------------------------------

_ENV_NAME = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]{2,})\s*=", re.MULTILINE)

#: Everything that can read an environment variable, outside the tests.
_SKIP_DIRS = {"tests", ".git", ".planning", ".venv", "node_modules", "staticfiles", "backups"}


def _reader_files():
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            if name.endswith((".py", ".sh", ".toml", ".yml", ".yaml")) or name in (
                "Makefile",
                "Dockerfile",
                "Caddyfile",
            ):
                yield Path(root) / name


def _is_read_somewhere(name: str) -> bool:
    quoted = re.compile(rf"""["']{name}["']""")
    bare = re.compile(rf"\b{name}\b")
    for path in _reader_files():
        if path.name == ".env.example":
            continue
        text = path.read_text(errors="ignore")
        pattern = quoted if path.suffix == ".py" else bare
        if pattern.search(text):
            return True
    return False


class TestSampleSettingsFile:
    """Every check turns the file into a plain yes or no before it asserts.

    The file's text never appears in an assertion, so a failure prints a sentence and the
    names involved, never a line of the file itself.
    """

    @pytest.fixture(scope="class")
    def sample(self):
        return _text(".env.example")

    @pytest.fixture(scope="class")
    def names(self, sample):
        return set(_ENV_NAME.findall(sample))

    def test_it_carries_no_setting_nothing_reads(self, names):
        unread = sorted(n for n in names if not _is_read_somewhere(n))
        ok = not unread
        assert ok, f"the sample file names settings that nothing reads: {unread}"

    def test_the_forward_address_that_no_code_reads_is_gone(self, sample):
        gone = "FEEDBACK_FORWARD_URL" not in sample
        assert gone, "the sample file still names FEEDBACK_FORWARD_URL"

    @pytest.mark.parametrize(
        "name",
        [
            "FEEDBACK_ENDPOINT",
            "LOG_DIR",
            "ACCESS_CONTROL_ENFORCED",
            "SECURE_SSL_REDIRECT",
            "SESSION_COOKIE_SECURE",
            "CSRF_COOKIE_SECURE",
            "DJANGO_SUPERUSER_EMAIL",
            "DJANGO_SUPERUSER_PASSWORD",
            "DJANGO_SUPERUSER_USERNAME",
            "OPENH2O_SITE_ADDRESS",
        ],
    )
    def test_it_names_the_setting(self, names, name):
        present = name in names
        assert present, f"the sample file does not name {name}"

    def test_the_modules_comment_does_not_say_blank_runs_all(self, sample, names):
        stale = "omit to run all" in sample.lower()
        assert not stale, "the OPENH2O_MODULES comment still says to omit it to run all"
        named = "OPENH2O_MODULES" in names
        assert named, "the sample file does not name OPENH2O_MODULES"

    def test_the_budget_example_is_not_the_tier_two_figure(self, sample):
        stale = bool(re.search(r"OPENET_MONTHLY_BUDGET\s*=\s*400", sample))
        assert not stale, "the sample file still sets OPENET_MONTHLY_BUDGET=400"

    def test_it_does_not_name_the_maintainers_site(self, sample):
        named = "openh2o.com" in sample.lower()
        assert not named, "the sample file names the maintainer's own site"


# -- Row: .gitignore ------------------------------------------------------------


def _gitignored(relative: str) -> bool:
    """Whether the repository's .gitignore ignores a path.

    The test container has no git, so this reads the file the way git does for the plain
    patterns .gitignore uses here: a trailing slash names a folder, a leading slash anchors
    to the root, a pattern with no slash matches any name along the path, and the last
    matching line wins (a leading ``!`` takes a path back out).
    """
    import fnmatch

    parts = relative.split("/")
    ignored = False
    for raw in _text(".gitignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negate = line.startswith("!")
        pattern = line[1:] if negate else line
        folder_only = pattern.endswith("/")
        pattern = pattern.rstrip("/")
        anchored = pattern.startswith("/") or "/" in pattern
        pattern = pattern.lstrip("/")
        if anchored:
            matched = any(
                fnmatch.fnmatchcase("/".join(parts[: i + 1]), pattern)
                and (i < len(parts) - 1 or not folder_only)
                for i in range(len(parts))
            )
        else:
            matched = any(
                fnmatch.fnmatchcase(part, pattern) and (i < len(parts) - 1 or not folder_only)
                for i, part in enumerate(parts)
            )
        if matched:
            ignored = not negate
    return ignored


_NO_GITIGNORE = pytest.mark.skipif(
    not (REPO / ".gitignore").exists(),
    reason=".dockerignore keeps .gitignore out of the web image",
)


@_NO_GITIGNORE
class TestGitignore:
    """Reads the repository's own ``.gitignore``, which the web image does not carry.

    On the host: ``OPENH2O_MODULES=all python -m pytest tests/test_operator_files_08.py
    --ds=config.settings.local -k Gitignore`` from the checkout. In the image the
    three tests skip.
    """

    def test_a_virtual_environment_is_ignored(self):
        assert _gitignored(".venv/bin/python")

    def test_the_renamed_tailwind_binary_is_ignored(self):
        assert _gitignored("tailwindcss")

    def test_the_matcher_does_not_ignore_everything(self):
        assert not _gitignored("tailwind.config.js")
        assert not _gitignored("core/site_identity.py")
        assert _gitignored(".env")


class TestDeployRefusalPointsAtUpgrade:
    def _refusal(self):
        text = _text("Makefile")
        start = text.index("guard-demo-host:")
        return text[start : text.index("exit 1", start)]

    def test_it_names_make_upgrade(self):
        assert "make upgrade" in self._refusal()

    def test_it_does_not_list_the_old_manual_steps(self):
        refusal = self._refusal()
        assert "git pull origin main" not in refusal
        assert "docker compose up -d --build" not in refusal


# -- Row: the maintainer's own site ----------------------------------------------


class TestNoMaintainerDetailsInShippedFiles:
    FILES = [
        "Caddyfile",
        "scripts/release.sh",
        "config/settings/base.py",
        "config/settings/production.py",
        "Makefile",
        "crontab.txt",
        "docker-compose.yml",
    ]

    @pytest.mark.parametrize("relative", FILES)
    def test_the_file_does_not_name_the_site(self, relative):
        assert "openh2o.com" not in _text(relative).lower(), relative

    def test_the_caddyfile_does_not_name_a_tunnel(self):
        assert "tunnel" not in _text("Caddyfile").lower()

    def test_the_default_sender_is_not_the_maintainers_address(self):
        assert not re.search(r"DEFAULT_FROM_EMAIL.*@openh2o", _text("config/settings/base.py"))

    def test_release_without_a_site_refuses_and_names_the_setting(self, tmp_path):
        env = {k: v for k, v in os.environ.items() if k != "RELEASE_SITE"}
        env["HOME"] = str(tmp_path)
        done = subprocess.run(
            [BASH, str(REPO / "scripts/release.sh"), "REF=abc123"],
            capture_output=True,
            text=True,
            env=env,
            cwd=tmp_path,
            timeout=60,
        )
        assert done.returncode != 0
        assert "RELEASE_SITE" in done.stdout + done.stderr
        assert not list(tmp_path.glob("openh2o-release-*.log")), "it began a release"


# -- Rows handed over from other rows ----------------------------------------------


class TestHandOffs:
    def test_the_browser_xss_switch_is_gone(self):
        assert "SECURE_BROWSER_XSS_FILTER" not in _text("config/settings/production.py")

    def test_the_makefile_has_no_seed_roles_target(self):
        makefile = _text("Makefile")
        assert "seed-roles" not in makefile
        assert "seed_roles" not in makefile

    def test_deploy_has_no_seed_roles_line(self):
        assert "seed_roles" not in _text("DEPLOY.md")

    def test_a_settings_comment_names_no_person_or_date(self):
        lines = _text("config/settings/base.py").splitlines()
        assert not any("Brent" in line for line in lines)
        at = lines.index("ACCOUNT_EMAIL_UNKNOWN_ACCOUNTS = False")
        above = []
        for line in reversed(lines[:at]):
            if not line.startswith("#"):
                break
            above.append(line)
        assert above, "the setting has lost its comment"
        assert not any(re.search(r"\b20\d\d-\d\d-\d\d\b", line) for line in above)


# -- Row: the demonstration targets under a protected checkout -----------------------

#: The sentence only the guard prints (snapshot-demo.sh has refusals of its own).
REFUSAL = "is not the demonstration host"

DEMO_TARGETS = ["demo", "remove-demo", "reset-demo", "snapshot-demo", "calc-rebuild"]


def _make_checkout(tmp_path, *markers):
    """A temporary checkout carrying the real scripts, and stand-ins for docker."""
    co = tmp_path / "co"
    shutil.copytree(REPO / "scripts", co / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("crontab.txt",):
        shutil.copy(REPO / name, co / name)
    for marker in markers:
        (co / marker).write_text("")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "docker"
    fake.write_text("#!/bin/sh\nexit 1\n")
    fake.chmod(0o755)
    return co


def _clean_env(tmp_path):
    env = {
        "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
    }
    (tmp_path / "home").mkdir(exist_ok=True)
    return env


def _run(args, co, tmp_path, **extra):
    env = _clean_env(tmp_path)
    env.update(extra)
    return subprocess.run(
        [BASH, *args], capture_output=True, text=True, cwd=co, env=env, timeout=120
    )


class TestDemonstrationTargetsUnderTheLock:
    def test_every_demonstration_target_runs_the_guard_first(self):
        makefile = _text("Makefile")
        for target in DEMO_TARGETS:
            match = re.search(rf"^{re.escape(target)}:([^#\n]*)", makefile, re.MULTILINE)
            assert match, f"no {target} target"
            prerequisites = match.group(1).split()
            assert prerequisites and prerequisites[0] == "guard-demo-target", (
                f"{target} does not run guard-demo-target first: {prerequisites}"
            )

    @pytest.mark.parametrize("script", ["reset-demo.sh", "snapshot-demo.sh"])
    def test_the_lock_alone_refuses_a_script_run_directly(self, tmp_path, script):
        co = _make_checkout(tmp_path, ".production-lock")
        done = _run([f"scripts/{script}"], co, tmp_path)
        assert done.returncode != 0
        assert REFUSAL in done.stdout + done.stderr
        assert ".production-lock" in done.stdout + done.stderr

    @pytest.mark.parametrize("script", ["reset-demo.sh", "snapshot-demo.sh"])
    @pytest.mark.parametrize("markers", [(".production-lock", ".demo-host"), (".demo-host",), ()])
    def test_the_demonstration_host_and_an_unlocked_checkout_pass_the_guard(
        self, tmp_path, script, markers
    ):
        co = _make_checkout(tmp_path, *markers)
        done = _run([f"scripts/{script}"], co, tmp_path)
        assert REFUSAL not in done.stdout + done.stderr, done.stdout + done.stderr

    @pytest.mark.parametrize("target", DEMO_TARGETS)
    def test_the_guard_script_refuses_each_target_under_the_lock_alone(self, tmp_path, target):
        co = _make_checkout(tmp_path, ".production-lock")
        done = _run(["scripts/guard-demo-target.sh", target, "."], co, tmp_path)
        assert done.returncode == 1
        text = done.stdout + done.stderr
        assert f"'{target}'" in text
        assert REFUSAL in text

    @pytest.mark.parametrize("target", DEMO_TARGETS)
    @pytest.mark.parametrize("markers", [(".production-lock", ".demo-host"), (".demo-host",), ()])
    def test_the_guard_script_passes_the_demonstration_host_and_an_open_checkout(
        self, tmp_path, target, markers
    ):
        co = _make_checkout(tmp_path, *markers)
        done = _run(["scripts/guard-demo-target.sh", target, "."], co, tmp_path)
        assert done.returncode == 0, done.stdout + done.stderr
        assert done.stdout == "" and done.stderr == ""


# -- Row: install-cron and the Caddyfile address ------------------------------------

FAKE_CRONTAB = """#!/bin/sh
f="$FAKE_CRONTAB_FILE"
case "$1" in
  -l) if [ -f "$f" ]; then cat "$f"; else echo "no crontab for nobody" >&2; exit 1; fi ;;
  -) cat > "$f" ;;
  *) exit 2 ;;
esac
"""


@pytest.fixture
def cron(tmp_path):
    co = _make_checkout(tmp_path)
    stand_in = tmp_path / "bin" / "crontab"
    stand_in.write_text(FAKE_CRONTAB)
    stand_in.chmod(0o755)
    store = tmp_path / "installed.txt"

    def install(**extra):
        return _run(
            ["scripts/install-cron.sh"],
            co,
            tmp_path,
            CRONTAB=str(stand_in),
            FAKE_CRONTAB_FILE=str(store),
            **extra,
        )

    install.co = co
    install.store = store
    install.home = tmp_path / "home"
    return install


class TestInstallCron:
    def test_the_shipped_schedule_asks_for_no_edit(self):
        text = _text("crontab.txt")
        assert not re.search(r"^OPENH2O_DIR=", text, re.MULTILINE)
        assert not re.search(r"^OPENH2O_LOG_DIR=", text, re.MULTILINE)
        assert "/opt/openh2o" not in text

    def test_it_writes_this_checkouts_path_and_a_log_folder(self, cron):
        done = cron()
        assert done.returncode == 0, done.stdout + done.stderr
        installed = cron.store.read_text()
        assert f"OPENH2O_DIR={cron.co}\n" in installed
        assert f"OPENH2O_LOG_DIR={cron.home}/openh2o-logs\n" in installed
        assert (cron.home / "openh2o-logs").is_dir()
        assert "scripts/backup.sh" in installed
        assert "run_accounting" in installed

    def test_the_log_folder_can_be_chosen(self, cron, tmp_path):
        chosen = tmp_path / "elsewhere" / "logs"
        done = cron(OPENH2O_LOG_DIR=str(chosen))
        assert done.returncode == 0, done.stdout + done.stderr
        assert f"OPENH2O_LOG_DIR={chosen}\n" in cron.store.read_text()
        assert chosen.is_dir()

    def test_run_twice_it_leaves_one_block(self, cron):
        assert cron().returncode == 0
        assert cron().returncode == 0
        installed = cron.store.read_text()
        assert installed.count("scripts/backup.sh") == 1
        assert installed.count("OPENH2O_DIR=") == 1

    def test_a_line_the_operator_added_outside_the_block_survives(self, cron):
        cron.store.write_text(
            "MAILTO=ops@example.org\n17 4 * * * /usr/local/bin/own-job.sh\n"
        )
        assert cron().returncode == 0
        assert cron().returncode == 0
        installed = cron.store.read_text()
        assert "MAILTO=ops@example.org\n" in installed
        assert installed.count("/usr/local/bin/own-job.sh") == 1

    def test_the_block_follows_a_changed_schedule(self, cron):
        assert cron().returncode == 0
        shutil.copy(REPO / "crontab.txt", cron.co / "crontab.txt")
        (cron.co / "crontab.txt").write_text(
            (cron.co / "crontab.txt").read_text().replace("run_health_checks", "run_health_checks --quick")
        )
        assert cron().returncode == 0
        installed = cron.store.read_text()
        assert "run_health_checks --quick" in installed
        assert installed.count("scripts/backup.sh") == 1

    def test_lines_from_an_older_install_are_refused_not_doubled(self, cron):
        older = "OPENH2O_DIR=/srv/site\nOPENH2O_LOG_DIR=/srv/logs\n25 1 * * * $OPENH2O_DIR/scripts/backup.sh\n"
        cron.store.write_text(older)
        done = cron()
        assert done.returncode != 0
        assert "crontab -e" in done.stdout + done.stderr
        assert cron.store.read_text() == older

    def test_a_ntfy_address_in_the_environment_reaches_the_block(self, cron):
        assert cron(OPENH2O_NTFY_URL="https://ntfy.example.org/topic").returncode == 0
        assert "OPENH2O_NTFY_URL=https://ntfy.example.org/topic\n" in cron.store.read_text()
        assert cron().returncode == 0
        assert not re.search(r"^OPENH2O_NTFY_URL=", cron.store.read_text(), re.MULTILINE)

    def test_make_runs_the_script(self):
        makefile = _text("Makefile")
        match = re.search(r"^install-cron:.*\n((?:\t.*\n)+)", makefile, re.MULTILINE)
        assert match and "scripts/install-cron.sh" in match.group(1)


class TestCaddyAddress:
    def test_the_site_address_comes_from_the_environment_with_80_as_the_default(self):
        lines = [
            line
            for line in _text("Caddyfile").splitlines()
            if line and not line.startswith(("#", " ", "\t")) and line not in ("{", "}")
        ]
        assert lines[0] == "{$OPENH2O_SITE_ADDRESS::80} {", lines[0]

    def test_compose_passes_it_with_80_as_the_default(self):
        compose = _text("docker-compose.yml")
        caddy = compose.split("  caddy:", 1)[1].split("\nvolumes:", 1)[0]
        assert "OPENH2O_SITE_ADDRESS: ${OPENH2O_SITE_ADDRESS:-:80}" in caddy, (
            "an empty value would reach Caddy as a set, empty address, which it refuses"
        )

    def test_deploy_tells_a_public_site_to_set_it_in_env(self):
        deploy = _text("DEPLOY.md")
        assert "OPENH2O_SITE_ADDRESS" in deploy
        reference = deploy.split("## 12.", 1)[1].split("## 13.", 1)[0]
        assert "OPENH2O_SITE_ADDRESS" in reference
        assert "OPENH2O_LOG_DIR" in deploy
