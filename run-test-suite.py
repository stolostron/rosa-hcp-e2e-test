#!/usr/bin/env python3
"""
CAPA Test Suite Runner
======================

Standalone CLI test runner for CAPA (Cluster API Provider AWS) automation framework.
Executes test suites defined in JSON format without requiring the web UI.

Usage:
    ./run-test-suite.py 02-basic-rosa-hcp-cluster-creation
    ./run-test-suite.py 10-configure-mce-environment -e name_prefix=xyz
    ./run-test-suite.py 10-configure-mce-environment --dry-run
    ./run-test-suite.py 10-configure-mce-environment -vv  # Verbose output
    ./run-test-suite.py --all
    ./run-test-suite.py --tag rosa-hcp
    ./run-test-suite.py --list
    ./run-test-suite.py --help

Features:
    - Sequential and parallel test execution
    - Real-time progress output
    - JSON and HTML report generation
    - Exit codes for CI/CD integration
    - Tag-based filtering
    - Results history with timestamps

Author: Tina Fitzgerald
Created: January 22, 2026
"""

import argparse
import fcntl
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

# Per-feature verification results. The playbook writes this at a fixed path
# (it has no view of the runner's dated output layout); the runner reads it to
# expand JUnit testcases and archives a dated copy alongside the other reports.
FEATURE_VERIFICATION_FILE = "feature-verification.json"
FEATURE_VERIFICATION_PLAYBOOK = "verify_feature_flags.yml"

# AI Agent Framework (optional - only imported if --ai-agent flag is used)
try:
    from agents import MonitoringAgent, DiagnosticAgent, RemediationAgent, LearningAgent
    AI_AGENTS_AVAILABLE = True
except ImportError:
    AI_AGENTS_AVAILABLE = False

# Terminal colors for output
class _BlockingStream:
    """Wrap a stream to reset O_NONBLOCK on BlockingIOError.

    On macOS, the AI agent's sidecar thread can set O_NONBLOCK on stdout,
    causing any print() to raise BlockingIOError ([Errno 35]). Wrapping
    sys.stdout with this class makes every write auto-recover.
    """

    def __init__(self, stream):
        self._stream = stream

    def write(self, data):
        try:
            return self._stream.write(data)
        except BlockingIOError:
            fcntl.fcntl(self._stream, fcntl.F_SETFL,
                        fcntl.fcntl(self._stream, fcntl.F_GETFL) & ~os.O_NONBLOCK)
            return self._stream.write(data)

    def flush(self):
        try:
            return self._stream.flush()
        except BlockingIOError:
            fcntl.fcntl(self._stream, fcntl.F_SETFL,
                        fcntl.fcntl(self._stream, fcntl.F_GETFL) & ~os.O_NONBLOCK)
            return self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


