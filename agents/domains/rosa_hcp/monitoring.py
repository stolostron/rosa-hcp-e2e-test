"""
ROSA HCP Monitoring Agent
=========================

Domain-specific monitoring hooks for ROSA HCP test automation.
"""

from pathlib import Path
from typing import Dict, Optional

from ...monitoring_agent import MonitoringAgent


class RosaHcpMonitoringAgent(MonitoringAgent):
    """MonitoringAgent with ROSA HCP-specific resource detection and stale-issue filtering."""

    def __init__(self, base_dir: Path, enabled: bool = True, verbose: bool = False, kb_dir: Path = None):
        if kb_dir is None:
            kb_dir = Path(__file__).parent / "knowledge_base"
        super().__init__(base_dir, enabled, verbose, kb_dir=kb_dir)

    def _should_skip_stale_issue(self, issue_type: str, issue: Dict) -> bool:
        ctx_resource_type = self._structured_context.get("resource_type")
        if ctx_resource_type and "_stuck_deletion" in issue_type:
            expected_prefix = f"{ctx_resource_type}_stuck_deletion"
            if issue_type != expected_prefix:
                self.log(
                    f"Skipping stale issue {issue_type} — structured context says resource_type={ctx_resource_type}",
                    "debug",
                )
                return True
        return False

    def _extract_waiting_for_resource(self, line: str) -> Optional[str]:
        if "ROSANetwork" in line:
            return "ROSANetwork"
        elif "ROSAControlPlane" in line:
            return "ROSAControlPlane"
        elif "ROSARoleConfig" in line:
            return "ROSARoleConfig"
        return None
