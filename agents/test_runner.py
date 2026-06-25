"""
Auto-test execution for feature verification.
"""

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List


def build_test_command(feature_ids: List[str], suite_id: str = "20-rosa-hcp-provision") -> List[str]:
    feature_args = []
    for feat_id in feature_ids:
        feature_args.extend(["--feature", feat_id.replace("_", "-")])
    return ["./run-test-suite.py", suite_id] + feature_args + ["--update-docs"]


def execute_test(cmd: List[str], base_dir: Path) -> Dict:
    start_time = datetime.now()

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=base_dir,
        )

        output_lines = []
        for line in iter(process.stdout.readline, ""):
            if line:
                stripped = line.rstrip()
                print(stripped)
                output_lines.append(stripped)

        process.stdout.close()
        return_code = process.wait()

    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to execute auto-test: {e}",
            "duration": (datetime.now() - start_time).total_seconds(),
            "exit_code": -1,
        }

    duration = (datetime.now() - start_time).total_seconds()
    success = return_code == 0

    return {
        "success": success,
        "duration": duration,
        "exit_code": return_code,
        "command": " ".join(cmd),
    }
