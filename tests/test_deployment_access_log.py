# SPDX-License-Identifier: AGPL-3.0-or-later
"""Both shipped deployment shapes must record the HTTP requests they serve.

ISS-121: a deployment built from this repository's own documentation recorded
not one request. `docker compose logs web` and `docker compose logs caddy` each
carried zero lines naming a path — 642 and 102 lines respectively on staging at
`962b9e5`, none of them a request — so an operator asked *"has anyone opened
this page"* had nothing to read. For a public agency that record is also what
answers a records request about the agency's own system.

Turning the log on is three edits in three files, and three edits in three files
is exactly the shape that comes back undone. This module watches the seam:

1. `entrypoint.sh`'s gunicorn `exec` line carries ``--access-logfile``. This is
   the Docker shape's record, and the flag is on the command rather than in a
   config file on purpose — see the SUMMARY for the rejected `gunicorn.conf.py`.
2. The `Caddyfile` declares a ``log`` block with **both** a ``file`` output and a
   ``stderr`` output. Neither alone is enough, and the reasons differ: stderr
   dies with the container on every ``docker compose up -d --build``, so a file
   is what makes the record survive a deploy; and a file alone would leave
   ``docker compose logs caddy`` still reading zero, so the control that found
   ISS-121 could never confirm the fix.
3. `docs/INSTALL-WITHOUT-DOCKER.md`'s ``ExecStart=`` unit file carries
   ``--access-logfile``. This is the native shape's record. The flag must be in
   the unit file itself, not offered later as something to add by hand — an
   operator who never reads §11 still gets the record.
4. That same document no longer calls this *"a known gap in this platform."*
   Phase 112 wrote that sentence and it was true when written. Shipping the fix
   makes it false, and a document describing a closed gap as open is the same
   class of drift the sibling modules in this directory exist to catch.

**Everything goes through one ``scan()``.** Assertions and controls alike. A
control exercising a different code path from the gate proves nothing — Phase
110 learned that one the hard way, and `test_deploy_https_branches.py` says so
in its own docstring for the same reason.

The controls are fixture strings, never the real files, so they keep proving the
scanner works after the real files change again.
"""

import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The gunicorn access-log flag, in either shape. ``-`` on the Docker path
#: (stdout, which is what `docker compose logs web` reads); a real path on the
#: native path, where there is no container log to read.
ACCESS_LOG_FLAG = "--access-logfile"

#: The line that hands the container over to the web server:
#: ``exec gosu app gunicorn config.wsgi:application \``. Matched loosely on
#: ``exec`` + ``gunicorn`` so a change of privilege-dropping tool does not
#: silently un-gate the file.
EXEC_GUNICORN = re.compile(r"^\s*exec\b.*\bgunicorn\b")

#: A systemd unit file's start command, as it appears inside the fenced ``ini``
#: block in the install document. Scoped deliberately: the document also shows
#: the flag in a fenced example elsewhere, and a gate that matched the whole
#: file would have been green before this phase shipped anything.
EXEC_START = re.compile(r"^\s*ExecStart\s*=")

#: A Caddy ``log`` directive opening a block, named or not: ``log {`` and
#: ``log access_file {`` are both site-level log configs. Caddy 2.7+ allows the
#: name; staging runs 2.11.3.
LOG_BLOCK = re.compile(r"^(\s*)log(?:\s+([A-Za-z0-9_.-]+))?\s*\{\s*$")

#: ``output stderr`` / ``output file /var/log/caddy/access.log {`` — the first
#: word after ``output`` is the writer's kind, which is the whole question here.
LOG_OUTPUT = re.compile(r"^\s*output\s+([A-Za-z_][A-Za-z0-9_]*)\b")

#: ``include http.log.access.access_file``. This is the line that fans one site's
#: access entries out to a SECOND sink, and it is only valid in the global
#: options block. Assertion 2 below rests on it — see that test for the measured
#: reason why.
LOG_INCLUDE = re.compile(r"^\s*include\s+(\S+)")

#: Caddy names a site's access logger after the site's `log <name>` block. Two
#: places in the Caddyfile must agree on that name and this is the join.
ACCESS_LOGGER_PREFIX = "http.log.access."

#: The sentence Phase 112 wrote truthfully and this phase makes false.
THE_GAP_SENTENCE = "known gap in this platform"


