"""
AI Agent Framework for ROSA HCP Test Automation
=================================================

Self-healing test execution with intelligent monitoring and auto-remediation.

Components:
    - BaseAgent: Core agent functionality
    - MonitoringAgent: Real-time output monitoring
    - DiagnosticAgent: Error pattern analysis
    - RemediationAgent: Autonomous fix execution
    - LearningAgent: Outcome tracking and confidence adjustment

Author: Tina Fitzgerald
Created: March 3, 2026
"""

from .base_agent import BaseAgent
from .monitoring_agent import MonitoringAgent, IssueState
from .diagnostic_agent import DiagnosticAgent
from .remediation_agent import RemediationAgent
from .learning_agent import LearningAgent

__all__ = [
    'BaseAgent',
    'MonitoringAgent',
    'DiagnosticAgent',
    'RemediationAgent',
    'LearningAgent',
    'IssueState',
]

__version__ = '0.2.0'
