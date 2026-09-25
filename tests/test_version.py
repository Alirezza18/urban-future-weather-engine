"""Version + import smoke checks."""
import re
from pathlib import Path


def test_version_consistency():
    """FastAPI version matches README badge and compose tag."""
    from app.main import app

    v = app.version
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text()
    assert re.search(r"version-\d+\.\d+\.\d+", readme), "README version badge missing"
    assert f"version-{v}" in readme, f"README badge out of date (app is {v})"
    compose = (Path(__file__).resolve().parent.parent / "docker-compose.yml").read_text()
    assert v in compose, f"docker-compose.yml image tag out of date (app is {v})"