def _strip_comment(line: str) -> str:
    """Drop a Caddyfile ``#`` comment, keeping the line's own indentation.

    Braces inside comments would otherwise throw off the depth count, and this
    Caddyfile is more comment than directive.
    """
    hash_at = line.find("#")
    if hash_at == -1:
        return line
    return line[:hash_at]


def _logical_line(lines, start_index: int) -> str:
    """One shell/unit command including its backslash continuations.

    Both files being read here wrap their gunicorn invocation across four lines.
    Matching ``--access-logfile`` against the first line alone would report a
    missing flag that is sitting on line three.
    """
    parts = []
    index = start_index
    while index < len(lines):
        text = lines[index].rstrip()
        parts.append(text.rstrip("\\").rstrip())
        if not text.endswith("\\"):
            break
        index += 1
    return " ".join(parts)


@dataclass(frozen=True)
class LogBlock:
    """One Caddy ``log`` block: what it writes to, and whose entries it takes."""

    line: int
    name: str
    outputs: tuple
    includes: tuple

    @property
    def writes_to_a_file(self) -> bool:
        return "file" in self.outputs

    @property
    def writes_to_stderr(self) -> bool:
        return "stderr" in self.outputs


@dataclass(frozen=True)
class AccessLogSeam:
    """Everything the four assertions need, read once from the three files."""

    entrypoint_gunicorn_command: str
    caddy_log_blocks: tuple
    unit_file_exec_start: str
    install_doc_calls_it_a_gap: bool

    @property
    def entrypoint_logs_requests(self) -> bool:
        return ACCESS_LOG_FLAG in self.entrypoint_gunicorn_command

    @property
    def unit_file_logs_requests(self) -> bool:
        return ACCESS_LOG_FLAG in self.unit_file_exec_start

    @property
    def caddy_logs_to_a_file(self) -> bool:
        return any(block.writes_to_a_file for block in self.caddy_log_blocks)

    @property
    def caddy_logs_to_stderr(self) -> bool:
        return any(block.writes_to_stderr for block in self.caddy_log_blocks)

    @property
    def caddy_file_log(self):
        """The block that writes the surviving copy. Its name names the logger."""
        for block in self.caddy_log_blocks:
            if block.writes_to_a_file:
                return block
        return None

    @property
    def caddy_stderr_log(self):
        for block in self.caddy_log_blocks:
            if block.writes_to_stderr:
                return block
        return None

    @property
    def both_caddy_sinks_take_the_same_entries(self) -> bool:
        """Does anything actually reach BOTH sinks?

        Declaring two ``log`` blocks is not enough and this is the whole point
        of the property — see ``test_the_caddyfile_records_requests_to_both_a_file_and_stderr``.
        The site emits access entries to exactly one logger, named after its own
        ``log <name>`` block; a second sink receives them only by naming that
        logger in an ``include``.
        """
        file_log = self.caddy_file_log
        stderr_log = self.caddy_stderr_log
        if file_log is None or stderr_log is None:
            return False
        if file_log is stderr_log:
            return True
        wanted = ACCESS_LOGGER_PREFIX + file_log.name
        return wanted in stderr_log.includes


def _caddy_log_blocks(caddyfile_text: str) -> tuple:
    """Every ``log`` block in the file, with the output kinds inside each.

    Brace-depth counted on comment-stripped lines so that the long explanatory
    comments in this Caddyfile cannot open or close a block by accident.
    """
    blocks = []
    lines = caddyfile_text.splitlines()
    index = 0
    while index < len(lines):
        opener = LOG_BLOCK.match(_strip_comment(lines[index]))
        if not opener:
            index += 1
            continue

        outputs = []
        includes = []
        depth = 1
        cursor = index + 1
        while cursor < len(lines) and depth > 0:
            body = _strip_comment(lines[cursor])
            output = LOG_OUTPUT.match(body)
            if output:
                outputs.append(output.group(1))
            included = LOG_INCLUDE.match(body)
            if included:
                includes.append(included.group(1))
            depth += body.count("{") - body.count("}")
            cursor += 1

        blocks.append(
            LogBlock(
                line=index + 1,
                name=opener.group(2) or "",
                outputs=tuple(outputs),
                includes=tuple(includes),
            )
        )
        index = cursor
    return tuple(blocks)


