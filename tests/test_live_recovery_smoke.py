from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "ops" / "recovery" / "verify-live-restore.sh"


def run_script(extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ["PATH"], "PYTHON_BIN": sys.executable, **extra_env}
    return subprocess.run(
        [str(SCRIPT)],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_script_has_valid_shell_syntax_and_is_executable() -> None:
    assert os.access(SCRIPT, os.X_OK)
    result = subprocess.run(
        ["sh", "-n", str(SCRIPT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_script_requires_image_contract() -> None:
    result = run_script({})

    assert result.returncode != 0
    assert "POSTGRES_IMAGE is required" in result.stderr


def test_script_rejects_mutable_image_before_using_docker() -> None:
    result = run_script(
        {
            "POSTGRES_IMAGE": "postgres:18-alpine",
            "GRAFANA_IMAGE": f"grafana/grafana:13.2.0@sha256:{'a' * 64}",
            "GRAFANA_VERSION": "13.2.0",
        }
    )

    assert result.returncode != 0
    assert "POSTGRES_IMAGE has an unsafe or unsupported format" in result.stderr
