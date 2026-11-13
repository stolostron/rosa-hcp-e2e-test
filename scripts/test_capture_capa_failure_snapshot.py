#!/usr/bin/env python3
"""Tests for capture_capa_failure_snapshot.py.

Every `oc` invocation is mocked: these tests never contact a cluster, an AWS
account, or any network endpoint.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import capture_capa_failure_snapshot as snap  # noqa: E402

CLUSTER = "qe6-rosa-hcp"
NAMESPACE = "ns-rosa-hcp"
ROLES = "qe6-rosa-hcp-roles"
ACCOUNT_ID = "123456789012"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT_ID}:role/qe6-Installer-Role"
ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"  # pragma: allowlist secret

# A deliberately hostile RosaControlPlane: it carries annotations, labels,
# managedFields, an inline kubeconfig and a token alongside the fields the
# snapshot is allowed to keep.
CONTROL_PLANE = {
    "apiVersion": "controlplane.cluster.x-k8s.io/v1beta2",
    "kind": "ROSAControlPlane",
    "metadata": {
        "name": CLUSTER,
        "namespace": NAMESPACE,
        "creationTimestamp": "2026-11-11T09:01:02Z",
        "annotations": {"automation.acm.redhat.com/description": "secret-ish note"},
        "labels": {"cluster.x-k8s.io/cluster-name": CLUSTER},
        "managedFields": [{"manager": "capa-controller-manager"}],
        "uid": "4a1c0f3e-0000-0000-0000-000000000001",
    },
    "spec": {
        "version": "4.22.6",
        "channelGroup": "stable",
        "region": "us-west-2",
        "rosaClusterName": CLUSTER,
        "domainPrefix": "qe6",
        "rosaRoleConfigRef": {"name": ROLES},
        "rosaNetworkRef": {"name": "qe6-rosa-hcp-network"},
        "credentialsSecretRef": {"name": "rosa-creds-secret"},
        "additionalTags": {"purpose": "testing"},
        "kubeconfig": "apiVersion: v1\nusers:\n- user:\n    token: sha256~supersecret",
        "token": "sha256~another-secret",
    },
    "status": {
        "ready": False,
        "id": "2abc3def",
        "failureReason": "ReconciliationError",
        "failureMessage": (
            "operation error STS: AssumeRole, https response error StatusCode: 403, "
            f"api error AccessDenied: User arn:aws:sts::{ACCOUNT_ID}:assumed-role/capa "
            f"is not authorized to perform: sts:AssumeRole on resource: {ROLE_ARN}"
        ),
        "oidcEndpointURL": "https://oidc.op1.openshiftapps.com/2abc3def",
        "conditions": [
            {
                "type": "Ready",
                "status": "False",
                "reason": "ReconciliationError",
                "message": f"AccessDenied assuming {ROLE_ARN}",
                "lastTransitionTime": "2026-11-11T09:20:00Z",
                "observedGeneration": 3,  # not allowlisted
            }
        ],
        "externalManagedControlPlane": True,
    },
}

ROLE_CONFIG = {
    "kind": "ROSARoleConfig",
    "metadata": {
        "name": ROLES,
        "namespace": NAMESPACE,
        "creationTimestamp": "2026-11-11T09:00:00Z",
        "annotations": {"automation.acm.redhat.com/timestamp": "2026-11-11T09:00:00Z"},
        "managedFields": [{"manager": "ansible"}],
    },
    "spec": {
        "oidcProviderType": "Managed",
        "accountRoleConfig": {"prefix": "qe6", "version": "4.22.6"},
        "operatorRoleConfig": {"prefix": "qe6", "oidcID": "2abc3def"},
    },
    "status": {
        "ready": True,
        "phase": "Ready",
        "oidcID": "2abc3def",
        "oidcProviderArn": f"arn:aws:iam::{ACCOUNT_ID}:oidc-provider/oidc.op1/2abc3def",
        "installerRoleArn": ROLE_ARN,
        "conditions": [{"type": "Ready", "status": "True", "reason": "Created"}],
    },
}


class _FakeOC:
    """Stand-in for subprocess.run that serves canned `oc get` responses."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        response = self.responses[command[2].split("/")[0]]
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, type) and issubclass(response, BaseException):
            raise response(cmd=command, timeout=kwargs.get("timeout"))
        return response