def scan(
    entrypoint_text: str, caddyfile_text: str, install_doc_text: str
) -> AccessLogSeam:
    """Read the seam out of all three files. Every assertion and control calls this."""
    entrypoint_lines = entrypoint_text.splitlines()
    gunicorn_command = ""
    for number, line in enumerate(entrypoint_lines):
        if EXEC_GUNICORN.match(line):
            gunicorn_command = _logical_line(entrypoint_lines, number)
            break

    install_lines = install_doc_text.splitlines()
    exec_start = ""
    for number, line in enumerate(install_lines):
        if EXEC_START.match(line):
            exec_start = _logical_line(install_lines, number)
            break

    return AccessLogSeam(
        entrypoint_gunicorn_command=gunicorn_command,
        caddy_log_blocks=_caddy_log_blocks(caddyfile_text),
        unit_file_exec_start=exec_start,
        install_doc_calls_it_a_gap=THE_GAP_SENTENCE in install_doc_text,
    )


def _scan_the_real_files() -> AccessLogSeam:
    return scan(
        (REPO_ROOT / "entrypoint.sh").read_text(),
        (REPO_ROOT / "Caddyfile").read_text(),
        (REPO_ROOT / "docs" / "INSTALL-WITHOUT-DOCKER.md").read_text(),
    )


# -- The four assertions ------------------------------------------------------


def test_the_container_starts_gunicorn_with_a_request_record():
    seam = _scan_the_real_files()

    assert seam.entrypoint_gunicorn_command, (
        "entrypoint.sh has no `exec … gunicorn …` line at all, so this gate "
        "cannot read the command that serves requests. Either the container "
        "stopped serving or the regex above stopped matching; both need a human."
    )
    assert seam.entrypoint_logs_requests, (
        f"entrypoint.sh starts gunicorn without {ACCESS_LOG_FLAG!r}, so the "
        "Docker deployment serves every request and records none of them "
        "(ISS-121). The command as read is:\n  "
        f"{seam.entrypoint_gunicorn_command}"
    )


def test_the_caddyfile_records_requests_to_both_a_file_and_stderr():
    seam = _scan_the_real_files()

    assert seam.caddy_log_blocks, (
        "the Caddyfile declares no `log` block, so the traffic-router in front "
        "of the app writes no record of what it was asked for (ISS-121)."
    )
    assert seam.caddy_logs_to_stderr, (
        "no Caddy `log` block writes to stderr, so `docker compose logs caddy` "
        "still answers 'has anyone opened this page' with nothing — which is "
        "the exact control that found ISS-121, and it would stay red. Blocks "
        f"found: {seam.caddy_log_blocks}"
    )
    assert seam.caddy_logs_to_a_file, (
        "no Caddy `log` block writes to a file, so the whole record dies with "
        "the container on the next `docker compose up -d --build`. A record "
        "that a deploy erases is not the record ISS-121 asks for. Blocks "
        f"found: {seam.caddy_log_blocks}"
    )
    assert seam.both_caddy_sinks_take_the_same_entries, (
        "the Caddyfile declares a file sink and a stderr sink, but nothing "
        "routes the site's access entries to both, so one of them will be "
        "silently empty.\n\n"
        "THIS IS A MEASURED FAILURE, NOT A THEORY. Two sibling `log` blocks "
        "inside the site block were tried first, on 2026-08-28. "
        "`caddy validate` printed 'Valid configuration' and the adapted JSON "
        "showed both sinks present — and a real request landed in the file with "
        "stderr at zero, because the adapter sets the site's "
        "`default_logger_name` to the LAST named block and every access entry "
        "goes to that one logger. The fix is a second sink in the GLOBAL "
        "options block carrying `include "
        f"{ACCESS_LOGGER_PREFIX}<the site log block's name>`, which is the only "
        "place `include` is valid.\n\n"
        f"file sink: {seam.caddy_file_log}\nstderr sink: {seam.caddy_stderr_log}"
    )


def test_the_unit_file_starts_gunicorn_with_a_request_record():
    seam = _scan_the_real_files()

    assert seam.unit_file_exec_start, (
        "docs/INSTALL-WITHOUT-DOCKER.md has no `ExecStart=` line, so the "
        "background service this document tells an operator to write cannot be "
        "checked at all."
    )
    assert seam.unit_file_logs_requests, (
        f"the unit file in docs/INSTALL-WITHOUT-DOCKER.md omits {ACCESS_LOG_FLAG!r}. "
        "On this path there is no traffic-router to write the record instead, "
        "so an operator who follows the document and never reads §11 runs an "
        "instance that records nothing. The ExecStart as read is:\n  "
        f"{seam.unit_file_exec_start}"
    )


