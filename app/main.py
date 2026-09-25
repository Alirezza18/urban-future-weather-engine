"""NEPENTHE | Urban-Future-Weather Engine — API server.

Serves the Leaflet UI and a small JSON API over the Madrid EPW corpus:

  GET /                          -> the web app (static/index.html)
  GET /healthz                   -> liveness probe
  GET /api/sites                 -> 1,013 site coordinates from locations.csv
  GET /api/site/{id}             -> climate summaries for all scenarios at one site
  GET /api/warming               -> per-site warming deltas (bulk, precomputed)
  GET /api/epw/{scenario}/{id}   -> download the raw EPW file

Design notes
------------
* The corpus is large (~3,000 EPWs); per-site stats are computed lazily on
  first request and cached in-process. The warming map needs deltas for all
  1,013 sites, so those are precomputed once at startup in a background
  thread (light: one pass over two small columns per file).
"""
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import DATA_DIR, LOCAL_DATA_DIR, PORT, SCENARIOS, WARMING_SCENARIOS
from .epw import summarize_epw


def _source_dir(scenario: str | None = None) -> Path:
    """Where to read locations.csv / a scenario's files from."""
    base = LOCAL_DATA_DIR if LOCAL_DATA_DIR is not None else DATA_DIR
    if scenario is None:
        return base
    return base / SCENARIOS[scenario]["dir"]

app = FastAPI(title="Urban-Future-Weather Engine", version="1.3.1")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# ---------------------------------------------------------------------------
# Site catalogue
# ---------------------------------------------------------------------------

def _load_sites() -> list[dict]:
    """locations.csv: epwIndex,latitude,longitude -> list of site dicts.

    Always read from DATA_DIR (the mounted share): this runs at import time,
    before the corpus sync, and it's a single small file.

    Missing corpus is not fatal: the app boots with zero sites and says so,
    so `docker run` without a mount yields a healthy-but-empty instance
    (useful for CI smoke tests) instead of a crash loop.
    """
    sites: list[dict] = []
    path = DATA_DIR / "locations.csv"
    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    sites.append({
                        "id": int(row["epwIndex"]),
                        "lat": float(row["latitude"]),
                        "lon": float(row["longitude"]),
                    })
                except (KeyError, ValueError, TypeError):
                    continue
    except OSError as exc:
        print(f"[ufwe] WARNING: cannot read {path} ({exc}) — no corpus "
              f"mounted? Serving an empty catalogue.", flush=True)
        return sites
    sites.sort(key=lambda s: s["id"])
    return sites


SITES: list[dict] = _load_sites()
SITE_BY_ID: dict[int, dict] = {s["id"]: s for s in SITES}

# ---------------------------------------------------------------------------
# Scenario file resolution
# ---------------------------------------------------------------------------

def _scenario_file(scenario: str, site_id: int) -> Path:
    cfg = SCENARIOS.get(scenario)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"unknown scenario '{scenario}'")
    # Local sync dir first; fall back to the mounted share while the sync
    # is still filling it (or if a file was never copied).
    bases = [_source_dir(scenario)]
    share = DATA_DIR / cfg["dir"]
    if share not in bases:
        bases.append(share)
    for base in bases:
        for pattern in cfg["patterns"]:
            candidate = base / pattern.format(i=site_id)
            if candidate.is_file():
                return candidate
    raise HTTPException(
        status_code=404,
        detail=f"site {site_id} missing in scenario '{scenario}'",
    )


# ---------------------------------------------------------------------------
# Warming precompute (background)
# ---------------------------------------------------------------------------

_warming_lock = threading.Lock()
_warming_data: dict | None = None
_warming_progress = {"done": 0, "total": len(SITES)}

# Completed passes are cached across restarts (mount a small rw volume at
# UFWE_CACHE_DIR; disabled when unset).
_CACHE_VERSION = "ufwe-warming-v4"

# Variables whose (future − historical) deltas feed the overlay map.
# key -> (label, unit, diverging?) — diverging scales span negative values.
DELTA_VARS: dict[str, tuple[str, str, bool]] = {
    "temp": ("Δ mean dry-bulb", "°C", False),
    "rh":   ("Δ mean relative humidity", "%", True),
    "rad":  ("Δ mean global horiz. radiation", "W/m²", True),
    "wind": ("Δ mean wind speed", "m/s", True),
    "cdd":  ("Δ cooling degree days (base 18)", "°C·d", False),
}
_CACHE_FILE = Path(os.environ.get("UFWE_CACHE_DIR", "")) / "warming.json" if os.environ.get("UFWE_CACHE_DIR") else None