def _ok(payload):
    """A successful `oc get -o json` returning `payload`."""
    return subprocess.CompletedProcess(
        args=["oc"], returncode=0, stdout=json.dumps(payload), stderr=""
    )


def _raw(stdout, returncode=0, stderr=""):
    """An `oc get` returning arbitrary bytes on stdout."""
    return subprocess.CompletedProcess(
        args=["oc"], returncode=returncode, stdout=stdout, stderr=stderr
    )


@pytest.fixture
def capture(monkeypatch, tmp_path):
    """Run main() against a mocked `oc`; yields (code, snapshot, fake_oc)."""
    artifact_dir = tmp_path / "art"
    fallback_dir = tmp_path / "fallback"

    def _run(responses, *extra_args, use_artifact_dir=True):
        fake = _FakeOC(responses)
        monkeypatch.setattr(snap.subprocess, "run", fake)
        if use_artifact_dir:
            monkeypatch.setenv("ARTIFACT_DIR", str(artifact_dir))
        else:
            monkeypatch.delenv("ARTIFACT_DIR", raising=False)
        code = snap.main(
            ["--cluster-name", CLUSTER, "--namespace", NAMESPACE]
            + ["--fallback-dir", str(fallback_dir), *extra_args]
        )
        target = artifact_dir if use_artifact_dir else fallback_dir
        found = sorted(target.glob("capa-*.json")) if target.exists() else []
        return code, (json.loads(found[0].read_text()) if found else None), fake

    _run.artifact_dir = artifact_dir
    _run.fallback_dir = fallback_dir
    return _run


def _rcp():
    """The default response set: one failed control plane."""
    return {"rosacontrolplane": _ok(CONTROL_PLANE)}


def _both():
    """Control plane plus role config, both readable."""
    return {"rosacontrolplane": _ok(CONTROL_PLANE), "rosaroleconfig": _ok(ROLE_CONFIG)}


# ================================================================
# Normal capture
# ================================================================


def test_captures_failure_time_control_plane_status(capture):
    code, snapshot, _ = capture(_rcp())
    rcp = snapshot["resources"]["rosacontrolplane"]
    assert code == 0
    assert snapshot["phase"] == "pre-cleanup"
    assert rcp["status"]["ready"] is False
    assert rcp["status"]["failureReason"] == "ReconciliationError"
    assert "403" in rcp["status"]["failureMessage"]
    assert rcp["status"]["oidcEndpointURL"].endswith("2abc3def")
    assert rcp["conditions"][0]["status"] == "False"
    assert rcp["conditions"][0]["reason"] == "ReconciliationError"
    assert snapshot["errors"] == []


def test_captures_state_before_deletion(capture):
    """The regression: a pre-cleanup snapshot has no deletionTimestamp and no
    'deleting' condition, unlike the post-cleanup gather artifact."""
    _, snapshot, _ = capture(_rcp())
    rcp = snapshot["resources"]["rosacontrolplane"]
    assert "deletionTimestamp" not in rcp["metadata"]
    assert all(c.get("reason") != "deleting" for c in rcp["conditions"])


def test_captures_spec_and_references_by_name_only(capture):
    _, snapshot, _ = capture(_rcp())
    spec = snapshot["resources"]["rosacontrolplane"]["spec"]
    assert spec["rosaRoleConfigRef"] == {"name": ROLES}
    assert spec["credentialsSecretRef"] == {"name": "rosa-creds-secret"}
    assert spec["version"] == "4.22.6"
    assert spec["region"] == "us-west-2"


def test_captures_role_config_when_requested(capture):
    _, snapshot, fake = capture(_both(), "--role-config", ROLES)
    rrc = snapshot["resources"]["rosaroleconfig"]
    assert rrc["status"]["phase"] == "Ready"
    assert rrc["spec"]["operatorRoleConfig"]["oidcID"] == "2abc3def"
    assert len(fake.calls) == 2


def test_skips_role_config_when_not_named(capture):
    _, snapshot, fake = capture(_rcp())
    assert "rosaroleconfig" not in snapshot["resources"]
    assert len(fake.calls) == 1