def test_the_install_document_no_longer_calls_this_an_open_gap():
    seam = _scan_the_real_files()

    assert not seam.install_doc_calls_it_a_gap, (
        f"docs/INSTALL-WITHOUT-DOCKER.md still contains {THE_GAP_SENTENCE!r}. "
        "Phase 112 wrote that truthfully; this phase ships the flag in the unit "
        "file, which makes it false. A document that describes a closed gap as "
        "open sends an operator to do work the platform already did."
    )


# -- The controls -------------------------------------------------------------
#
# Fixture strings, run through the same scan(). Each is a correct set of three
# files with a single thing broken, and each proves one assertion can go red.
# Each control reads the clean fixture first, so a mutation that is reported
# is provably reported BECAUSE of the mutation.

_GOOD_ENTRYPOINT = """\
#!/bin/sh
set -e

exec gosu app gunicorn config.wsgi:application \\
    --bind 0.0.0.0:8000 \\
    --workers 3 \\
    --access-logfile - \\
    --timeout 60
"""

_GLOBAL_STDERR_SINK = """\
{
\tlog access_stderr {
\t\toutput stderr
\t\tformat console
\t\tinclude http.log.access.access_file
\t}
}

"""

_SITE_FILE_SINK = """\
    log access_file {
        output file /var/log/caddy/access.log {
            roll_size 10mb
            roll_keep 5
        }
    }

"""

_GOOD_CADDYFILE = (
    "# A comment mentioning log and { braces } that must not be read as one.\n"
    + _GLOBAL_STDERR_SINK
    + ":80 {\n"
    + "    encode gzip\n\n"
    + _SITE_FILE_SINK
    + """    handle {
        reverse_proxy web:8000 {
            header_up X-Forwarded-Proto https
        }
    }
}
"""
)

_GOOD_INSTALL_DOC = """\
## 5. The background service

```ini
[Service]
ExecStart=<the checkout>/.venv/bin/gunicorn config.wsgi:application \\
    --bind 127.0.0.1:80 --workers 3 --threads 4 \\
    --access-logfile /var/log/openh2o/access.log \\
    --worker-class gthread --timeout 60
```

## 11. No traffic-router on this path

Gunicorn writes the record itself, to the file named above.
"""

_ENTRYPOINT_WITHOUT_THE_FLAG = _GOOD_ENTRYPOINT.replace(
    "    --access-logfile - \\\n", ""
)

_CADDYFILE_WITHOUT_THE_FILE_OUTPUT = _GOOD_CADDYFILE.replace(
    _SITE_FILE_SINK, ""
)

_CADDYFILE_WITHOUT_THE_STDERR_OUTPUT = _GOOD_CADDYFILE.replace(
    _GLOBAL_STDERR_SINK, ""
)

#: The arrangement that was tried first and MEASURED BROKEN on 2026-08-28: two
#: sibling `log` blocks inside the site, no `include` joining them. It passes
#: `caddy validate`, and it writes to the file only. Kept as a fixture so the
#: assertion that catches it can never quietly stop catching it.
_CADDYFILE_WITH_TWO_SIBLING_LOG_BLOCKS = _GOOD_CADDYFILE.replace(
    _GLOBAL_STDERR_SINK, ""
).replace(
    _SITE_FILE_SINK,
    """    log {
        output stderr
        format console
    }
"""
    + _SITE_FILE_SINK,
)

_INSTALL_DOC_WITHOUT_THE_FLAG = _GOOD_INSTALL_DOC.replace(
    "    --access-logfile /var/log/openh2o/access.log \\\n", ""
)

_INSTALL_DOC_STILL_CALLING_IT_A_GAP = _GOOD_INSTALL_DOC.replace(
    "Gunicorn writes the record itself, to the file named above.",
    "That is a known gap in this platform, and it is worth closing here.",
)


def test_an_entrypoint_that_lost_the_flag_is_reported():
    clean = scan(_GOOD_ENTRYPOINT, _GOOD_CADDYFILE, _GOOD_INSTALL_DOC)
    assert clean.entrypoint_logs_requests, (
        "the clean fixture does not read as logging requests, so the mutation "
        "below would prove nothing"
    )

    broken = scan(
        _ENTRYPOINT_WITHOUT_THE_FLAG, _GOOD_CADDYFILE, _GOOD_INSTALL_DOC
    )
    assert not broken.entrypoint_logs_requests, (
        "an entrypoint with the access-log flag deleted still read as logging "
        "requests, so that assertion cannot fail and is not a measurement"
    )


