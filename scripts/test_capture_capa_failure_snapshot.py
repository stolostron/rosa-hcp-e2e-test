#!/usr/bin/env python3
"""Tests for capture_capa_failure_snapshot.py.

Every `oc` invocation is mocked: no cluster, AWS or network access.
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


def test_captures_failure_time_control_plane_status(capture):
    code, snapshot, _ = capture(_rcp())
    rcp = snapshot["resources"]["rosacontrolplane"]
    assert code == 0
    assert rcp["spec"]["version"] == "4.22.6" and rcp["spec"]["region"] == "us-west-2"
    assert rcp["spec"]["rosaRoleConfigRef"] == {"name": ROLES}
    assert rcp["spec"]["credentialsSecretRef"] == {"name": "rosa-creds-secret"}
    assert snapshot["phase"] == "pre-cleanup"
    assert rcp["status"]["ready"] is False
    assert rcp["status"]["failureReason"] == "ReconciliationError"
    assert "403" in rcp["status"]["failureMessage"]
    assert "AccessDenied" in rcp["status"]["failureMessage"]
    assert rcp["status"]["oidcEndpointURL"].endswith("2abc3def")
    assert rcp["conditions"][0]["status"] == "False"
    assert rcp["conditions"][0]["reason"] == "ReconciliationError"
    assert snapshot["errors"] == []
    assert snap.OMITTED_MESSAGE not in json.dumps(snapshot)  # benign text kept


def test_captures_state_before_deletion(capture):
    """The regression: a pre-cleanup snapshot has no deletionTimestamp and no
    'deleting' condition, unlike the post-cleanup gather artifact."""
    _, snapshot, _ = capture(_rcp())
    rcp = snapshot["resources"]["rosacontrolplane"]
    assert "deletionTimestamp" not in rcp["metadata"]
    assert all(c.get("reason") != "deleting" for c in rcp["conditions"])


@pytest.mark.parametrize("named", [True, False])
def test_role_config_is_read_only_when_named(capture, named):
    args = (_both(), "--role-config", ROLES) if named else (_rcp(),)
    _, snapshot, fake = capture(*args)
    assert len(fake.calls) == (2 if named else 1)
    if not named:
        assert "rosaroleconfig" not in snapshot["resources"]
        return
    rrc = snapshot["resources"]["rosaroleconfig"]
    assert rrc["status"]["phase"] == "Ready"
    assert rrc["spec"]["operatorRoleConfig"]["oidcID"] == "2abc3def"


@pytest.mark.parametrize(
    "served,expected",
    [
        ("RosaControlPlaneRenamed", "RosaControlPlaneRenamed"),
        (None, "ROSAControlPlane"),
    ],
)
def test_reports_the_kind_the_server_returned(capture, served, expected):
    """The artifact must not assert a kind the cluster never returned."""
    payload = dict(CONTROL_PLANE)
    if served is None:
        payload.pop("kind")
    else:
        payload["kind"] = served
    _, snapshot, _ = capture({"rosacontrolplane": _ok(payload)})
    assert snapshot["resources"]["rosacontrolplane"]["kind"] == expected


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


def test_redact_masks_account_ids_truncates_and_spares_ordinary_text():
    placeholder = snap.ACCOUNT_ID_PLACEHOLDER
    assert (
        snap.redact(f"account {ACCOUNT_ID} denied") == f"account {placeholder} denied"
    )
    assert snap.redact("2026-11-11T09:20:00Z") == "2026-11-11T09:20:00Z"
    assert snap.redact("AccessDenied on role qe6") == "AccessDenied on role qe6"
    result = snap.redact("stalled. " * 300)
    assert result.endswith(snap.TRUNCATION_SUFFIX)
    assert len(result) == snap.MAX_STRING_LENGTH + len(snap.TRUNCATION_SUFFIX)


def test_bounds_the_number_of_conditions():
    many = [
        {"type": f"C{i}", "status": "False"} for i in range(snap.MAX_LIST_ITEMS + 10)
    ]
    assert len(snap.reduce_conditions(many)) == snap.MAX_LIST_ITEMS


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


@pytest.mark.parametrize("use_artifact_dir", [True, False])
def test_snapshot_lands_in_artifact_dir_or_the_fallback(
    capture, monkeypatch, use_artifact_dir
):
    code, snapshot, _ = capture(_rcp(), use_artifact_dir=use_artifact_dir)
    assert code == 0 and snapshot is not None
    written = (capture.artifact_dir if use_artifact_dir else capture.fallback_dir).glob(
        "capa-failure-snapshot-*.json"
    )
    assert list(written)
    assert capture.fallback_dir.exists() is not use_artifact_dir
    monkeypatch.setenv("ARTIFACT_DIR", "   ")  # whitespace-only counts as unset
    assert snap.resolve_output_dir("/tmp/diagnostics") == "/tmp/diagnostics"


def test_snapshot_path_is_printed(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(snap.subprocess, "run", _FakeOC(_rcp()))
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    snap.main(["--cluster-name", CLUSTER, "--namespace", NAMESPACE])
    printed = capsys.readouterr().out.strip()
    assert printed.startswith(str(tmp_path))
    assert Path(printed).is_file()


SENSITIVE_MESSAGES = [
    "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG",  # pragma: allowlist secret
    "GET https://s3/x?X-Amz-Signature=dead&X-Amz-Credential=k",
    "could not read kubeconfig at /tmp/kubeconfig",
    "failed to parse the private key material",
    "password=hunter2 refused",  # pragma: allowlist secret
]


@pytest.mark.parametrize("message", SENSITIVE_MESSAGES)
def test_sensitive_freeform_text_is_omitted_whole(message):
    assert snap.scrub_message(message) == snap.OMITTED_MESSAGE


@pytest.mark.parametrize(
    "value",
    [
        "denied, Authorization: Bearer abc.def.ghi",
        "sha256~Zm9vYmFyCg",  # pragma: allowlist secret
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",  # pragma: allowlist secret
        "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU2Nzg5MDE=",  # pragma: allowlist secret
    ],
)
def test_high_risk_shapes_are_omitted_from_any_field(value):
    """Not just the freeform ones — redact() itself refuses these."""
    assert snap.redact(value) == snap.OMITTED_MESSAGE


def test_url_query_string_is_dropped(capture):
    hostile = json.loads(json.dumps(CONTROL_PLANE))
    hostile["status"][
        "oidcEndpointURL"
    ] = "https://oidc.example/2abc?X-Amz-Signature=dead"
    _, snapshot, _ = capture({"rosacontrolplane": _ok(hostile)})
    url = snapshot["resources"]["rosacontrolplane"]["status"]["oidcEndpointURL"]
    assert url == "https://oidc.example/2abc" + snap.OMITTED_QUERY
    assert "X-Amz-Signature" not in json.dumps(snapshot)


@pytest.mark.parametrize(
    "where,payload,forbidden",
    [
        ("status:failureMessage", "denied, Authorization: Bearer abc.def", "Bearer"),
        ("condition:message", "denied, Authorization: Bearer abc.def", "Bearer"),
        ("condition:reason", "sha256~Zm9vYmFy", "sha256~"),  # pragma: allowlist secret
        (
            "status:id",
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            "eyJ",
        ),  # pragma: allowlist secret
    ],
)
def test_secret_shaped_text_never_reaches_the_artifact(
    capture, where, payload, forbidden
):
    """Freeform *and* structured fields are covered, not just the former."""
    hostile = json.loads(json.dumps(CONTROL_PLANE))
    scope, field = where.split(":")
    target = (
        hostile["status"]["conditions"][0]
        if scope == "condition"
        else hostile["status"]
    )
    target[field] = payload
    _, snapshot, _ = capture({"rosacontrolplane": _ok(hostile)})
    serialized = json.dumps(snapshot)
    assert forbidden not in serialized
    assert snap.OMITTED_MESSAGE in serialized
    # Still diagnosable from the fields that were not omitted.
    assert snapshot["resources"]["rosacontrolplane"]["status"]["ready"] is False


def test_freeform_text_has_a_tighter_length_bound():
    long_benign = "provisioning stalled. " * 60
    result = snap.scrub_message(long_benign)
    assert result.endswith(snap.TRUNCATION_SUFFIX)
    assert len(result) == snap.MAX_MESSAGE_LENGTH + len(snap.TRUNCATION_SUFFIX)
    assert snap.MAX_MESSAGE_LENGTH < snap.MAX_STRING_LENGTH


def test_oc_stderr_is_scrubbed_before_it_is_recorded(capture):
    noisy = _raw("", returncode=1, stderr="error: Authorization: Bearer abc.def.ghi")
    _, snapshot, _ = capture({"rosacontrolplane": noisy})
    joined = " ".join(snapshot["errors"])
    assert "Bearer" not in joined and "abc.def.ghi" not in joined
    assert snap.OMITTED_MESSAGE in joined