def test_reports_the_kind_the_server_returned(capture):
    """The artifact must not assert a kind the cluster never returned."""
    renamed = dict(CONTROL_PLANE, kind="RosaControlPlaneRenamed")
    _, snapshot, _ = capture({"rosacontrolplane": _ok(renamed)})
    assert (
        snapshot["resources"]["rosacontrolplane"]["kind"] == "RosaControlPlaneRenamed"
    )


def test_falls_back_to_the_expected_kind_when_absent(capture):
    kindless = {k: v for k, v in CONTROL_PLANE.items() if k != "kind"}
    _, snapshot, _ = capture({"rosacontrolplane": _ok(kindless)})
    assert snapshot["resources"]["rosacontrolplane"]["kind"] == "ROSAControlPlane"


# ================================================================
# Allowlist and redaction
# ================================================================


def test_allowlist_drops_metadata_secrets_and_unknown_fields(capture):
    _, snapshot, _ = capture(_both(), "--role-config", ROLES)
    serialized = json.dumps(snapshot)
    for forbidden in (
        "annotations",
        "labels",
        "managedFields",
        "kubeconfig",
        "sha256~",
        "supersecret",
        "additionalTags",
        "uid",
        "observedGeneration",
        "externalManagedControlPlane",
        "secret-ish note",
    ):
        assert forbidden not in serialized, f"{forbidden} leaked into the snapshot"


def test_redacts_aws_account_ids(capture):
    _, snapshot, _ = capture(_both(), "--role-config", ROLES)
    serialized = json.dumps(snapshot)
    assert ACCOUNT_ID not in serialized
    assert snap.ACCOUNT_ID_PLACEHOLDER in serialized
    # Redaction keeps the ARN shape so the role can still be identified.
    assert "role/qe6-Installer-Role" in serialized


def test_access_key_in_failure_message_never_reaches_the_artifact(capture):
    hostile = json.loads(json.dumps(CONTROL_PLANE))
    hostile["status"][
        "failureMessage"
    ] = f"AuthFailure: the key {ACCESS_KEY} used by {ROLE_ARN} is not authorized"
    _, snapshot, _ = capture({"rosacontrolplane": _ok(hostile)})
    serialized = json.dumps(snapshot)
    assert ACCESS_KEY not in serialized
    assert ACCOUNT_ID not in serialized
    assert "AuthFailure" in serialized  # the diagnosis survives redaction


@pytest.mark.parametrize(
    "key_id",
    [
        "AKIAIOSFODNN7EXAMPLE",  # pragma: allowlist secret
        "ASIAY34FZKBOKMUTVV7A",  # pragma: allowlist secret
        "AROAX3EXAMPLEIDHERE1",  # pragma: allowlist secret
    ],
)
def test_redacts_aws_key_and_principal_ids(key_id):
    masked = snap.redact(f"The security token {key_id} is invalid")
    assert key_id not in masked
    assert snap.ACCESS_KEY_PLACEHOLDER in masked


def test_redacts_bare_account_id_but_leaves_other_text_alone():
    assert snap.redact(f"account {ACCOUNT_ID} denied") == (
        f"account {snap.ACCOUNT_ID_PLACEHOLDER} denied"
    )
    assert snap.redact("2026-11-11T09:20:00Z") == "2026-11-11T09:20:00Z"
    assert snap.redact("AccessDenied on role qe6") == "AccessDenied on role qe6"


def test_truncates_long_strings():
    result = snap.redact("x" * (snap.MAX_STRING_LENGTH + 500))
    assert result.endswith(snap.TRUNCATION_SUFFIX)
    assert len(result) == snap.MAX_STRING_LENGTH + len(snap.TRUNCATION_SUFFIX)


def test_bounds_the_number_of_conditions():
    many = [
        {"type": f"C{i}", "status": "False"} for i in range(snap.MAX_LIST_ITEMS + 10)
    ]
    assert len(snap.reduce_conditions(many)) == snap.MAX_LIST_ITEMS


# ================================================================
# Bounded, read-only collection
# ================================================================


