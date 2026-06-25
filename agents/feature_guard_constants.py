"""
Shared constants and pure functions for the feature doc system.
"""

import re
from typing import Dict, List, Tuple

REDACTION_PATTERNS: List[Tuple[str, str]] = [
    (r'arn:aws:[a-z0-9-]+:[a-z0-9-]*:\d{12}:[^\s,\]"]+', "arn:aws:***:***:***:***"),
    (r'sg-[0-9a-f]{8,17}', "sg-<id>"),
    (r'vpc-[0-9a-f]{8,17}', "vpc-<id>"),
    (r'subnet-[0-9a-f]{8,17}', "subnet-<id>"),
    (r'igw-[0-9a-f]{8,17}', "igw-<id>"),
    (r'nat-[0-9a-f]{8,17}', "nat-<id>"),
    (r'rtb-[0-9a-f]{8,17}', "rtb-<id>"),
    (r'eni-[0-9a-f]{8,17}', "eni-<id>"),
    (r'i-[0-9a-f]{8,17}', "i-<id>"),
    (r'ami-[0-9a-f]{8,17}', "ami-<id>"),
    (r'vol-[0-9a-f]{8,17}', "vol-<id>"),
    (r'snap-[0-9a-f]{8,17}', "snap-<id>"),
    (r'AKIA[0-9A-Z]{16}', "<access-key-id>"),
    (r'https?://api\.[a-z0-9.-]+\.openshiftapps\.com[^\s]*', "https://api.<cluster>.<domain>:443"),
    (r'https?://console-openshift-console\.[a-z0-9.-]+\.openshiftapps\.com[^\s]*', "https://console.<cluster>.<domain>"),
    (r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', "<uuid>"),
    (r'\b\d{12}\b(?=\s|$|[,\]}])', "<account-id>"),
]

FEATURE_FILE_PATTERNS: Dict[str, List[str]] = {
    "security_groups": [
        "tasks/create_security_group.yml",
        "tasks/delete_security_group.yml",
    ],
    "etcd_kms": [],
    "fips": [],
    "external_oidc": [],
    "no_cni": [],
    "private_network": [],
}

SHARED_FILE_PATTERNS: List[str] = [
    "tasks/provision_rosa_hcp_with_automation.yml",
    "tasks/delete_rosa_hcp_resources.yml",
    "tasks/create_rosa_control_plane_versioned.yml",
    "feature_manager.py",
    "templates/schemas/feature-registry.yml",
    "templates/versions/*/features/*.yaml.j2",
]

IGNORED_PATH_PREFIXES: List[str] = [
    "tests/",
    "docs/",
    "scripts/",
    "agents/",
    "test-results/",
    ".github/",
]

ADVISORY_KEYWORD_MAP: Dict[str, List[str]] = {
    "fips": ["fips", "fips-140", "fips 140", "cryptographic", "crypto module"],
    "etcd_kms": ["etcd", "kms", "encryption at rest", "etcdEncryptionKMS"],
    "security_groups": ["security group", "securitygroup", "additionalSecurityGroups", "firewall rule"],
    "external_oidc": ["oidc", "openid connect", "external auth", "identity provider", "oauth"],
    "no_cni": ["cni", "network plugin", "networkType", "cilium", "calico", "ovn"],
    "private_network": ["private cluster", "endpoint access", "private endpoint", "endpointAccess"],
    "additional_tags": ["resource tag", "additionalTags", "aws tag"],
    "domain_prefix": ["domain prefix", "domainPrefix", "dns"],
    "channel_group": ["channel group", "channelGroup", "upgrade channel"],
    "image_registry": ["image registry", "registry config", "clusterRegistryConfig", "container registry"],
    "parallel_upgrade": ["rolling update", "node upgrade", "rollingUpdate", "maxSurge", "maxUnavailable"],
    "disk_size": ["disk size", "volume size", "volumeSize", "root volume", "ebs"],
    "availability_zones": ["availability zone", "multi-az", "az", "availabilityZones"],
    "user_agent": ["user agent", "userAgent"],
    "default_autoscaling": ["autoscal", "machine pool scaling", "defaultMachinePoolSpec"],
    "cluster_autoscaler_expander": ["cluster autoscaler", "expander", "autoscaler expander"],
    "audit_logging": ["audit log", "cloudwatch", "log forward", "cloudWatchlogForwarder"],
}

UPSTREAM_REPO = "stolostron/cluster-api-provider-aws"

UPSTREAM_FILE_MAP: Dict[str, List[str]] = {
    "fips": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
        "Dockerfile*",
        "stolostron/Dockerfile*",
    ],
    "etcd_kms": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
        "pkg/cloud/services/kms/*",
        "pkg/cloud/services/rosa/*",
    ],
    "security_groups": [
        "exp/api/v1beta2/rosamachinepool_types.go",
        "exp/controllers/*",
        "exp/internal/controllers/*",
        "pkg/cloud/services/ec2/*",
        "pkg/cloud/services/securitygroup/*",
    ],
    "external_oidc": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/api/v1beta2/external_auth_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
        "pkg/cloud/services/oidc/*",
    ],
    "no_cni": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
        "pkg/cloud/services/network/*",
    ],
    "private_network": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
        "pkg/cloud/services/network/*",
        "pkg/cloud/services/ec2/*",
    ],
    "additional_tags": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
        "pkg/cloud/tags/*",
    ],
    "domain_prefix": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
    ],
    "channel_group": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
    ],
    "image_registry": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
    ],
    "parallel_upgrade": [
        "exp/api/v1beta2/rosamachinepool_types.go",
        "exp/controllers/*",
        "exp/internal/controllers/*",
    ],
    "disk_size": [
        "exp/api/v1beta2/rosamachinepool_types.go",
        "exp/controllers/*",
        "exp/internal/controllers/*",
    ],
    "availability_zones": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
        "pkg/cloud/services/network/*",
    ],
    "user_agent": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
    ],
    "default_autoscaling": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
    ],
    "cluster_autoscaler_expander": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
    ],
    "audit_logging": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
        "pkg/cloud/services/cloudwatch/*",
    ],
}

UPSTREAM_SHARED_PATTERNS: List[str] = [
    "controlplane/rosa/api/v1beta2/rosacontrolplane_webhook.go",
    "exp/internal/webhooks/rosamachinepool_webhook.go",
    "controlplane/rosa/api/v1beta2/defaults.go",
    "pkg/cloud/services/rosa/*",
]

RETENTION = {
    "max_test_runs": 10,
    "max_change_history": 50,
    "max_tracker_history": 200,
}


def redact(text: str) -> str:
    for pattern, replacement in REDACTION_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text


def redact_dict(data: dict) -> dict:
    result = {}
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = redact(value)
        elif isinstance(value, dict):
            result[key] = redact_dict(value)
        elif isinstance(value, list):
            result[key] = [
                redact(v) if isinstance(v, str) else
                redact_dict(v) if isinstance(v, dict) else v
                for v in value
            ]
        else:
            result[key] = value
    return result