def _cache_load() -> dict | None:
    if _CACHE_FILE is None or not _CACHE_FILE.is_file():
        return None
    try:
        payload = json.loads(_CACHE_FILE.read_text())
        if payload.get("version") == _CACHE_VERSION and payload.get("n_sites") == len(SITES):
            return payload["data"]
    except (json.JSONDecodeError, OSError, KeyError):
        pass
    return None


def _cache_save(data: dict) -> None:
    if _CACHE_FILE is None:
        return
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps({"version": _CACHE_VERSION, "n_sites": len(SITES), "data": data}))
    except OSError:
        pass


def _sync_corpus() -> None:
    """One-time copy of the corpus into LOCAL_DATA_DIR (idempotent).

    Skips files already present with the same size, so restarts cost a
    directory walk, not a re-download. After this, 9p is never read again.
    """
    assert LOCAL_DATA_DIR is not None
    if not DATA_DIR.is_dir():
        print(f"[ufwe] WARNING: data dir {DATA_DIR} does not exist — no "
              f"corpus mounted? Skipping sync; UI will show an empty catalogue.",
              flush=True)
        return
    LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    copied = skipped = failed = 0

    jobs: list[tuple[Path, Path]] = [(DATA_DIR / "locations.csv",
                                      LOCAL_DATA_DIR / "locations.csv")]
    for cfg in SCENARIOS.values():
        src_dir = DATA_DIR / cfg["dir"]
        dst_dir = LOCAL_DATA_DIR / cfg["dir"]
        dst_dir.mkdir(parents=True, exist_ok=True)
        for src in src_dir.iterdir():
            if src.is_file() and not src.name.startswith("._"):
                jobs.append((src, dst_dir / src.name))

    for src, dst in jobs:
        try:
            if dst.is_file() and dst.stat().st_size == src.stat().st_size:
                skipped += 1
                continue
            shutil.copyfile(src, dst)
            copied += 1
        except OSError as exc:
            failed += 1
            print(f"[ufwe] sync failed {src.name}: {exc}", flush=True)

    print(f"[ufwe] corpus sync: {copied} copied, {skipped} skipped, "
          f"{failed} failed in {time.monotonic()-t0:.0f}s", flush=True)


def _scenario_mean(scenario: str, site_id: int) -> dict | None:
    """Annual metric bundle for one site/scenario, or None if unavailable.

    Returns the subset of fields the warming pass needs. Deliberately broad
    except: a missing file raises HTTPException, a truncated one ValueError,
    a vanished share OSError — any of them must skip the site, never kill
    the precompute thread.
    """
    try:
        s = summarize_epw(_scenario_file(scenario, site_id), site_id, "", "")
        return {"temp": s.mean_db, "rh": s.means.get("rh", 0.0),
                "rad": s.means.get("glohorz", 0.0),
                "wind": s.means.get("wind", 0.0), "cdd": s.cdd18}
    except Exception:
        return None


def _precompute_warming() -> None:
    """Per-site, per-variable deltas (future − historical) for the overlay.

    One pass over the corpus; everything the map and the histogram need is
    computed once here and cached.
    """
    hist_stats: dict[int, dict] = {}
    deltas: dict[str, dict[str, dict[int, float]]] = {
        s: {k: {} for k in DELTA_VARS} for s in WARMING_SCENARIOS}
    unavailable: dict[str, list[int]] = {
        "historical": [], **{s: [] for s in WARMING_SCENARIOS}}
    t0 = time.monotonic()

    for site in SITES:
        sid = site["id"]
        h = _scenario_mean("historical", sid)
        if h is None:
            unavailable["historical"].append(sid)
            with _warming_lock:
                _warming_progress["done"] += 1
            continue
        hist_stats[sid] = h
        for scen in WARMING_SCENARIOS:
            f = _scenario_mean(scen, sid)
            if f is None:
                unavailable[scen].append(sid)
                continue
            d = deltas[scen]
            d["temp"][sid] = round(f["temp"] - h["temp"], 2)
            d["rh"][sid] = round(f["rh"] - h["rh"], 2)
            d["rad"][sid] = round(f["rad"] - h["rad"], 1)
            d["wind"][sid] = round(f["wind"] - h["wind"], 2)
            d["cdd"][sid] = round(f["cdd"] - h["cdd"], 0)
        with _warming_lock:
            _warming_progress["done"] += 1

    payload = {
        "scenarios": {
            key: {
                "label": SCENARIOS[key]["label"],
                "color": SCENARIOS[key]["color"],
                "deltas": {
                    var: [{"id": sid, "delta": val}
                          for sid, val in sorted(vals.items())]
                    for var, vals in vars_.items()
                },
            }
            for key, vars_ in deltas.items()
        },
        "n_sites": len(hist_stats),
        "unavailable": {k: sorted(v) for k, v in unavailable.items()},
        "delta_vars": {
            key: {"label": lbl, "unit": unit, "diverging": div}
            for key, (lbl, unit, div) in DELTA_VARS.items()
        },
    }
    with _warming_lock:
        globals()["_warming_data"] = payload
    _cache_save(payload)
    print(f"[ufwe] warming precompute finished in {time.monotonic()-t0:.0f}s", flush=True)