def test_a_caddyfile_that_lost_either_output_is_reported():
    clean = scan(_GOOD_ENTRYPOINT, _GOOD_CADDYFILE, _GOOD_INSTALL_DOC)
    assert clean.caddy_logs_to_a_file and clean.caddy_logs_to_stderr, (
        f"the clean fixture reads as {clean.caddy_log_blocks}, which is not "
        "both outputs, so the mutations below would prove nothing"
    )

    no_file = scan(
        _GOOD_ENTRYPOINT, _CADDYFILE_WITHOUT_THE_FILE_OUTPUT, _GOOD_INSTALL_DOC
    )
    assert not no_file.caddy_logs_to_a_file, (
        "a Caddyfile with the file output deleted still read as writing a "
        "record that survives a container recreate"
    )
    assert no_file.caddy_logs_to_stderr, (
        "deleting the file output also stopped stderr being seen, so the two "
        "halves are not being distinguished and neither assertion is specific"
    )

    no_stderr = scan(
        _GOOD_ENTRYPOINT, _CADDYFILE_WITHOUT_THE_STDERR_OUTPUT, _GOOD_INSTALL_DOC
    )
    assert not no_stderr.caddy_logs_to_stderr, (
        "a Caddyfile with the stderr output deleted still read as answering "
        "`docker compose logs caddy`, which is the ISS-121 control itself"
    )
    assert no_stderr.caddy_logs_to_a_file, (
        "deleting the stderr output also stopped the file being seen, so the "
        "two halves are not being distinguished"
    )


def test_two_sibling_log_blocks_are_reported_as_only_one_record():
    """The real mistake, kept as a control because `caddy validate` blesses it.

    Both sinks are declared and both are found by the scanner, so the two
    output assertions pass. Only the include check can fail here, which is why
    it exists: on 2026-08-28 this exact arrangement adapted cleanly, printed
    "Valid configuration", and then served a request that reached the file and
    never reached stderr.
    """
    clean = scan(_GOOD_ENTRYPOINT, _GOOD_CADDYFILE, _GOOD_INSTALL_DOC)
    assert clean.both_caddy_sinks_take_the_same_entries, (
        "the clean fixture does not route entries to both sinks, so the "
        "mutation below would prove nothing"
    )

    broken = scan(
        _GOOD_ENTRYPOINT,
        _CADDYFILE_WITH_TWO_SIBLING_LOG_BLOCKS,
        _GOOD_INSTALL_DOC,
    )
    assert broken.caddy_logs_to_stderr and broken.caddy_logs_to_a_file, (
        "this control is only meaningful while BOTH output assertions still "
        "pass on it — that is what makes it the case they cannot catch"
    )
    assert not broken.both_caddy_sinks_take_the_same_entries, (
        "two sibling `log` blocks with nothing joining them were read as "
        "recording to both places. They do not: the site emits to one logger "
        "named after its own log block, and the other sink receives nothing."
    )


def test_a_unit_file_that_lost_the_flag_is_reported():
    clean = scan(_GOOD_ENTRYPOINT, _GOOD_CADDYFILE, _GOOD_INSTALL_DOC)
    assert clean.unit_file_logs_requests, (
        "the clean fixture's ExecStart does not read as logging requests, so "
        "the mutation below would prove nothing"
    )

    broken = scan(
        _GOOD_ENTRYPOINT, _GOOD_CADDYFILE, _INSTALL_DOC_WITHOUT_THE_FLAG
    )
    assert not broken.unit_file_logs_requests, (
        "a unit file with the access-log flag deleted still read as logging "
        "requests. The most likely cause is a gate matching the whole document "
        "rather than the ExecStart line — the document shows this flag in more "
        "than one fenced block, and only the unit file's copy is the shipped one"
    )


def test_a_document_that_still_calls_it_a_gap_is_reported():
    clean = scan(_GOOD_ENTRYPOINT, _GOOD_CADDYFILE, _GOOD_INSTALL_DOC)
    assert not clean.install_doc_calls_it_a_gap, (
        "the clean fixture already calls it a gap, so the mutation below would "
        "prove nothing"
    )

    broken = scan(
        _GOOD_ENTRYPOINT, _GOOD_CADDYFILE, _INSTALL_DOC_STILL_CALLING_IT_A_GAP
    )
    assert broken.install_doc_calls_it_a_gap, (
        "a document restored to calling this an open gap was not reported, so "
        "that assertion cannot fail"
    )