class TestSuiteRunner:
    """Main test suite runner class."""

    def __init__(self, base_dir: Path = Path.cwd(), extra_vars: Optional[Dict[str, str]] = None, dry_run: bool = False, verbosity: int = 0, ai_agent_enabled: bool = False, ai_agent_dry_run: bool = False):
        self.base_dir = base_dir
        self.test_suites_dir = base_dir / "test-suites"
        self.results_dir = base_dir / "test-results"

        # Set AUTOMATION_PATH automatically (can be overridden by extra_vars)
        self.extra_vars = {"AUTOMATION_PATH": str(base_dir.absolute())}
        if extra_vars:
            self.extra_vars.update(extra_vars)

        self.dry_run = dry_run
        self.verbosity = verbosity
        self.suite_label = None  # For generating descriptive filenames
        # Used to tell this run's feature-verification artifact from a stale one.
        self._started_at = time.time()
        # Ansible output preserved as <system-out> when a suite's testcases were
        # expanded per feature and the playbook-level log would otherwise be lost.
        self._suite_output: Dict[str, str] = {}
        # save_results() runs once per --format (3x under the default "all");
        # the artifact archive must happen once per run, not once per format.
        self._artifact_archived = False
        # Counts from the last JUnit build, so the console line and the XML are
        # one derivation rather than two that can drift.
        self._last_junit_counts: Optional[Dict[str, int]] = None
        self.results = {
            "start_time": None,
            "end_time": None,
            "duration": 0,
            "total_tests": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "suites": [],
            "ai_agent_statistics": None
        }

        # Create results directory if it doesn't exist
        self.results_dir.mkdir(exist_ok=True)

        # Initialize AI agents if enabled
        self.ai_agent_enabled = ai_agent_enabled
        self.monitor_agent = None
        self.diagnostic_agent = None
        self.remediation_agent = None
        self.learning_agent = None
        self._agent_lock = threading.Lock()  # Guards process_line from concurrent sidecar + stdout calls

        if self.ai_agent_enabled:
            if not AI_AGENTS_AVAILABLE:
                print(f"{Colors.YELLOW}Warning: AI agents requested but not available - install agents/ module{Colors.ENDC}")
                self.ai_agent_enabled = False
            else:
                print(f"{Colors.CYAN}Initializing AI Agent Framework...{Colors.ENDC}")

                self.monitor_agent = MonitoringAgent(base_dir, enabled=True, verbose=(verbosity > 0))
                self.diagnostic_agent = DiagnosticAgent(base_dir, enabled=True, verbose=(verbosity > 0))
                self.remediation_agent = RemediationAgent(base_dir, enabled=True, verbose=(verbosity > 0), dry_run=ai_agent_dry_run)
                self.learning_agent = LearningAgent(base_dir, enabled=True, verbose=(verbosity > 0))

                self.monitor_agent.set_issue_callback(self._ai_agent_issue_detected)

                mode_text = "DRY RUN MODE" if ai_agent_dry_run else "LIVE MODE"
                print(f"{Colors.GREEN}AI Agent Framework initialized ({mode_text}){Colors.ENDC}")
                print(f"{Colors.CYAN}  - Monitoring Agent: Real-time issue detection{Colors.ENDC}")
                print(f"{Colors.CYAN}  - Diagnostic Agent: Root cause analysis{Colors.ENDC}")
                print(f"{Colors.CYAN}  - Remediation Agent: Autonomous fixes{Colors.ENDC}")
                print(f"{Colors.CYAN}  - Learning Agent: Outcome tracking & confidence adjustment{Colors.ENDC}\n")

    def _ai_agent_issue_detected(self, issue_type: str, context: Dict, issue: Dict):
        """
        AI Agent callback - called when monitoring agent detects an issue.
        Orchestrates the diagnostic and remediation chain.
        """
        resource_key = context.get("resource_key")

        try:
            print(f"\n{Colors.YELLOW}AI Agent detected issue: {issue_type}{Colors.ENDC}")

            diagnosis = self.diagnostic_agent.diagnose(issue_type, context)

            if diagnosis:
                print(f"{Colors.CYAN}   Root cause: {diagnosis.get('root_cause', 'Unknown')}{Colors.ENDC}")
                print(f"{Colors.CYAN}   Recommended fix: {diagnosis.get('recommended_fix', 'None')}{Colors.ENDC}")

                if diagnosis.get('confidence', 0) >= 0.7:
                    success, message = self.remediation_agent.remediate(diagnosis)

                    # Record outcome for learning agent
                    if self.learning_agent:
                        self.learning_agent.record_outcome(
                            issue_type=issue_type,
                            diagnosis=diagnosis,
                            fix_applied=diagnosis.get("recommended_fix", ""),
                            success=success,
                            resource_key=resource_key or "",
                            details=message,
                        )

                    if success:
                        print(f"{Colors.GREEN}   Fix applied: {message}{Colors.ENDC}\n")
                        self.monitor_agent.mark_issue_resolved(issue_type, resource_key)
                    else:
                        print(f"{Colors.YELLOW}   Fix result: {message}{Colors.ENDC}\n")
                        self.monitor_agent.mark_issue_failed(issue_type, resource_key)
                else:
                    print(f"{Colors.YELLOW}   Confidence too low for auto-remediation{Colors.ENDC}\n")
                    self.monitor_agent.mark_issue_failed(issue_type, resource_key)
            else:
                print(f"{Colors.YELLOW}   Unable to diagnose issue{Colors.ENDC}\n")
                self.monitor_agent.mark_issue_failed(issue_type, resource_key)

        except Exception as e:
            print(f"{Colors.YELLOW}   AI Agent error: {str(e)}{Colors.ENDC}\n")
            self.monitor_agent.mark_issue_failed(issue_type, resource_key)

    def load_test_suite(self, suite_id: str) -> Optional[Dict]:
        """Load test suite JSON from file."""
        suite_file = self.test_suites_dir / f"{suite_id}.json"

        if not suite_file.exists():
            print(f"{Colors.RED}✗ Test suite not found: {suite_id}{Colors.ENDC}")
            return None

        try:
            with open(suite_file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            print(f"{Colors.RED}✗ Invalid JSON in {suite_id}: {e}{Colors.ENDC}")
            return None

    def list_test_suites(self) -> List[Dict]:
        """List all available test suites."""
        suites = []
        for suite_file in sorted(self.test_suites_dir.glob("*.json")):
            suite_id = suite_file.stem
            suite_data = self.load_test_suite(suite_id)
            if suite_data:
                suites.append({
                    "id": suite_id,
                    "name": suite_data.get("name", "Unknown"),
                    "description": suite_data.get("description", ""),
                    "tags": suite_data.get("tags", []),
                    "playbook_count": len(suite_data.get("playbooks", []))
                })
        return suites

    def run_playbook(self, playbook: Dict, suite_name: str) -> Dict:
        """Execute a single Ansible playbook."""
        playbook_name = playbook.get("name")
        playbook_file = playbook.get("file", playbook_name)  # Use 'file' field, fallback to 'name'
        playbook_path = self.base_dir / playbook_file

        if not playbook_path.exists():
            return {
                "name": playbook_name,
                "file": playbook_file,
                "success": False,
                "error": f"Playbook not found: {playbook_path}",
                "duration": 0
            }

        # Show dry-run indicator
        if self.dry_run:
            print(f"\n{Colors.YELLOW}🔍 DRY RUN: {playbook.get('description', playbook_name)}{Colors.ENDC}")
        else:
            print(f"\n{Colors.CYAN}⏳ Running: {playbook.get('description', playbook_name)}{Colors.ENDC}")

        start_time = time.time()

        try:
            # Build ansible-playbook command
            cmd = ["ansible-playbook", str(playbook_path)]

            # Add verbosity flags
            if self.verbosity > 0:
                cmd.append("-" + "v" * min(self.verbosity, 4))  # Max -vvvv

            # Merge playbook vars with extra vars (extra vars take precedence)
            all_vars = {}
            if "extra_vars" in playbook:
                all_vars.update(playbook["extra_vars"])
            all_vars.update(self.extra_vars)  # Command-line overrides JSON

            # Add dry_run variable for playbooks to use
            if self.dry_run:
                all_vars["dry_run"] = "true"

            # Add merged variables to command
            # Complex types (dicts/lists) are passed as a JSON blob so ansible
            # parses them correctly; simple types use key=value form.
            complex_vars = {}
            for key, value in all_vars.items():
                val_str = str(value)
                if val_str.startswith('{') or val_str.startswith('['):
                    try:
                        complex_vars[key] = json.loads(val_str)
                    except json.JSONDecodeError:
                        cmd.extend(["-e", f"{key}={value}"])
                else:
                    cmd.extend(["-e", f"{key}={value}"])
            if complex_vars:
                cmd.extend(["-e", json.dumps(complex_vars)])

            # Set timeout if specified
            timeout = playbook.get("timeout", None)

            # Execute playbook with real-time output streaming
            # This prevents Jenkins timeout issues on long-running operations
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Merge stderr into stdout
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,  # Line buffered
                cwd=self.base_dir
            )

            # Start sidecar log file tailer for real-time agent monitoring.
            # Ansible shell wait loops buffer stdout, but they also write to a
            # sidecar log file via tee. This thread tails that file and feeds
            # lines to the agent immediately (same pattern as ui/backend/app.py).
            sidecar_stop = threading.Event()
            sidecar_thread = None

            if self.ai_agent_enabled and self.monitor_agent and "delete" in playbook_name.lower():
                cluster_name = self.extra_vars.get("cluster_name", "")
                if not cluster_name:
                    # Derive from name_prefix (same as Ansible: name_prefix + "-rosa-hcp")
                    name_prefix = self.extra_vars.get("name_prefix", "")
                    if name_prefix:
                        cluster_name = f"{name_prefix}-rosa-hcp"
                if cluster_name:
                    sidecar_logfile = f"/tmp/deletion-agent-{cluster_name}.log"

                    def _tail_sidecar():
                        """Tail the sidecar log file and feed lines to the AI agent in real-time."""
                        last_pos = 0
                        while not sidecar_stop.is_set():
                            try:
                                if os.path.exists(sidecar_logfile):
                                    with open(sidecar_logfile, 'r') as f:
                                        f.seek(last_pos)
                                        new_lines = f.readlines()
                                        if new_lines:
                                            for line in new_lines:
                                                line = line.strip()
                                                if line:
                                                    try:
                                                        with self._agent_lock:
                                                            self.monitor_agent.process_line(line)
                                                    except Exception:
                                                        pass
                                        last_pos = f.tell()
                            except Exception:
                                pass
                            sidecar_stop.wait(2)  # Poll every 2 seconds
                    sidecar_thread = threading.Thread(target=_tail_sidecar, daemon=True)
                    sidecar_thread.start()
                    if self.verbosity > 0:
                        print(f"{Colors.CYAN}AI Agent sidecar monitoring: {sidecar_logfile}{Colors.ENDC}")

            # Capture output while streaming it in real-time
            output_lines = []
            try:
                for line in process.stdout:
                    # Print immediately (prevents timeout detection in CI/CD)
                    print(line, end='')
                    sys.stdout.flush()
                    # Also store for later use
                    output_lines.append(line)

                    # AI Agent Hook: Process line in real-time for issue detection
                    if self.ai_agent_enabled and self.monitor_agent:
                        try:
                            with self._agent_lock:
                                self.monitor_agent.process_line(line)
                        except Exception as e:
                            if self.verbosity > 0:
                                print(f"{Colors.YELLOW}AI Agent Warning: {str(e)}{Colors.ENDC}")

                # Wait for process to complete
                returncode = process.wait(timeout=timeout)

            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise  # Re-raise to be caught by outer exception handler
            finally:
                # Stop the sidecar tailer thread
                sidecar_stop.set()
                if sidecar_thread is not None:
                    sidecar_thread.join(timeout=5)

            duration = time.time() - start_time
            output = ''.join(output_lines)

            if returncode == 0:
                print(f"{Colors.GREEN}✓ Completed successfully ({self._format_duration(duration)}){Colors.ENDC}")

                return {
                    "name": playbook_name,
                    "file": playbook_file,
                    "description": playbook.get("description", ""),
                    "test_case_id": playbook.get("test_case_id", ""),
                    "success": True,
                    "duration": duration,
                    "output": output
                }
            else:
                print(f"{Colors.RED}✗ Failed with exit code {returncode}{Colors.ENDC}")

                return {
                    "name": playbook_name,
                    "file": playbook_file,
                    "description": playbook.get("description", ""),
                    "test_case_id": playbook.get("test_case_id", ""),
                    "success": False,
                    "error": output,
                    "duration": duration,
                    "output": output
                }

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            print(f"{Colors.RED}✗ Timeout after {self._format_duration(duration)}{Colors.ENDC}")
            return {
                "name": playbook_name,
                "file": playbook_file,
                "description": playbook.get("description", ""),
                "test_case_id": playbook.get("test_case_id", ""),
                "success": False,
                "is_error": True,
                "error": f"Timeout after {timeout} seconds",
                "duration": duration
            }
        except Exception as e:
            duration = time.time() - start_time
            print(f"{Colors.RED}✗ Error: {str(e)}{Colors.ENDC}")
            return {
                "name": playbook_name,
                "file": playbook_file,
                "description": playbook.get("description", ""),
                "test_case_id": playbook.get("test_case_id", ""),
                "success": False,
                "is_error": True,
                "error": str(e),
                "duration": duration
            }

    def _extract_suite_label(self, suite_id: str) -> str:
        """Extract a short descriptive label from suite ID for filenames.

        Examples:
            10-configure-mce-environment -> configure
            20-rosa-hcp-provision -> provision
            30-rosa-hcp-delete -> delete
            23-rosa-hcp-full-lifecycle -> lifecycle
        """
        # Remove leading numbers and hyphens
        label = suite_id.lstrip('0123456789-')

        # Extract key terms for common patterns
        if 'configure' in label:
            return 'configure'
        elif 'provision' in label or 'creation' in label:
            return 'provision'
        elif 'delete' in label or 'deletion' in label:
            return 'delete'
        elif 'lifecycle' in label:
            return 'lifecycle'
        elif 'verify' in label:
            return 'verify'
        elif 'enable' in label or 'disable' in label:
            return 'toggle'
        else:
            # Fallback: use first significant word
            words = label.replace('-', ' ').split()
            return words[0] if words else 'test'

    def run_test_suite(self, suite_id: str) -> bool:
        """Execute a complete test suite."""
        suite_data = self.load_test_suite(suite_id)
        if not suite_data:
            return False

        # Set suite label for filename generation
        self.suite_label = self._extract_suite_label(suite_id)

        # Print suite header
        self._print_suite_header(suite_data)

        suite_start = time.time()
        suite_results = {
            "id": suite_id,
            "name": suite_data.get("name", "Unknown"),
            "start_time": datetime.now().isoformat(),
            "playbooks": []
        }

        # Execute playbooks
        playbooks = suite_data.get("playbooks", [])
        total_playbooks = len(playbooks)

        for idx, playbook in enumerate(playbooks, 1):
            print(f"\n{Colors.BOLD}[{idx}/{total_playbooks}]{Colors.ENDC} ", end="")

            playbook_result = self.run_playbook(playbook, suite_data.get("name"))
            suite_results["playbooks"].append(playbook_result)

            # Update counts
            if playbook_result["success"]:
                self.results["passed"] += 1
            else:
                self.results["failed"] += 1

                # Stop on failure if configured
                if suite_data.get("stopOnFailure", False) and playbook.get("required", True):
                    print(f"\n{Colors.YELLOW}⚠ Stopping suite due to failure{Colors.ENDC}")
                    break

        # Calculate suite duration
        suite_duration = time.time() - suite_start
        suite_results["end_time"] = datetime.now().isoformat()
        suite_results["duration"] = suite_duration

        # Print suite summary
        self._print_suite_summary(suite_results)

        # Add to overall results
        self.results["suites"].append(suite_results)
        self.results["total_tests"] = len(playbooks)

        return self.results["failed"] == 0

    def run_scenario(self, scenario: Dict) -> bool:
        """Execute a scenario's stages in order.

        Stages marked `always` (cleanup/restore) still run after a failure, so a
        failed provision does not leak an AWS cluster or leave the hub with
        HyperShift disabled.
        """
        self.suite_label = f"scenario-{scenario['name']}"

        stages = scenario["stages"]
        print(f"\n{Colors.BOLD}{'=' * 70}{Colors.ENDC}")
        print(f"{Colors.BOLD}Scenario: {scenario['name']}{Colors.ENDC}")
        print(f"  {scenario['description']}")
        if scenario.get("version"):
            print(f"  OpenShift version: {scenario['version']}")
        print(f"  Features: {', '.join(scenario['features'])}")
        print(f"  Stages:   {' → '.join(s['suite'] for s in stages)}")
        if scenario.get("estimated_minutes"):
            print(f"  Estimated runtime: ~{scenario['estimated_minutes']} minutes")
        print(f"{Colors.BOLD}{'=' * 70}{Colors.ENDC}")

        all_passed = True
        for stage in stages:
            suite_id = stage["suite"]

            if not all_passed and not stage["always"]:
                print(f"\n{Colors.YELLOW}⊘ Skipping {suite_id} (earlier stage failed){Colors.ENDC}")
                continue

            if not all_passed and stage["always"]:
                print(f"\n{Colors.YELLOW}↻ Running {suite_id} anyway (cleanup stage){Colors.ENDC}")

            # run_test_suite() returns a cumulative pass flag, so compare the
            # failure count before and after to see if *this* stage failed.
            failures_before = self.results["failed"]
            saved_label = self.suite_label
            self.run_test_suite(suite_id)
            self.suite_label = saved_label

            if self.results["failed"] > failures_before:
                all_passed = False

        return all_passed

    def run_all_suites(self, tag_filter: Optional[str] = None) -> bool:
        """Run all test suites, optionally filtered by tag."""
        suites = self.list_test_suites()

        # Set suite label for filename generation
        if tag_filter:
            self.suite_label = f"tag-{tag_filter}"
        else:
            self.suite_label = "multi"

        # Apply tag filter if specified
        if tag_filter:
            suites = [s for s in suites if tag_filter in s.get("tags", [])]
            print(f"{Colors.CYAN}Running test suites with tag '{tag_filter}'{Colors.ENDC}\n")

        if not suites:
            print(f"{Colors.YELLOW}No test suites found{Colors.ENDC}")
            return False

        print(f"{Colors.BOLD}Found {len(suites)} test suite(s){Colors.ENDC}\n")

        # Run each suite (note: suite_label remains as set above for all suites)
        all_passed = True
        for suite in suites:
            # Temporarily save the multi/tag label
            saved_label = self.suite_label
            success = self.run_test_suite(suite["id"])
            # Restore the multi/tag label for filename generation
            self.suite_label = saved_label
            if not success:
                all_passed = False

        return all_passed

    def save_results(self, format: str = "json") -> Path:
        """Save test results to file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_date_dir = self.results_dir / datetime.now().strftime("%Y-%m-%d")
        results_date_dir.mkdir(exist_ok=True)

        # Generate filename with suite label for better identification
        # Examples: test-run-provision-20260208_145017.xml
        #           test-run-delete-20260208_150612.xml
        #           test-run-configure-20260208_151015.xml
        label_part = f"-{self.suite_label}" if self.suite_label else ""

        if format == "json":
            output_file = results_date_dir / f"test-run{label_part}-{timestamp}.json"
            with open(output_file, 'w') as f:
                json.dump(self.results, f, indent=2)

            # Also save as latest.json (with label)
            latest_file = self.results_dir / f"latest{label_part}.json"
            with open(latest_file, 'w') as f:
                json.dump(self.results, f, indent=2)

        elif format == "html":
            output_file = results_date_dir / f"test-run{label_part}-{timestamp}.html"
            html_content = self._generate_html_report()
            with open(output_file, 'w') as f:
                f.write(html_content)

            # Also save as latest.html (with label)
            latest_file = self.results_dir / f"latest{label_part}.html"
            with open(latest_file, 'w') as f:
                f.write(html_content)

        elif format == "junit":
            output_file = results_date_dir / f"test-run{label_part}-{timestamp}.xml"
            junit_content = self._generate_junit_xml()
            with open(output_file, 'w') as f:
                f.write(junit_content)

            # Also save as latest.xml (with label)
            latest_file = self.results_dir / f"latest{label_part}.xml"
            with open(latest_file, 'w') as f:
                f.write(junit_content)

        # Archive this run's per-feature results next to the report, in any
        # format. The fixed-path copy is overwritten by the next run; the dated
        # copy is what makes run-over-run comparison possible later.
        if not self._artifact_archived:
            feature_data = self.load_feature_verification()
            if feature_data:
                archived = results_date_dir / f"feature-verification{label_part}-{timestamp}.json"
                with open(archived, 'w') as f:
                    json.dump(feature_data, f, indent=2)
                self._artifact_archived = True

        return output_file

    def _extract_environment_info(self, playbook_output: str) -> dict:
        """Extract environment information from playbook output."""
        import re

        env_info = {}

        # Extract OCP login info
        ocp_login_match = re.search(r'Successfully logged in - User: ([\w:]+) \| API: (https://[^\s]+) \| Context: ([^\s]+)', playbook_output)
        if ocp_login_match:
            env_info['ocp_user'] = ocp_login_match.group(1)
            env_info['ocp_api_url'] = ocp_login_match.group(2)
            env_info['ocp_context'] = ocp_login_match.group(3)

        # Extract CAPI controller info
        capi_match = re.search(r'CAPI controller deployed - ({[^}]+})', playbook_output)
        if capi_match:
            env_info['capi_controller'] = capi_match.group(1)

        # Extract CAPA controller info
        capa_match = re.search(r'CAPA controller deployed - ({[^}]+})', playbook_output)
        if capa_match:
            env_info['capa_controller'] = capa_match.group(1)

        # Check for RosaNetwork resources
        if 'RosaNetwork resources found' in playbook_output or 'No RosaNetwork resources found' in playbook_output:
            if 'No RosaNetwork resources found' in playbook_output:
                env_info['rosa_network'] = 'none'
            else:
                env_info['rosa_network'] = 'available'

        # Check for RosaRoleConfig (note: might be ROSARoleConfig in some outputs)
        if 'rosa-creds-secret found' in playbook_output:
            env_info['rosa_role_config'] = 'available'
        elif 'rosa-creds-secret not found' in playbook_output:
            env_info['rosa_role_config'] = 'none'

        return env_info

    def _generate_html_report(self) -> str:
        """Generate HTML test report."""
        passed_pct = (self.results["passed"] / max(self.results["total_tests"], 1)) * 100

        # Extract environment info from first successful playbook
        env_info = {}
        for suite in self.results.get("suites", []):
            for playbook in suite.get("playbooks", []):
                if playbook.get("success") and playbook.get("output"):
                    env_info = self._extract_environment_info(playbook["output"])
                    if env_info:
                        break
            if env_info:
                break

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>ROSA HCP Test Results - {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }}
        .env-info {{ background: #e3f2fd; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #2196F3; }}
        .env-info h2 {{ margin-top: 0; color: #1976D2; font-size: 18px; }}
        .env-item {{ margin: 8px 0; }}
        .env-label {{ font-weight: bold; color: #555; }}
        .env-value {{ color: #333; font-family: monospace; background: white; padding: 2px 6px; border-radius: 3px; }}
        .summary {{ display: flex; gap: 20px; margin: 20px 0; }}
        .stat-box {{ flex: 1; padding: 20px; border-radius: 8px; text-align: center; }}
        .stat-box.total {{ background: #2196F3; color: white; }}
        .stat-box.passed {{ background: #4CAF50; color: white; }}
        .stat-box.failed {{ background: #f44336; color: white; }}
        .stat-number {{ font-size: 36px; font-weight: bold; }}
        .stat-label {{ font-size: 14px; margin-top: 5px; }}
        .suite {{ margin: 20px 0; padding: 20px; border: 1px solid #ddd; border-radius: 8px; }}
        .suite-header {{ font-size: 20px; font-weight: bold; margin-bottom: 10px; }}
        .playbook {{ margin: 10px 0; padding: 15px; background: #f9f9f9; border-left: 4px solid #ddd; }}
        .playbook.success {{ border-left-color: #4CAF50; }}
        .playbook.failed {{ border-left-color: #f44336; }}
        .playbook-name {{ font-weight: bold; }}
        .playbook-duration {{ color: #666; font-size: 12px; }}
        .error {{ color: #f44336; margin-top: 10px; padding: 10px; background: #ffebee; border-radius: 4px; }}
        .progress-bar {{ width: 100%; height: 30px; background: #e0e0e0; border-radius: 15px; overflow: hidden; margin: 20px 0; }}
        .progress-fill {{ height: 100%; background: linear-gradient(90deg, #4CAF50, #8BC34A); display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>ROSA HCP Test Results</h1>
"""

        # Add environment info section if available
        if env_info:
            html += """
        <div class="env-info">
            <h2>🔧 Environment Information</h2>
"""
            if 'ocp_api_url' in env_info:
                html += f"""
            <div class="env-item">
                <span class="env-label">OpenShift API:</span>
                <span class="env-value">{env_info['ocp_api_url']}</span>
            </div>
"""
            if 'ocp_user' in env_info:
                html += f"""
            <div class="env-item">
                <span class="env-label">User:</span>
                <span class="env-value">{env_info['ocp_user']}</span>
            </div>
"""
            if 'ocp_context' in env_info:
                html += f"""
            <div class="env-item">
                <span class="env-label">Context:</span>
                <span class="env-value">{env_info['ocp_context']}</span>
            </div>
"""
            if 'capi_controller' in env_info:
                html += f"""
            <div class="env-item">
                <span class="env-label">CAPI Controller:</span>
                <span class="env-value">✓ Deployed</span>
            </div>
"""
            if 'capa_controller' in env_info:
                html += f"""
            <div class="env-item">
                <span class="env-label">CAPA Controller:</span>
                <span class="env-value">✓ Deployed</span>
            </div>
"""
            if 'rosa_network' in env_info:
                if env_info['rosa_network'] == 'available':
                    html += """
            <div class="env-item">
                <span class="env-label">ROSANetwork CRD:</span>
                <span class="env-value">✓ Available (MCE Enhancement)</span>
            </div>
"""
                else:
                    html += """
            <div class="env-item">
                <span class="env-label">ROSANetwork CRD:</span>
                <span class="env-value">ℹ Not yet available</span>
            </div>
"""
            if 'rosa_role_config' in env_info:
                if env_info['rosa_role_config'] == 'available':
                    html += """
            <div class="env-item">
                <span class="env-label">ROSARoleConfig:</span>
                <span class="env-value">✓ Available (MCE Enhancement)</span>
            </div>
"""
                else:
                    html += """
            <div class="env-item">
                <span class="env-label">ROSARoleConfig:</span>
                <span class="env-value">ℹ Not yet available</span>
            </div>
"""
            html += """
        </div>
"""

        html += f"""
        <div class="summary">
            <div class="stat-box total">
                <div class="stat-number">{self.results["total_tests"]}</div>
                <div class="stat-label">Total Tests</div>
            </div>
            <div class="stat-box passed">
                <div class="stat-number">{self.results["passed"]}</div>
                <div class="stat-label">Passed</div>
            </div>
            <div class="stat-box failed">
                <div class="stat-number">{self.results["failed"]}</div>
                <div class="stat-label">Failed</div>
            </div>
        </div>

        <div class="progress-bar">
            <div class="progress-fill" style="width: {passed_pct}%">
                {passed_pct:.1f}% Passed
            </div>
        </div>

        <p><strong>Duration:</strong> {self._format_duration(self.results["duration"])}</p>
        <p><strong>Started:</strong> {self.results["start_time"]}</p>
        <p><strong>Completed:</strong> {self.results["end_time"]}</p>

"""

        # Add suite details
        for suite in self.results["suites"]:
            html += f"""
        <div class="suite">
            <div class="suite-header">{suite["name"]}</div>
            <p><strong>Duration:</strong> {self._format_duration(suite["duration"])}</p>
"""

            for playbook in suite["playbooks"]:
                status_class = "success" if playbook["success"] else "failed"
                icon = "✓" if playbook["success"] else "✗"

                html += f"""
            <div class="playbook {status_class}">
                <div class="playbook-name">{icon} {playbook.get("description", playbook["name"])}</div>
                <div class="playbook-duration">Duration: {self._format_duration(playbook["duration"])}</div>
"""

                if not playbook["success"] and "error" in playbook:
                    html += f"""
                <div class="error">
                    <strong>Error:</strong><br>
                    <pre>{playbook["error"]}</pre>
                </div>
"""

                html += "            </div>\n"

            html += "        </div>\n"

        html += """
    </div>
</body>
</html>
"""

        return html

    def load_feature_verification(self) -> Optional[Dict]:
        """Read the per-feature results stage 21 writes, if this run wrote them.

        The artifact lives at a fixed path so the playbook does not need to know
        the runner's dated output layout. That makes a stale file from an
        earlier run possible, so only accept one modified since this run began.
        """
        path = self.results_dir / FEATURE_VERIFICATION_FILE
        try:
            if path.stat().st_mtime < self._started_at:
                return None
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _feature_testcases(self, playbook: Dict, feature_data: Optional[Dict]) -> Optional[List[Dict]]:
        """Expand the feature-verification playbook into one testcase per feature.

        Returns None when expansion does not apply (different playbook, no
        artifact, or an artifact with no features) so the caller falls back to
        the single playbook-level testcase. That fallback matters: if the
        playbook died before writing the artifact — a login failure, a timeout —
        there are no per-feature results to report and the raw error is what the
        reader needs.
        """
        if not feature_data:
            return None
        if not str(playbook.get("file", "")).endswith(FEATURE_VERIFICATION_PLAYBOOK):
            return None
        # Shape-check rather than trust: a malformed artifact must not raise out
        # of report generation and discard an otherwise-complete 75-minute run.
        features = feature_data.get("features")
        if not isinstance(features, list) or not features:
            return None

        cases = []

        # A degraded run verified only the CRD side of every feature. Without a
        # testcase of its own that fact lives in a debug line nobody reads, and
        # the build goes green on half the evidence. Failed under CI (matching
        # the playbook, which also fails there), skipped locally so offline runs
        # stay usable while still showing up in the report.
        env = feature_data.get("environment") or {}
        # `is True`, not truthiness: the playbook templates this field, and a
        # templated scalar only survives as a real bool because ansible-core
        # special-cases "True"/"False". Under jinja2_native it becomes the
        # string "False", which is truthy — every CI build would then grow a
        # spurious ocm_reachability failure on a perfectly healthy run.
        if env.get("degraded") is True:
            reason = str(env.get("degraded_reason")
                         or "Verification ran without OCM; CRD side only").strip()
            cases.append({
                "classname": "FeatureVerification",
                "name": "ocm_reachability",
                "time": 0.0,
                "outcome": "failed" if _in_ci() else "skipped",
                "message": reason,
                "text": reason,
            })

        for index, feat in enumerate(features):
            if not isinstance(feat, dict):
                continue
            status = feat.get("status", "passed")
            detail = feat.get("detail", "")
            if status == "failed":
                outcome = "failed"
                message = detail or "Feature was requested but not found in the cluster spec"
            elif status == "warned":
                # A warn means the installed CRD has no field for this feature —
                # a platform limitation, not our bug. JUnit 'skipped' keeps the
                # build green while still surfacing it per feature, which is
                # exactly the distinction you need on a new OpenShift release.
                outcome = "skipped"
                message = detail or f"CRD has no field '{feat.get('field', '')}' — platform limitation"
            elif status == "passed":
                outcome, message = "passed", ""
            else:
                # Fail closed. An unrecognised status is exactly the case where
                # a green testcase is the wrong answer — the producing playbook
                # and this file are edited independently.
                outcome = "error"
                message = (f"Unrecognised feature status {status!r} in "
                           f"{FEATURE_VERIFICATION_FILE}")

            cases.append({
                # Stable classname so CI can trend one feature across builds.
                "classname": "FeatureVerification",
                "name": str(feat.get("id") or f"feature-{index}"),
                # Per-feature timing is not measured. The real elapsed time stays
                # on the enclosing <testsuite>; splitting it evenly across
                # features would be a fabricated number.
                "time": 0.0,
                "outcome": outcome,
                "message": message,
                "text": message,
            })
        return cases

    def _junit_testcases(self, suite: Dict, feature_data: Optional[Dict]) -> List[Dict]:
        """Normalize one suite's playbooks into JUnit testcase descriptors."""
        cases: List[Dict] = []
        for playbook in suite["playbooks"]:
            expanded = self._feature_testcases(playbook, feature_data)
            if expanded is not None:
                cases.extend(expanded)

                # The expansion replaces the playbook-level testcase, and with
                # it the ansible log that was the only material for diagnosing
                # a failure. Per-feature detail says *which* feature broke; the
                # log says why. Keep both.
                #
                # If the playbook failed but no expanded case did, the failure
                # happened outside the per-feature results entirely — today the
                # artifact is written before both `fail:` tasks, so that means
                # something after the write. Without this the suite would be
                # reported all-green on a non-zero exit.
                if not playbook["success"]:
                    self._suite_output[suite["name"]] = playbook.get("output", "")
                    if not any(c["outcome"] in ("failed", "error") for c in expanded):
                        cases.append({
                            "classname": f"{suite['name']} {playbook['name']}",
                            "name": f"{playbook['name']} (playbook exit)",
                            "time": round(playbook["duration"], 3),
                            "outcome": "error" if playbook.get("is_error") else "failed",
                            "message": playbook.get(
                                "error", "Playbook failed after writing per-feature results"),
                            "text": (f"Playbook: {playbook['name']}\n"
                                     f"Error: {playbook.get('error', 'Unknown error')}\n"
                                     f"\nOutput:\n{playbook.get('output', '')}"),
                        })
                continue

            test_case_id = playbook.get("test_case_id", "")
            description = playbook.get("description", playbook["name"])
            name = f"{test_case_id}: {description}" if test_case_id else description

            # A testcase is an ERROR (infrastructure/timeout) rather than a
            # FAILURE (assertion) when it carries is_error.
            if not playbook["success"]:
                outcome = "error" if playbook.get("is_error") else "failed"
                message = playbook.get("error", "Test failed")
                text = f"Playbook: {playbook['name']}\n"
                text += f"Error: {playbook.get('error', 'Unknown error')}\n"
                if playbook.get("output"):
                    text += f"\nOutput:\n{playbook['output']}"
            elif playbook.get("skipped"):
                outcome, message, text = "skipped", "", ""
            else:
                outcome, message, text = "passed", "", ""

            cases.append({
                "classname": f"{suite['name']} {name}",
                "name": name,
                "time": round(playbook["duration"], 3),
                "outcome": outcome,
                "message": message,
                "text": text,
            })
        return cases

    @property
    def last_junit_counts(self) -> Optional[Dict[str, int]]:
        """Counts from the most recent JUnit build, or None if none ran yet."""
        return self._last_junit_counts

    def _generate_junit_xml(self) -> str:
        """Generate JUnit XML test report for CI/CD integration.

        When stage 21 wrote per-feature results, its single playbook testcase is
        replaced by one testcase per feature. Without that, a feature regression
        shows up in CI only as 'Verify Feature Flags failed' plus a large stdout
        blob, and no single feature can be tracked across builds.
        """
        import xml.etree.ElementTree as ET
        from xml.dom import minidom

        feature_data = self.load_feature_verification()
        self._suite_output = {}

        # Build every suite's testcases first so the counts and the elements are
        # derived from the same list and cannot drift apart.
        suite_cases = [
            (suite, self._junit_testcases(suite, feature_data))
            for suite in self.results.get("suites", [])
        ]
        all_cases = [c for _, cases in suite_cases for c in cases]

        def _tally(cases, outcome):
            return sum(1 for c in cases if c["outcome"] == outcome)

        testsuites = ET.Element('testsuites')
        testsuites.set('name', 'ROSA HCP Test Suite')
        # Derive the test count from the testcases actually reported here, not
        # from self.results['total_tests'] — that counter is overwritten per
        # suite, so on a multi-suite run it would disagree with the totals.
        testsuites.set('tests', str(len(all_cases)))
        testsuites.set('failures', str(_tally(all_cases, 'failed')))
        testsuites.set('errors', str(_tally(all_cases, 'error')))
        testsuites.set('skipped', str(_tally(all_cases, 'skipped')))
        testsuites.set('time', str(round(self.results['duration'], 3)))

        for suite, cases in suite_cases:
            testsuite = ET.SubElement(testsuites, 'testsuite')
            testsuite.set('name', suite['name'])
            testsuite.set('timestamp', suite['start_time'])
            testsuite.set('tests', str(len(cases)))
            testsuite.set('time', str(round(suite['duration'], 3)))
            testsuite.set('failures', str(_tally(cases, 'failed')))
            testsuite.set('errors', str(_tally(cases, 'error')))
            testsuite.set('skipped', str(_tally(cases, 'skipped')))

            for case in cases:
                testcase = ET.SubElement(testsuite, 'testcase')
                testcase.set('name', case['name'])
                testcase.set('classname', case['classname'])
                testcase.set('time', str(case['time']))

                if case['outcome'] in ('failed', 'error'):
                    tag = 'error' if case['outcome'] == 'error' else 'failure'
                    elem = ET.SubElement(testcase, tag)
                    elem.set('type', 'TestError' if tag == 'error' else 'TestFailure')
                    elem.set('message', case['message'] or 'Test failed')
                    elem.text = case['text']
                elif case['outcome'] == 'skipped':
                    skipped = ET.SubElement(testcase, 'skipped')
                    if case['message']:
                        skipped.set('message', case['message'])

            # Attach the ansible log once per suite rather than per feature.
            captured = self._suite_output.get(suite['name'])
            if captured:
                ET.SubElement(testsuite, 'system-out').text = captured

        self._last_junit_counts = {
            "tests": len(all_cases),
            "failures": _tally(all_cases, 'failed'),
            "errors": _tally(all_cases, 'error'),
            "skipped": _tally(all_cases, 'skipped'),
        }

        # Pretty print XML
        xml_str = ET.tostring(testsuites, encoding='unicode')
        dom = minidom.parseString(xml_str)
        return dom.toprettyxml(indent='  ')

    def _print_suite_header(self, suite_data: Dict):
        """Print formatted suite header."""
        print("\n" + "=" * 80)
        print(f"{Colors.BOLD}{Colors.HEADER}CAPA Test Suite Runner{Colors.ENDC}")
        if self.dry_run:
            print(f"{Colors.BOLD}{Colors.YELLOW}🔍 DRY RUN MODE - No changes will be made{Colors.ENDC}")
        print("=" * 80)
        print(f"\n{Colors.BOLD}📋 Test Suite:{Colors.ENDC} {suite_data.get('name', 'Unknown')}")
        print(f"{Colors.BOLD}📝 Description:{Colors.ENDC} {suite_data.get('description', '')}")
        print(f"{Colors.BOLD}🏷️  Tags:{Colors.ENDC} {', '.join(suite_data.get('tags', []))}")
        print(f"{Colors.BOLD}📦 Playbooks:{Colors.ENDC} {len(suite_data.get('playbooks', []))}")
        print(f"{Colors.BOLD}⏰ Started:{Colors.ENDC} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("\n" + "-" * 80)

    def _print_suite_summary(self, suite_results: Dict):
        """Print suite execution summary."""
        passed = sum(1 for p in suite_results["playbooks"] if p["success"])
        failed = sum(1 for p in suite_results["playbooks"] if not p["success"])
        total = len(suite_results["playbooks"])

        print("\n" + "-" * 80)
        print(f"\n{Colors.BOLD}📊 SUITE SUMMARY:{Colors.ENDC}")
        print(f"   Total Playbooks: {total}")
        print(f"   {Colors.GREEN}✓ Passed: {passed}{Colors.ENDC}")
        print(f"   {Colors.RED}✗ Failed: {failed}{Colors.ENDC}")
        print(f"   ⏱️  Duration: {self._format_duration(suite_results['duration'])}")

    def _print_final_summary(self):
        """Print final test execution summary."""
        print("\n" + "=" * 80)
        print(f"\n{Colors.BOLD}📊 FINAL RESULTS SUMMARY:{Colors.ENDC}")
        print(f"   Total Tests: {self.results['total_tests']}")
        print(f"   {Colors.GREEN}✓ Passed: {self.results['passed']}{Colors.ENDC}")
        print(f"   {Colors.RED}✗ Failed: {self.results['failed']}{Colors.ENDC}")
        print(f"   ⏱️  Total Duration: {self._format_duration(self.results['duration'])}")

        # Print AI Agent statistics if enabled
        if self.ai_agent_enabled and self.monitor_agent:
            print(f"\n{Colors.BOLD}AI AGENT STATISTICS:{Colors.ENDC}")

            monitor_stats = self.monitor_agent.get_statistics()
            print(f"   Issues Detected: {monitor_stats.get('patterns_detected', 0)}")
            print(f"   Interventions: {monitor_stats.get('interventions_performed', 0)}")

            if self.remediation_agent:
                success_rates = self.remediation_agent.get_success_rate()
                if success_rates:
                    print(f"\n{Colors.CYAN}   Fix Success Rates:{Colors.ENDC}")
                    for fix_name, stats in success_rates.items():
                        print(f"      {fix_name}: {stats['success_rate']} ({stats['successes']}/{stats['total_attempts']})")

                self.results['ai_agent_statistics'] = {
                    'monitor_stats': monitor_stats,
                    'fix_success_rates': success_rates
                }

            # Learning agent end-of-run summary
            if self.learning_agent:
                learning_summary = self.learning_agent.end_of_run_summary()
                if learning_summary.get("session_outcomes", 0) > 0:
                    print(f"\n{Colors.CYAN}   Learning Agent:{Colors.ENDC}")
                    print(f"      Outcomes recorded: {learning_summary['session_outcomes']}")
                    if learning_summary.get("adjustments"):
                        for adj in learning_summary["adjustments"]:
                            print(f"      Confidence adjusted: {adj['issue_type']} ({adj.get('reason', '')})")
                self.results.setdefault('ai_agent_statistics', {})['learning_summary'] = learning_summary

        print("\n" + "=" * 80 + "\n")

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format duration in human-readable format."""
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours}h {minutes}m"


def _in_ci() -> bool:
    """True when running under CI.

    Presence alone is the wrong test: CI=false or CI=0 would otherwise mean
    "yes, CI". Matches the `| bool` check in verify_feature_flags.yml.
    """
    return os.environ.get("CI", "").strip().lower() not in ("", "0", "false", "no")


def _major_minor(version: str) -> str:
    """'4.22.6' -> '4.22'. Scenario/feature availability is keyed on major.minor."""
    parts = str(version).split(".")
    return ".".join(parts[:2])


def _default_openshift_version(fallback: Optional[str] = None) -> Optional[str]:
    """Read openshift_version from vars/vars.yml, or return fallback."""
    try:
        vars_path = Path.cwd() / "vars" / "vars.yml"
        if vars_path.exists():
            with open(vars_path, encoding="utf-8") as vf:
                return (yaml.safe_load(vf) or {}).get("openshift_version", fallback)
    except (OSError, yaml.YAMLError):
        pass
    return fallback


def main():
    """Main entry point."""
    sys.stdout = _BlockingStream(sys.stdout)

    parser = argparse.ArgumentParser(
        description="CAPA Test Suite Runner - Execute Ansible test suites for CAPA (Cluster API Provider AWS)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Run a specific test suite:
    ./run-test-suite.py 02-basic-rosa-hcp-cluster-creation

  Run a test suite with extra variables:
    ./run-test-suite.py 10-configure-mce-environment -e name_prefix=xyz

  Run with multiple extra variables:
    ./run-test-suite.py 02-basic-rosa-hcp-cluster-creation -e name_prefix=dev -e aws_region=us-east-1

  Dry run (check mode, no changes):
    ./run-test-suite.py 10-configure-mce-environment --dry-run

  Dry run with extra variables:
    ./run-test-suite.py 10-configure-mce-environment --dry-run -e name_prefix=xyz

  Run all test suites:
    ./run-test-suite.py --all

  Run tests with specific tag:
    ./run-test-suite.py --tag rosa-hcp

  List available test suites:
    ./run-test-suite.py --list
        """
    )

    parser.add_argument(
        "suite_id",
        nargs="?",
        help="Test suite ID to execute (e.g., 02-basic-rosa-hcp-cluster-creation)"
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all test suites"
    )

    parser.add_argument(
        "--tag",
        type=str,
        help="Filter test suites by tag"
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available test suites"
    )

    parser.add_argument(
        "--format",
        choices=["json", "html", "junit", "all"],
        default="all",
        help="Output format for test results: json, html, junit (JUnit XML), or all (default: all)"
    )

    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Don't save results to file"
    )

    parser.add_argument(
        "-e", "--extra-vars",
        action="append",
        help="Extra variables in key=value format (can be used multiple times)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run in dry-run mode (ansible --check) - no changes will be made"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v, -vv, -vvv, or -vvvv for maximum)"
    )

    parser.add_argument(
        "--ai-agent",
        action="store_true",
        help="Enable AI agent framework for autonomous issue detection and remediation"
    )

    parser.add_argument(
        "--ai-agent-dry-run",
        action="store_true",
        help="Run AI agents in dry-run mode (detect and diagnose but don't apply fixes)"
    )

    parser.add_argument(
        "--feature",
        dest="features",
        action="append",
        help="Enable a cluster feature (can be used multiple times, e.g., --feature no-cni --feature tags)"
    )

    parser.add_argument(
        "--feature-group",
        type=str,
        help="Enable a preset group of features (e.g., day1-combo)"
    )

    parser.add_argument(
        "--scenario",
        type=str,
        help="Run a named scenario end-to-end (features, inputs and stages all "
             "come from the registry, e.g. --scenario day1-security)"
    )

    parser.add_argument(
        "--stages",
        type=str,
        help="Comma-separated subset of a scenario's stages to run "
             "(e.g. --stages 20,21 to skip hub setup/teardown)"
    )

    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List all available scenarios and the versions each can run on"
    )

    parser.add_argument(
        "--list-features",
        action="store_true",
        help="List all available cluster features"
    )

    parser.add_argument(
        "--list-groups",
        action="store_true",
        help="List all available feature groups"
    )

    parser.add_argument(
        "--ocp-version",
        type=str,
        default=None,
        help="Filter features by OpenShift version (e.g., 4.20)"
    )

    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate feature flags and inputs only (no ansible execution). "
             "Exits 0 if valid, 1 if errors found."
    )

    args = parser.parse_args()

    # Parse extra vars from command line
    extra_vars = {}
    if args.extra_vars:
        for var in args.extra_vars:
            if '=' in var:
                key, value = var.split('=', 1)
                extra_vars[key] = value
            else:
                print(f"{Colors.YELLOW}Warning: Ignoring invalid extra var format: {var}{Colors.ENDC}")

    # Handle --list-features
    if args.list_features:
        from feature_manager import FeatureManager
        try:
            fm = FeatureManager(Path.cwd())
        except FileNotFoundError as e:
            print(f"{Colors.RED}Error: {e}{Colors.ENDC}")
            return 1
        features = fm.list_features(version=args.ocp_version)
        print(f"\n{Colors.BOLD}Available Cluster Features:{Colors.ENDC}")
        if args.ocp_version:
            print(f"  (filtered for OpenShift {args.ocp_version})")
        print()
        for f in features:
            alias = f.get("cli_alias", "")
            alias_str = f" (--feature {alias})" if alias else ""
            print(f"  {Colors.CYAN}{f['id']}{Colors.ENDC}{alias_str}")
            print(f"    {f['description']}")
            print(f"    Type: {f['type']}  Default: {f['default']}  Phase: {f['phase']}")
            if f.get("min_version"):
                print(f"    Available from: OpenShift {f['min_version']}")
            print()
        return 0

    # Handle --list-groups
    if args.list_groups:
        from feature_manager import FeatureManager
        try:
            fm = FeatureManager(Path.cwd())
        except FileNotFoundError as e:
            print(f"{Colors.RED}Error: {e}{Colors.ENDC}")
            return 1
        groups = fm.list_groups()
        print(f"\n{Colors.BOLD}Available Feature Groups:{Colors.ENDC}\n")
        for g in groups:
            features = g["features"]
            feat_str = ", ".join(features) if features else "(default provisioning — no extra features)"
            print(f"  {Colors.CYAN}{g['name']}{Colors.ENDC}")
            print(f"    {g['description']}")
            print(f"    Features: {feat_str}")
            print()
        return 0

    # Handle --list-scenarios
    if args.list_scenarios:
        from feature_manager import FeatureManager
        try:
            fm = FeatureManager(Path.cwd())
        except FileNotFoundError as e:
            print(f"{Colors.RED}Error: {e}{Colors.ENDC}")
            return 1
        print(f"\n{Colors.BOLD}Available Scenarios:{Colors.ENDC}\n")
        for s in fm.list_scenarios():
            print(f"  {Colors.CYAN}{s['name']}{Colors.ENDC}")
            print(f"    {s['description']}")
            print(f"    Features: {', '.join(s['features'])}")
            print(f"    Versions: {', '.join(s['versions']) or '(none supported)'}")
            print(f"    Stages:   {' → '.join(s['stages'])}")
            if s.get("estimated_minutes"):
                print(f"    Runtime:  ~{s['estimated_minutes']} minutes")
            print()
        print("  Run one with: ./run-test-suite.py --scenario <name> "
              "-e openshift_version=<version>\n")
        return 0

    if args.stages and not args.scenario:
        print(f"{Colors.RED}Error: --stages only applies to --scenario runs{Colors.ENDC}")
        return 1

    # Expand --scenario into features, extra vars and a stage list
    scenario = None
    scenario_extra_vars = {}
    if args.scenario:
        from feature_manager import FeatureManager, ScenarioError
        try:
            fm = FeatureManager(Path.cwd())
        except FileNotFoundError as e:
            print(f"{Colors.RED}Error: {e}{Colors.ENDC}")
            return 1

        # Version comes from -e, then --ocp-version, then vars.yml.
        version = (extra_vars.get("openshift_version")
                   or args.ocp_version
                   or _default_openshift_version())
        if not version:
            print(f"{Colors.RED}Error: could not determine an OpenShift version. "
                  f"Pass -e openshift_version=<version>{Colors.ENDC}")
            return 1

        try:
            scenario = fm.resolve_scenario(args.scenario, _major_minor(version))
        except ScenarioError as e:
            print(f"{Colors.RED}Scenario error: {e}{Colors.ENDC}")
            return 1

        scenario_extra_vars = dict(scenario["extra_vars"])

        # A version_overrides entry may pin an exact build for a release family.
        # This has to be applied here rather than left to the normal precedence
        # chain: the assignment below and the later CLI merge would both
        # overwrite it, so a pin in the registry would silently do nothing.
        #
        # Only a family is substituted. Asking for "5.0" means "the 5.0 release",
        # and the registry knows 5.0 exists solely as an EC build; asking for an
        # exact build is an explicit choice and is always honoured.
        pinned = scenario_extra_vars.get("openshift_version")
        if pinned and version == _major_minor(version):
            print(f"{Colors.CYAN}Scenario pins OpenShift {version} → {pinned} "
                  f"(OCM cannot resolve a bare {version}){Colors.ENDC}")
            version = pinned
            if "openshift_version" in extra_vars:
                extra_vars["openshift_version"] = pinned

        # Suite 20 no longer pins a version, so pass it through explicitly.
        scenario_extra_vars["openshift_version"] = version
        # Recorded in the verification artifact so the report can say which
        # scenario produced it; suite 21 run on its own simply omits it.
        scenario_extra_vars["scenario_name"] = args.scenario

        # Stages after provisioning (verify, delete) address the cluster by
        # name; suite 20 derives it from name_prefix, so mirror that here.
        name_prefix = extra_vars.get("name_prefix")
        if name_prefix and "cluster_name" not in extra_vars:
            scenario_extra_vars["cluster_name"] = f"{name_prefix}-rosa-hcp"
        # Same reasoning for the machine pool, and it is not optional. Both
        # machinepool playbooks default pool_name to the literal "extra-pool",
        # and every cluster shares the namespace ns-rosa-hcp, so two unscoped
        # runs collide: the second add fails on "already exists", and stage 28
        # deletes whichever cluster's pool got there first. The nightly already
        # avoids this by passing -e pool_name="${NAME_PREFIX}-mp"; match it so a
        # scenario run and a Jenkins run name pools the same way.
        if name_prefix and "pool_name" not in extra_vars:
            scenario_extra_vars["pool_name"] = f"{name_prefix}-mp"

        if args.features is None:
            args.features = []
        args.features.extend(scenario["features"])
        args.features = list(dict.fromkeys(args.features))

        if args.stages:
            wanted = [s.strip() for s in args.stages.split(",") if s.strip()]
            selected = [
                st for st in scenario["stages"]
                if any(st["suite"] == w or st["suite"].startswith(f"{w}-") for w in wanted)
            ]
            unmatched = [
                w for w in wanted
                if not any(st["suite"] == w or st["suite"].startswith(f"{w}-")
                           for st in scenario["stages"])
            ]
            if unmatched:
                available = ", ".join(st["suite"] for st in scenario["stages"])
                print(f"{Colors.RED}Error: --stages entries not in scenario "
                      f"'{args.scenario}': {', '.join(unmatched)}. "
                      f"Available: {available}{Colors.ENDC}")
                return 1
            scenario["stages"] = selected

        print(f"\n{Colors.CYAN}Scenario '{args.scenario}' on OpenShift {version}: "
              f"{', '.join(scenario['features'])}{Colors.ENDC}")

    # Expand --feature-group into --feature flags
    if args.feature_group:
        from feature_manager import FeatureManager
        try:
            fm = FeatureManager(Path.cwd())
        except FileNotFoundError as e:
            print(f"{Colors.RED}Error: {e}{Colors.ENDC}")
            return 1
        group_features = fm.resolve_group(args.feature_group)
        if group_features is None:
            available = ", ".join(g["name"] for g in fm.list_groups())
            print(f"{Colors.RED}Unknown feature group: '{args.feature_group}'. Available: {available}{Colors.ENDC}")
            return 1
        if group_features:
            if args.features is None:
                args.features = []
            args.features.extend(group_features)
            args.features = list(dict.fromkeys(args.features))
            print(f"\n{Colors.CYAN}Feature group '{args.feature_group}': {', '.join(group_features)}{Colors.ENDC}")
        else:
            print(f"\n{Colors.CYAN}Feature group '{args.feature_group}': using default provisioning{Colors.ENDC}")

    # Process --feature flags into extra_vars
    if args.features:
        from feature_manager import FeatureManager
        try:
            fm = FeatureManager(Path.cwd())
        except FileNotFoundError as e:
            print(f"{Colors.RED}Error: {e}{Colors.ENDC}")
            return 1

        resolved = [fm.resolve_alias(f) for f in args.features]
        resolved = fm.auto_resolve_deps(resolved)

        # Read default version from vars.yml if not specified via -e
        version = (extra_vars.get("openshift_version")
                   or scenario_extra_vars.get("openshift_version")
                   or _default_openshift_version("4.21"))
        errors = fm.validate_features(resolved, version)
        if errors:
            for error_msg in errors:
                print(f"{Colors.RED}Feature error: {error_msg}{Colors.ENDC}")
            return 1

        feature_vars = fm.resolve_to_extra_vars(resolved)

        # A scenario supplies the inputs its features require, so they count as
        # provided here even though they never appeared on the command line.
        supplied = {**scenario_extra_vars, **extra_vars}
        input_warnings = fm.check_required_inputs(resolved, supplied)
        for warn in input_warnings:
            print(f"{Colors.YELLOW}Warning: {warn}{Colors.ENDC}")
        if input_warnings and _in_ci():
            print(f"{Colors.RED}Error: Required feature inputs missing in CI mode{Colors.ENDC}")
            return 1

        # Precedence: feature defaults < scenario (incl. version overrides) < CLI -e
        extra_vars = {**feature_vars, **scenario_extra_vars, **extra_vars}

        print(f"\n{Colors.CYAN}Features enabled: {', '.join(args.features)}{Colors.ENDC}")
        if set(resolved) != set(fm.resolve_alias(f) for f in args.features):
            auto_added = set(resolved) - set(fm.resolve_alias(f) for f in args.features)
            print(f"{Colors.CYAN}Auto-added dependencies: {', '.join(auto_added)}{Colors.ENDC}")
        print()

    # A featureless scenario skips the merge above, so apply its vars here.
    if scenario and not args.features:
        extra_vars = {**scenario_extra_vars, **extra_vars}

    # --validate-only: exit after feature validation without running ansible
    if args.validate_only:
        if scenario:
            print(f"{Colors.GREEN}Scenario '{scenario['name']}' validation PASSED{Colors.ENDC}")
            print(f"  Stages: {' → '.join(s['suite'] for s in scenario['stages'])}")
            print("  Resolved extra vars:")
            for key in sorted(extra_vars):
                print(f"    {key}={extra_vars[key]}")
        elif not args.features and not args.feature_group:
            print(f"{Colors.GREEN}No features to validate — input OK{Colors.ENDC}")
        else:
            print(f"{Colors.GREEN}Feature validation PASSED{Colors.ENDC}")
        return 0

    # Initialize runner
    runner = TestSuiteRunner(
        extra_vars=extra_vars,
        dry_run=args.dry_run,
        verbosity=args.verbose,
        ai_agent_enabled=args.ai_agent,
        ai_agent_dry_run=args.ai_agent_dry_run
    )

    # List suites if requested
    if args.list:
        suites = runner.list_test_suites()
        print(f"\n{Colors.BOLD}Available Test Suites:{Colors.ENDC}\n")
        for suite in suites:
            print(f"  {Colors.CYAN}{suite['id']}{Colors.ENDC}")
            print(f"    Name: {suite['name']}")
            print(f"    Description: {suite['description']}")
            print(f"    Tags: {', '.join(suite['tags'])}")
            print(f"    Playbooks: {suite['playbook_count']}\n")
        return 0

    # Validate arguments
    if not args.suite_id and not args.all and not args.tag and not scenario:
        parser.print_help()
        print(f"\n{Colors.RED}Error: Please specify a suite ID, --scenario <name>, "
              f"--all, or --tag <tag>{Colors.ENDC}")
        return 1

    # Track overall execution time
    runner.results["start_time"] = datetime.now().isoformat()
    start_time = time.time()

    # Execute tests
    success = False
    try:
        if scenario:
            success = runner.run_scenario(scenario)
        elif args.all or args.tag:
            success = runner.run_all_suites(tag_filter=args.tag)
        else:
            success = runner.run_test_suite(args.suite_id)

    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}⚠ Test execution interrupted by user{Colors.ENDC}")
        runner.results["failed"] += 1
        success = False

    # Calculate total duration
    runner.results["end_time"] = datetime.now().isoformat()
    runner.results["duration"] = time.time() - start_time

    # Print final summary
    runner._print_final_summary()

    # Save results
    if not args.no_save:
        if args.format in ["json", "all"]:
            json_file = runner.save_results(format="json")
            print(f"{Colors.CYAN}📄 JSON results: {json_file}{Colors.ENDC}")

        if args.format in ["html", "all"]:
            html_file = runner.save_results(format="html")
            print(f"{Colors.CYAN}📄 HTML report: {html_file}{Colors.ENDC}")

        if args.format in ["junit", "all"]:
            junit_file = runner.save_results(format="junit")
            print(f"{Colors.CYAN}📄 JUnit XML: {junit_file}{Colors.ENDC}")
            # Log the XML path and its computed counts so a build flipped to
            # UNSTABLE by the junit step can be traced back to the exact
            # failures/errors this run recorded (rather than stale XMLs the
            # Jenkins glob may also pick up).
            # Read the counts the XML build already computed rather than
            # deriving them a second time. Two independent derivations of the
            # same thing is exactly the drift the refactor set out to remove.
            _c = runner.last_junit_counts or {}
            print(
                f"{Colors.CYAN}   ↳ Reports: {_c.get('tests', 0)} tests, "
                f"{_c.get('failures', 0)} failures, {_c.get('errors', 0)} errors, "
                f"{_c.get('skipped', 0)} skipped{Colors.ENDC}"
            )

    # Return exit code for CI/CD
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
