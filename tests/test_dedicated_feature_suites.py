"""Offline regressions for dedicated suites through the real Ansible consumer."""

import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
RUNNER_SPEC = importlib.util.spec_from_file_location(
    "dedicated_suite_runner", BASE_DIR / "run-test-suite.py"
)
RUNNER_MODULE = importlib.util.module_from_spec(RUNNER_SPEC)
RUNNER_SPEC.loader.exec_module(RUNNER_MODULE)


@pytest.mark.parametrize("suite_id", ["22-rosa-hcp-private", "23-rosa-hcp-no-cni"])
@pytest.mark.parametrize(
    "version,channel_group",
    [
        (None, None),
        ("4.22", None),
        ("4.22.6", None),
        ("5.0.0-ec.6", None),
        ("4.22.6", "stable"),
    ],
)
def test_dedicated_suite_renders_feature(suite_id, version, channel_group, tmp_path):
    """Resolve suite/CLI vars, extract private subnets, and render without apply."""
    overrides = {"openshift_version": version} if version else {}
    if channel_group:
        overrides["channel_group"] = channel_group
    runner = RUNNER_MODULE.TestSuiteRunner(
        base_dir=BASE_DIR, extra_vars=overrides, ai_agent_enabled=False
    )
    suite = runner.load_test_suite(suite_id)
    assert len(suite["playbooks"]) == 1
    process = MagicMock()
    process.stdout = []
    process.wait.return_value = 0
    with patch.object(RUNNER_MODULE.subprocess, "Popen", return_value=process) as popen:
        assert runner.run_playbook(suite["playbooks"][0], suite["name"])["success"]
    command = popen.call_args.args[0]
    variables = {}
    for index, argument in enumerate(command):
        if argument == "-e":
            value = command[index + 1]
            if value.startswith("{"):
                variables.update(json.loads(value))
            else:
                key, value = value.split("=", 1)
                variables[key] = value

    expected_version = version or "5.0.0-ec.6"
    assert variables["openshift_version"] == expected_version
    assert variables["channel_group"] == (channel_group or "candidate")
    assert variables["create_rosa_network"] == "True"
    assert variables["create_rosa_role_config"] == "True"
    variables.update(
        cluster_name="offline-feature",
        rosa_hcp_namespace="offline-ns",
        deployment_mode="mce",
        domain_prefix="offline",
        machine_pool={},
        cluster_network={},
        create_rosa_roles=True,
        rosa_network_subnets=[
            {
                "privateSubnet": "subnet-1234abcd",
                "publicSubnet": "subnet-5678abcd",
                "availabilityZone": "us-west-2a",
            }
        ],
        output_dir=str(tmp_path / "rendered"),
        supported_versions=["4.22", "5.0"],
    )
    provisioning = yaml.safe_load(
        (BASE_DIR / "tasks/provision_rosa_hcp_with_automation.yml").read_text()
    )
    private_step = next(
        task
        for task in provisioning
        if task["name"] == "Extract private subnets for private cluster"
    )
    for task in private_step["block"]:
        if "include_tasks" in task:
            task["include_tasks"] = str(BASE_DIR / "tasks" / task["include_tasks"])
    creation = next(
        task
        for task in provisioning
        if "block" in task
        and task["name"]
        == "Create RosaControlPlane with references to automated resources"
    )["block"]
    selector = next(
        task for task in creation if task["name"].startswith("Determine which template")
    )
    render = next(
        task
        for task in creation
        if task["name"] == "Create RosaControlPlane from template"
    )
    render["vars"]["apply_immediately"] = False
    render["include_tasks"] = str(BASE_DIR / "tasks" / render["include_tasks"])
    playbook_content = yaml.safe_dump(
        [
            {
                "hosts": "localhost",
                "connection": "local",
                "gather_facts": False,
                "vars": variables,
                "tasks": [private_step, selector, render],
            }
        ]
    )
    with tempfile.TemporaryDirectory(prefix=".offline-", dir=BASE_DIR) as playbook_dir:
        playbook = Path(playbook_dir) / "offline.yml"
        playbook.write_text(playbook_content)
        result = subprocess.run(
            ["ansible-playbook", "-i", "localhost,", str(playbook)],
            cwd=BASE_DIR / "tasks",
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    assert result.returncode == 0, result.stdout + result.stderr
    documents = {
        document["kind"]: document
        for document in yaml.safe_load_all(
            (tmp_path / "rendered/offline-feature-rosa-control-plane.yaml").read_text()
        )
        if document
    }
    control_plane = documents["ROSAControlPlane"]["spec"]
    assert control_plane["version"] == expected_version
    assert documents["ROSAMachinePool"]["spec"]["version"] == expected_version
    assert control_plane["channelGroup"] == (channel_group or "candidate")
    assert control_plane["rosaRoleConfigRef"]["name"] == "offline-feature-roles"
    assert {"Cluster", "ManagedCluster", "MachinePool"} <= documents.keys()
    if suite_id == "22-rosa-hcp-private":
        assert control_plane["endpointAccess"] == "Private"
        assert control_plane["subnets"] == ["subnet-1234abcd"]
        assert control_plane["availabilityZones"] == ["us-west-2a"]
        assert "rosaNetworkRef" not in control_plane
    else:
        assert control_plane["endpointAccess"] == "Public"
        assert control_plane["network"]["networkType"] == "Other"
        assert control_plane["rosaNetworkRef"]["name"] == "offline-feature-network"
