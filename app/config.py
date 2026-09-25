"""UFWE configuration: where the EPW corpus lives and how scenarios map to folders."""
from __future__ import annotations

import os
from pathlib import Path

# Root of the EPW pipeline corpus (mounted read-only in Docker).
# Override with UFWE_DATA_DIR for local dev or alternative deployments.
DATA_DIR = Path(os.environ.get("UFWE_DATA_DIR", "/data"))

# All runtime reads go through LOCAL_DATA_DIR. When set, the app syncs
# DATA_DIR -> LOCAL_DATA_DIR once at startup (skipping files that already
# exist with the same size) and never touches DATA_DIR again. This keeps
# network mounts (Docker Desktop 9p shares) out of the request path — they
# degrade under sustained small-file I/O. Point UFWE_LOCAL_DATA_DIR at a
# Docker volume; unset it to read DATA_DIR directly.
LOCAL_DATA_DIR = Path(os.environ["UFWE_LOCAL_DATA_DIR"]) \
    if os.environ.get("UFWE_LOCAL_DATA_DIR") else None

# Scenario registry: key -> where files live and how they are named.
# `patterns` are tried in order; `{i}` is the site index from locations.csv.
# (The Mid-century folder names files `N_updated.epw` — handled by the fallback.)
SCENARIOS: dict[str, dict] = {
    "historical": {
        "label": "Historical (most-severe year)",
        "dir": "Historical_MostSevere",
        "patterns": ["{i}.epw"],
        "color": "#38bdf8",
    },
    "midfuture": {
        "label": "Mid-century (most-severe year)",
        "dir": "Midfuture MostSevere",
        "patterns": ["{i}_updated.epw", "{i}.epw"],
        "color": "#f59e0b",
    },
    "future2084": {
        "label": "2084 (most-severe year)",
        "dir": "FutureSevere_2084",
        "patterns": ["{i}.epw"],
        "color": "#ef4444",
    },
}

# Scenarios colored on the warming map (each needs historical as baseline).
WARMING_SCENARIOS: tuple[str, ...] = ("midfuture", "future2084")

# Port for `python -m app.main` local runs; Docker CMD uses the same default.
PORT = int(os.environ.get("UFWE_PORT", "8610"))
