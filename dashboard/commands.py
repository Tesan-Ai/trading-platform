"""Subprocess helpers for dashboard action buttons."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def command_env() -> dict[str, str]:
    env = os.environ.copy()
    root = str(PROJECT_ROOT)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = root if not existing else f"{root}{os.pathsep}{existing}"
    return env


def python_command(script: str, *args: str) -> list[str]:
    return [PYTHON, script, *args]
