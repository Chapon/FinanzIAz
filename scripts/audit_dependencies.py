"""
Run a security audit against the project's installed dependencies.

This is a thin wrapper over ``pip-audit`` that:
1. Verifies pip-audit is available (graceful error if not).
2. Runs against the active environment (so it sees the *actual* installed
   versions, not just what's listed in requirements.txt).
3. Prints a human-readable summary plus an actionable recommendation.

Usage
-----
    pip install -r requirements-dev.txt   # gets pip-audit
    python scripts/audit_dependencies.py

Exit codes
----------
0   no vulnerabilities found
1   vulnerabilities or audit failure
2   pip-audit not installed
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    # Locate pip-audit in the current Python environment first.
    try:
        import pip_audit  # noqa: F401
    except ImportError:
        print(
            "pip-audit is not installed.\n"
            "Install it first:\n"
            "    pip install pip-audit\n"
            "Or, recommended for full dev tooling:\n"
            "    pip install -r requirements-dev.txt",
            file=sys.stderr,
        )
        return 2

    print("Running pip-audit on the active environment …\n")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip_audit", "--strict", "--progress-spinner=off"],
            cwd=ROOT,
            check=False,
            text=True,
        )
    except FileNotFoundError:
        print("Could not invoke pip-audit. Is it installed in this venv?", file=sys.stderr)
        return 2

    if result.returncode == 0:
        print("\n✓ No known vulnerabilities found.")
        return 0

    print(
        "\n✗ pip-audit reported issues. Review the table above and bump the "
        "affected packages in requirements.txt, then regenerate the lock:\n"
        "    python scripts/lock_requirements.py",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
