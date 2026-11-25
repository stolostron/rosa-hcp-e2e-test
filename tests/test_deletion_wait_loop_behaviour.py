#!/usr/bin/env python3
"""
Behavioural tests for the three ROSA deletion wait loops.

WHY THIS EXISTS
---------------
These loops are shell embedded in YAML, so the usual gates see almost nothing:
yamllint checks the YAML, ansible-lint checks task style, and
`ansible-playbook --syntax-check` does not even load an include_tasks file.
Nothing executed the shell, so a loop could be syntactically perfect and still
never terminate, never detect a stuck resource, or ignore its timeout.

These tests extract each loop's shell body and actually run it against a stub
`oc` on PATH, asserting the three behaviours that matter:

    resource already gone  -> exit 0 immediately
    resource stuck         -> exit 1 early, with #AGENT_CONTEXT
    resource still working -> exit 1 at the configured TIMEOUT, not before

The third is the regression guard for a real defect: an earlier revision
derived its retry count as `timeout / 10`, which assumed a constant 10s sleep.
When exponential backoff (1s..30s) was added, that count stopped corresponding
to elapsed time — a 300s timeout expired after 40s and a 3600s one ran 8420s.
The loops are deadline-based so TIMEOUT means wall-clock seconds.
"""

import os
import shutil
import subprocess
import tempfile
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

BASE_DIR = Path(__file__).parent.parent
DELETION_TASKS = BASE_DIR / "tasks" / "delete_rosa_hcp_resources.yml"

# (task name prefix, resource kind, name env var)
LOOPS = [
    ("Wait for ROSAControlPlane", "rosacontrolplane", "CLUSTER_NAME"),
    ("Wait for ROSANetwork", "rosanetwork", "NETWORK_NAME"),
    ("Wait for ROSARoleConfig", "rosaroleconfig", "ROLE_CONFIG_NAME"),
]

needs_jq = pytest.mark.skipif(
    shutil.which("jq") is None, reason="jq is required by the wait loops"
)


def _loop_body(name_prefix):
    for task in yaml.safe_load(DELETION_TASKS.read_text(encoding="utf-8")) or []:
        if isinstance(task, dict) and task.get("name", "").startswith(name_prefix):
            shell = task.get("ansible.builtin.shell")
            return shell["cmd"] if isinstance(shell, dict) else shell
    raise AssertionError(f"no task found starting with {name_prefix!r}")


def _run(body, stub_oc, env_extra, timeout_s=90):
    """Run a loop body with a stubbed `oc` on PATH. Returns (rc, output, secs)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bindir = tmp / "bin"
        bindir.mkdir()
        oc = bindir / "oc"
        oc.write_text(textwrap.dedent(stub_oc))
        oc.chmod(0o755)
        # `aws` is only reached on the ROSANetwork CF-recovery path; stub it so a
        # machine without the AWS CLI behaves the same as one with it.
        aws = bindir / "aws"
        aws.write_text("#!/bin/sh\necho GONE\nexit 0\n")
        aws.chmod(0o755)

        script = tmp / "loop.sh"
        script.write_text(body)

        env = dict(os.environ)
        env["PATH"] = f"{bindir}:{env['PATH']}"
        env.update(
            {
                "LOGFILE": str(tmp / "log.txt"),
                "CLUSTER_NAME": "c1",
                "NETWORK_NAME": "n1",
                "ROLE_CONFIG_NAME": "r1",
                "NAMESPACE": "ns",
                "STACK_NAME": "stack",
                "REGION": "us-west-2",
                "STUCK_AFTER": "1200",
                "FINALIZER_STUCK_AFTER": "300",
                "CF_CHECK_INTERVAL": "30",
            }
        )
        env.update(env_extra)

        start = datetime.now()
        proc = subprocess.run(
            ["sh", str(script)],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        secs = (datetime.now() - start).total_seconds()
        return proc.returncode, proc.stdout + proc.stderr, secs


@pytest.mark.parametrize("prefix,kind,_name", LOOPS)
def test_exits_zero_when_resource_already_gone(prefix, kind, _name):
    rc, out, secs = _run(
        _loop_body(prefix),
        f"""\
        #!/bin/sh
        echo 'Error from server (NotFound): {kind} "x" not found' >&2
        exit 1
        """,
        {"TIMEOUT": "30"},
    )
    assert rc == 0, f"expected success when the resource is gone, got {rc}\n{out}"
    assert secs < 10, f"should exit immediately, took {secs:.1f}s"
    assert "deleted successfully" in out


@needs_jq
@pytest.mark.parametrize("prefix,kind,_name", LOOPS)
def test_detects_a_stuck_resource_and_exits_early(prefix, kind, _name):
    """An old deletionTimestamp must trip stuck detection well before TIMEOUT."""
    rc, out, secs = _run(
        _loop_body(prefix),
        """\
        #!/bin/sh
        echo '{"metadata":{"name":"x","deletionTimestamp":"2020-01-01T00:00:00Z","finalizers":[]}}'
        exit 0
        """,
        {"TIMEOUT": "60", "CF_CHECK_INTERVAL": "9999"},
    )
    assert rc == 1, f"expected failure for a stuck resource, got {rc}\n{out}"
    assert secs < 30, f"should exit early, not run the full 60s (took {secs:.1f}s)"
    assert "status=stuck_deleting" in out, f"missing agent context:\n{out}"


@needs_jq
@pytest.mark.parametrize("prefix,kind,_name", LOOPS)
def test_honours_the_configured_timeout(prefix, kind, _name):
    """
    A resource that is deleting normally (recent timestamp, no finalizers) must
    run until TIMEOUT — not stop early because a retry count ran out.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    budget = 6
    rc, out, secs = _run(
        _loop_body(prefix),
        f"""\
        #!/bin/sh
        echo '{{"metadata":{{"name":"x","deletionTimestamp":"{now}","finalizers":[]}}}}'
        exit 0
        """,
        {"TIMEOUT": str(budget), "CF_CHECK_INTERVAL": "9999"},
    )
    assert rc == 1, f"expected timeout failure, got {rc}\n{out}"
    assert budget - 1 <= secs <= budget + 4, (
        f"expected to run ~{budget}s (the configured TIMEOUT), ran {secs:.1f}s.\n"
        "A large undershoot means the loop is bounded by an iteration count "
        "rather than a wall-clock deadline.\n" + out
    )
    assert "Timed out" in out
