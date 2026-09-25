"""Run the parser + API tests inside the project's Docker image.

The synthetic corpus means no real data is needed — this is exactly what
CI runs on every push.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGE = "urban-future-weather-engine:ci"

command = [
    "docker", "run", "--rm",
    "-v", f"{ROOT}:/repo:ro",
    "-w", "/repo",
    IMAGE,
    "python", "-m", "pytest", "tests/", "-q",
]

if __name__ == "__main__":
    subprocess.run(
        ["docker", "build", "-q", "-t", IMAGE, "-"],
        input=(
            "FROM python:3.12-slim\n"
            "WORKDIR /repo\n"
            "RUN pip install --no-cache-dir fastapi uvicorn pytest httpx\n"
        ).encode(),
        check=True,
    )
    sys.exit(subprocess.run(command).returncode)
