from pathlib import Path
from typing import Optional, List
import yaml

class DetectionConfig:
    def __init__(self, local_since: str = "HEAD~1"):
        self.local_since = local_since

class UpstreamConfig:
    def __init__(self, repo: str = "stolostron/cluster-api-provider-aws", branch: str = "backplane-2.11"):
        self.repo = repo
        self.branch = branch

class AdvisoryConfig:
    def __init__(self, enabled: bool = True, sources: List[str] = None):
        self.enabled = enabled
        self.sources = sources or ["redhat", "github"]

class AutoTestConfig:
    def __init__(self, enabled: bool = False, max_features: int = 5, suite_id: str = "20-rosa-hcp-provision"):
        self.enabled = enabled
        self.max_features = max_features
        self.suite_id = suite_id

class FeatureGuardConfig:
    def __init__(
        self, 
        base_dir: Path, 
        auto_record: bool = True,
        verbose: bool = False,
        enabled: bool = True,
        docs_dir: Optional[Path] = None,
        template_path: Optional[Path] = None,
        detection: Optional[DetectionConfig] = None,
        upstream: Optional[UpstreamConfig] = None,
        advisory: Optional[AdvisoryConfig] = None,
        auto_test: Optional[AutoTestConfig] = None
    ):
        self.base_dir = base_dir
        self.auto_record = auto_record
        self.verbose = verbose
        self.enabled = enabled
        self.docs_dir = docs_dir or (base_dir / "docs" / "features")
        self.template_path = template_path or (self.docs_dir / "_template.md")
        self.detection = detection or DetectionConfig()
        self.upstream = upstream or UpstreamConfig()
        self.advisory = advisory or AdvisoryConfig()
        self.auto_test = auto_test or AutoTestConfig()
    
    @classmethod
    def default(cls, base_dir: Path = None):
        if base_dir is None:
            base_dir = Path.cwd()
        return cls(base_dir)
    
    @classmethod
    def from_file(cls, path: Path, base_dir: Path):
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            data = {}
        
        detection_data = data.get("detection", {})
        upstream_data = data.get("upstream", {})
        advisory_data = data.get("advisory", {})
        auto_test_data = data.get("auto_test", {})
        
        return cls(
            base_dir=base_dir,
            auto_record=data.get("auto_record", True),
            verbose=data.get("verbose", False),
            detection=DetectionConfig(
                local_since=detection_data.get("local_since", "HEAD~1")
            ),
            upstream=UpstreamConfig(
                repo=upstream_data.get("repo", "stolostron/cluster-api-provider-aws"),
                branch=upstream_data.get("branch", "backplane-2.11")
            ),
            advisory=AdvisoryConfig(
                enabled=advisory_data.get("enabled", True),
                sources=advisory_data.get("sources", ["redhat", "github"])
            ),
            auto_test=AutoTestConfig(
                enabled=auto_test_data.get("enabled", False),
                max_features=auto_test_data.get("max_features", 5),
                suite_id=auto_test_data.get("suite_id", "20-rosa-hcp-provision")
            )
        )
    
    @classmethod
    def load(cls, base_dir: Path):
        settings_path = cls.settings_path(base_dir)
        if settings_path.exists():
            return cls.from_file(settings_path, base_dir)
        else:
            return cls.default(base_dir)
    
    @staticmethod
    def settings_path(base_dir: Path) -> Path:
        return base_dir / "agents" / "knowledge_base" / "feature_guard_settings.yml"
    
    def __repr__(self):
        return f"FeatureGuardConfig(base_dir={self.base_dir}, verbose={self.verbose}, enabled={self.enabled})"