@app.on_event("startup")
def _start_warming_precompute() -> None:
    # A valid cache makes warming instantly ready — it doesn't depend on the
    # corpus, so load it first and let the corpus sync run in parallel.
    cached = _cache_load()
    if cached is not None:
        with _warming_lock:
            globals()["_warming_data"] = cached
            _warming_progress["done"] = _warming_progress["total"]
        print("[ufwe] warming deltas loaded from cache", flush=True)
        if LOCAL_DATA_DIR is not None:
            threading.Thread(target=_sync_corpus,
                             name="corpus-sync", daemon=True).start()
    else:
        def _worker() -> None:
            if LOCAL_DATA_DIR is not None:
                _sync_corpus()
            _precompute_warming()

        threading.Thread(target=_worker, name="corpus-sync+warming",
                         daemon=True).start()
    # Zip artifacts wait for the sync internally (file-count poll), so they
    # can start unconditionally in both branches.
    if LOCAL_DATA_DIR is not None:
        _start_artifact_builders()


# ---------------------------------------------------------------------------
# Downloadable zip artifacts (corpus-level)
# ---------------------------------------------------------------------------

DOWNLOAD_DIR = Path(os.environ.get("UFWE_DOWNLOAD_DIR", "/downloads"))


def _zip_status(name: str) -> dict:
    path = DOWNLOAD_DIR / name
    if path.is_file():
        return {"name": name, "state": "ready", "bytes": path.stat().st_size,
                "url": f"/api/downloads/{name}"}
    lock_path = DOWNLOAD_DIR / f".{name}.building"
    if lock_path.exists():
        return {"name": name, "state": "building"}
    return {"name": name, "state": "pending"}


@app.get("/api/downloads")
def downloads_index() -> dict:
    """Status of every corpus-level download artifact."""
    return {
        "artifacts": [
            _zip_status("historical_all_sites.zip"),
            _zip_status("midfuture_all_sites.zip"),
            _zip_status("future2084_all_sites.zip"),
            _zip_status("ufwe_full_corpus.zip"),
        ],
        "note": "zips are built once in the background; rebuild by deleting "
                "them from the downloads volume",
    }


@app.get("/api/downloads/{name}")
def downloads_fetch(name: str) -> FileResponse:
    if name not in {"historical_all_sites.zip", "midfuture_all_sites.zip",
                    "future2084_all_sites.zip", "ufwe_full_corpus.zip"}:
        raise HTTPException(status_code=404, detail="unknown artifact")
    path = DOWNLOAD_DIR / name
    if not path.is_file():
        return JSONResponse(status_code=202, content={"status": "building",
                                                      "artifact": name})
    return FileResponse(path, media_type="application/zip", filename=name)


def _build_zip(name: str, entries: list[tuple[Path, str]]) -> None:
    """Write a zip atomically; a lock file marks it in-progress."""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = DOWNLOAD_DIR / f".{name}.building"
    lock_path.touch()
    final = DOWNLOAD_DIR / name
    t0 = time.monotonic()
    try:
        fd, tmp_name = tempfile.mkstemp(suffix=".zip", dir=DOWNLOAD_DIR)
        with os.fdopen(fd, "wb") as tmp:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for src, arcname in entries:
                    zf.write(src, arcname)
        os.replace(tmp_name, final)
        print(f"[ufwe] built {name}: {len(entries)} files "
              f"({final.stat().st_size/1e6:.0f} MB) in "
              f"{time.monotonic()-t0:.0f}s", flush=True)
    finally:
        lock_path.unlink(missing_ok=True)


