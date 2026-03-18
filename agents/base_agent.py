"""
Base AI Agent Class
===================

Foundation for all AI agents in the self-healing test framework.

Provides:
    - Logging and event tracking
    - Pattern matching infrastructure
    - Intervention history

Author: Tina Fitzgerald
Created: March 3, 2026
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


class BaseAgent:
    """Base class for all AI agents with core functionality."""

    def __init__(self, name: str, base_dir: Path, enabled: bool = True, verbose: bool = False):
        self.name = name
        self.base_dir = base_dir
        self.enabled = enabled
        self.verbose = verbose

        # Setup logging
        self.logger = logging.getLogger(f"agent.{name}")
        self.logger.setLevel(logging.DEBUG if verbose else logging.INFO)

        # Agent state
        self.interventions: List[Dict] = []
        self.patterns_detected: List[Dict] = []
        self.current_context: Dict = {}

        # Knowledge base directory
        self.kb_dir = base_dir / "agents" / "knowledge_base"
        self.kb_dir.mkdir(parents=True, exist_ok=True)

        # Lazy-loaded knowledge base cache
        self._known_issues: Optional[Dict] = None

        self.log(f"{name} agent initialized (enabled={enabled})")

    @property
    def known_issues(self) -> Dict:
        """Lazy-load known issues only when needed (used by MonitoringAgent)."""
        if self._known_issues is None:
            self._known_issues = self._load_knowledge("known_issues.json")
        return self._known_issues

    def log(self, message: str, level: str = "info"):
        """Log a message with the agent's context."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = f"[{timestamp}] [{self.name}]"

        if level == "debug" and self.verbose:
            self.logger.debug(f"{prefix} {message}")
            print(f"\033[90m{prefix} {message}\033[0m")  # Gray
        elif level == "info":
            self.logger.info(f"{prefix} {message}")
            if self.verbose:
                print(f"\033[96m{prefix} {message}\033[0m")  # Cyan
        elif level == "warning":
            self.logger.warning(f"{prefix} {message}")
            print(f"\033[93m{prefix} {message}\033[0m")  # Yellow
        elif level == "error":
            self.logger.error(f"{prefix} {message}")
            print(f"\033[91m{prefix} {message}\033[0m")  # Red
        elif level == "success":
            self.logger.info(f"{prefix} {message}")
            print(f"\033[92m{prefix} {message}\033[0m")  # Green

    def _load_knowledge(self, filename: str) -> Dict:
        """Load knowledge base JSON file."""
        kb_file = self.kb_dir / filename
        if kb_file.exists():
            try:
                with open(kb_file, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                self.log(f"Failed to load {filename}: {e}", "error")
                return {}
        return {}

    def match_pattern(self, text: str, patterns: List[Dict]) -> Optional[Dict]:
        """Match text against known patterns."""
        for pattern_def in patterns:
            pattern = pattern_def.get("pattern", "")
            if re.search(pattern, text, re.IGNORECASE):
                self.log(f"Pattern matched: {pattern_def.get('type', 'unknown')}", "debug")
                return pattern_def
        return None

    def record_intervention(self, intervention_type: str, details: Dict):
        """Record an intervention for auditing."""
        self.interventions.append({
            "timestamp": datetime.now().isoformat(),
            "type": intervention_type,
            "agent": self.name,
            "details": details,
        })

    def update_context(self, key: str, value):
        """Update the current execution context."""
        self.current_context[key] = value
        self.log(f"Context updated: {key} = {value}", "debug")

    def get_context(self, key: str, default=None):
        """Get value from current execution context."""
        return self.current_context.get(key, default)

    def should_intervene(self, issue: Dict) -> bool:
        """Determine if agent should intervene based on issue auto_fix flag."""
        return self.enabled and issue.get("auto_fix", False)