def test_oc_calls_are_read_only_typed_and_namespaced(capture):
    _, _, fake = capture(_both(), "--role-config", ROLES, "--timeout", "7")
    for command, kwargs in fake.calls:
        assert command[:2] == ["oc", "get"]
        assert command[3:] == ["-n", NAMESPACE, "-o", "json"]
        assert kwargs["timeout"] == 7
        assert kwargs["stdin"] is subprocess.DEVNULL
    assert [c[0][2] for c in fake.calls] == [
        f"rosacontrolplane/{CLUSTER}",
        f"rosaroleconfig/{ROLES}",
    ]


def test_default_timeout_is_not_increased():
    assert snap.DEFAULT_TIMEOUT_SECONDS == 30


# ================================================================
# Failure handling: the capture never breaks the run
# ================================================================


@pytest.mark.parametrize(
    "response,expected",
    [
        (_raw("", returncode=1, stderr="Error: not found"), "exited 1"),
        (subprocess.TimeoutExpired, "timed out"),
        (FileNotFoundError("oc"), "oc binary not found"),
        (_raw("{not json"), "could not parse JSON"),
        (_raw("null"), "non-object JSON"),
        (_raw("[]"), "non-object JSON"),
        (OSError("boom"), "failed to run oc"),
    ],
)
def test_capture_errors_are_recorded_and_exit_zero(capture, response, expected):
    code, snapshot, _ = capture({"rosacontrolplane": response})
    assert code == 0
    assert snapshot["resources"]["rosacontrolplane"] is None
    assert any(expected in err for err in snapshot["errors"])


def test_every_missing_resource_is_explained_by_an_error(capture):
    """A null resource must never appear with an empty error list."""
    _, snapshot, _ = capture(
        {"rosacontrolplane": _raw("null"), "rosaroleconfig": _raw("null")},
        "--role-config",
        ROLES,
    )
    missing = [k for k, v in snapshot["resources"].items() if v is None]
    assert missing and len(snapshot["errors"]) >= len(missing)


def test_role_config_failure_does_not_lose_control_plane_snapshot(capture):
    code, snapshot, _ = capture(
        {
            "rosacontrolplane": _ok(CONTROL_PLANE),
            "rosaroleconfig": subprocess.TimeoutExpired,
        },
        "--role-config",
        ROLES,
    )
    assert code == 0
    assert snapshot["resources"]["rosacontrolplane"]["status"]["ready"] is False
    assert snapshot["resources"]["rosaroleconfig"] is None
    assert any("timed out" in err for err in snapshot["errors"])


def test_unwritable_output_directory_exits_zero(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(snap.subprocess, "run", _FakeOC(_rcp()))
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("occupied")
    monkeypatch.setenv("ARTIFACT_DIR", str(blocker / "sub"))
    code = snap.main(["--cluster-name", CLUSTER, "--namespace", NAMESPACE])
    assert code == 0
    assert "could not write snapshot" in capsys.readouterr().err


def test_unexpected_internal_error_exits_zero(monkeypatch, tmp_path, capsys):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("x")

    monkeypatch.setattr(snap, "build_snapshot", _boom)
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    code = snap.main(["--cluster-name", CLUSTER, "--namespace", NAMESPACE])
    assert code == 0
    assert "snapshot capture failed" in capsys.readouterr().err


# ================================================================
# Output location
# ================================================================


def test_artifact_dir_is_preferred_when_set(capture):
    code, snapshot, _ = capture(_rcp())
    assert code == 0 and snapshot is not None
    assert not capture.fallback_dir.exists()


def test_fallback_dir_used_when_artifact_dir_absent(capture):
    code, snapshot, _ = capture(_rcp(), use_artifact_dir=False)
    assert code == 0 and snapshot is not None
    assert list(capture.fallback_dir.glob("capa-failure-snapshot-*.json"))


def test_blank_artifact_dir_falls_back(monkeypatch):
    monkeypatch.setenv("ARTIFACT_DIR", "   ")
    assert snap.resolve_output_dir("/tmp/diagnostics") == "/tmp/diagnostics"


def test_snapshot_path_is_printed(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(snap.subprocess, "run", _FakeOC(_rcp()))
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    snap.main(["--cluster-name", CLUSTER, "--namespace", NAMESPACE])
    printed = capsys.readouterr().out.strip()
    assert printed.startswith(str(tmp_path))
    assert Path(printed).is_file()