def _start_artifact_builders() -> None:
    """Kick off corpus zip builds once the local corpus sync is done."""
    def _worker() -> None:
        if LOCAL_DATA_DIR is None:
            return
        # wait for the sync to finish (dirs fully populated) — but give up
        # after ~10 min so a corpus-less deployment doesn't poll forever
        expected = {cfg["dir"]: None for cfg in SCENARIOS.values()}
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            counts = {
                d: sum(1 for p in (LOCAL_DATA_DIR / d).glob("*.epw")
                       if not p.name.startswith("._"))
                for d in expected
            }
            total = sum(counts.values())
            if total >= 3000:
                break
            time.sleep(2)
        else:
            print("[ufwe] zip-builder: corpus never appeared — skipping "
                  "artifact builds", flush=True)
            return
        for key, cfg in SCENARIOS.items():
            name = f"{key}_all_sites.zip"
            if _zip_status(name)["state"] == "ready":
                continue
            base = LOCAL_DATA_DIR / cfg["dir"]
            entries = [(p, f"{key}/{p.name}") for p in sorted(base.glob("*.epw"))
                       if not p.name.startswith("._")]
            _build_zip(name, entries)
        full = "ufwe_full_corpus.zip"
        if _zip_status(full)["state"] != "ready":
            entries = []
            for key, cfg in SCENARIOS.items():
                base = LOCAL_DATA_DIR / cfg["dir"]
                entries.extend((p, f"{key}/{p.name}") for p in sorted(base.glob("*.epw"))
                               if not p.name.startswith("._"))
            entries.append((LOCAL_DATA_DIR / "locations.csv", "locations.csv"))
            _build_zip(full, entries)

    threading.Thread(target=_worker, name="zip-builder", daemon=True).start()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/healthz")
def healthz() -> dict:
    with _warming_lock:
        progress = dict(_warming_progress)
        ready = _warming_data is not None
    return {"status": "ok", "warming_ready": ready, **progress}


@app.get("/api/sites")
def sites() -> dict:
    return {"count": len(SITES), "sites": SITES}


@app.get("/api/site/{site_id}")
def site_detail(site_id: int) -> dict:
    if site_id not in SITE_BY_ID:
        raise HTTPException(status_code=404, detail=f"unknown site {site_id}")
    summaries = []
    for key, cfg in SCENARIOS.items():
        try:
            summary = summarize_epw(
                _scenario_file(key, site_id), site_id,
                cfg["label"], cfg["color"],
            )
            summaries.append({"scenario": key, **asdict(summary)})
        except Exception as exc:
            # HTTPException (missing file), ValueError (bad rows), OSError
            # (share trouble) — report per-scenario, keep the rest usable.
            detail = getattr(exc, "detail", None) or str(exc)
            summaries.append({"site_id": site_id, "scenario": key,
                              "error": detail})
    return {"site": SITE_BY_ID[site_id], "scenarios": summaries}


@app.get("/api/warming")
def warming() -> JSONResponse:
    with _warming_lock:
        data = _warming_data
        progress = dict(_warming_progress)
    if data is None:
        return JSONResponse(
            status_code=202,
            content={"status": "computing", **progress},
        )
    return JSONResponse(data)


@app.get("/api/quality")
def quality() -> dict:
    """Per-scenario data-quality report derived from the warming pass."""
    with _warming_lock:
        data = _warming_data
    if data is None:
        return {"status": "computing", **_warming_progress}
    un = data["unavailable"]
    return {
        "status": "ok",
        "total_sites": len(SITES),
        "scenarios": {
            key: {
                "label": SCENARIOS[key]["label"],
                "available": len(SITES) - len(un[key]),
                "unavailable": un[key],
                "n": len(un[key]),
            }
            for key in ("historical", *WARMING_SCENARIOS)
        },
    }


@app.get("/api/sites.geojson")
def sites_geojson() -> dict:
    """All sites as GeoJSON Point features (for QGIS/ArcGIS/web reuse)."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point",
                             "coordinates": [round(s["lon"], 8), round(s["lat"], 8)]},
                "properties": {"site_id": s["id"]},
            }
            for s in SITES
        ],
    }


@app.get("/api/epw/{scenario}/{site_id}")
def epw_download(scenario: str, site_id: int) -> FileResponse:
    path = _scenario_file(scenario, site_id)
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=path.name,
    )


@app.get("/api/site/{site_id}/bundle.zip")
def site_bundle(site_id: int) -> Response:
    """All available scenario EPWs for one site, zipped on the fly."""
    if site_id not in SITE_BY_ID:
        raise HTTPException(status_code=404, detail=f"unknown site {site_id}")
    buf = io.BytesIO()
    included = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for key, cfg in SCENARIOS.items():
            try:
                path = _scenario_file(key, site_id)
            except HTTPException:
                continue
            zf.write(path, f"site_{site_id}/{key}__{path.name}")
            included.append(key)
    if not included:
        raise HTTPException(status_code=404,
                            detail=f"site {site_id} has no available files")
    buf.seek(0)
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="site_{site_id}_all_scenarios.zip"',
                 "X-Included-Scenarios": ",".join(included)},
    )


# Static UI last so /api/* and /healthz keep priority.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
