# NEPENTHE | Urban-Future-Weather Engine (UFWE)

**A map-first explorer for a city-scale, multi-era EPW corpus.**

![version](https://img.shields.io/badge/version-1.3.1-38bdf8)
[![CI](https://github.com/Alirezza18/urban-future-weather-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/Alirezza18/urban-future-weather-engine/actions/workflows/ci.yml)
![license](https://img.shields.io/badge/license-MIT-green)
![python](https://img.shields.io/badge/python-3.12-blue)
![docker](https://img.shields.io/badge/docker-ready-2496ED)

> **v1.3** — download-first site card: one primary **Download EPW** button,
> per-scenario EPW links, a one-click all-scenarios `.zip`, and stat chips
> (CDD18, HDD18, hot hours >32 °C, frost hours). Clicking a site also pops up
> **direct EPW download links on the map** for every available era. A
> **methodology card** documents the generation pipeline (EURO-CORDEX →
> bias correction → heatwave-preserving morphing → UWG urban deltas) and every
> site card carries per-era provenance lines. Multi-variable
> monthly charts (temperature, dew point, RH, radiation, wind) and a city-wide
> factor overlay — ΔT, ΔCDD, ΔRH, Δradiation, Δwind on diverging color scales —
> map how any climate factor varies across the 1,013 sites.
>
> Plus v1.2 downloads at every level (single EPW → site bundle → per-scenario
> zip → full corpus, 721 MB, resumable) and v1.1 keyless basemaps (Esri
> dark/streets/satellite), `#site=ID` deep links, warming-Δ histogram,
> data-quality panel, domain outline, `GET /api/sites.geojson`,
> `GET /api/quality`, `GET /api/downloads`.

UFWE serves the Madrid morphed-weather dataset — **1,013 urban sites × 3 climate
eras × 8,760 hourly records (~26.6M data points)** — through a dark control-room
web app: Leaflet site map, per-site climate profiles, city-wide warming overlay,
and raw EPW download for every site/scenario pair.

| Era | Key | Folder | Files |
|---|---|---|---|
| Historical (most-severe year) | `historical` | `Historical_MostSevere` | 1,013 |
| Mid-century (most-severe year) | `midfuture` | `Midfuture MostSevere` | 1,007* |
| 2084 (most-severe year) | `future2084` | `FutureSevere_2084` | 1,013 |

\* 6 sites absent from the source corpus and 1 unparseable file; the API
reports all of them as unavailable rather than failing.

## Tests

The test suite runs entirely on a **synthetic mini-corpus** (built in-memory
by the fixtures) — no real data needed:

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests/ -v
```

or in Docker, exactly as CI does:

```bash
python tests/run_in_docker.py
```

CI (GitHub Actions) runs the tests on every push, then builds the image and
smoke-tests that the container boots and reports healthy.

## Citation

If UFWE contributes to your research, please cite it — see
[CITATION.cff](CITATION.cff) (GitHub renders this as a **Cite this
repository** button) or:

> Karimi, A. (2026). *NEPENTHE | Urban-Future-Weather Engine: a map-first
> explorer for city-scale, multi-era future weather files* (Version 1.3.1)
> [Computer software]. https://github.com/Alirezza18/urban-future-weather-engine

## Quickstart

```bash
# from this directory
docker compose up --build
# → http://localhost:8610
```

Or with plain Docker (adjust the corpus path):

```bash
docker build -t urban-future-weather-engine:1.3.0 .
docker run -d --name ufwe -p 8610:8610 \
  -v "D:/alireza app:/data:ro" \
  -v ufwe-data:/localdata \
  -v ufwe-cache:/cache \
  -v ufwe-downloads:/downloads \
  urban-future-weather-engine:1.3.0
```

On first start the engine precomputes per-site warming deltas (a single pass
over ~3,000 EPWs) in a background thread; the UI shows live progress. The
result is cached in `/cache`, so restarts are instant.

## API

| Endpoint | Purpose |
|---|---|
| `GET /healthz` | liveness + warming precompute progress |
| `GET /api/sites` | site catalogue (`id`, `lat`, `lon` from `locations.csv`) |
| `GET /api/site/{id}` | per-scenario summary: mean/max/min dry-bulb, CDD18/HDD18, hot & frost hours, monthly means for temp / dew point / RH / radiation / wind |
| `GET /api/warming` | per-site Δ for temperature, CDD, RH, radiation, wind vs historical (202 while computing) |
| `GET /api/quality` | per-scenario availability: counts + missing/corrupt site ids |
| `GET /api/sites.geojson` | all sites as GeoJSON Point features (QGIS/ArcGIS-ready) |
| `GET /api/epw/{scenario}/{id}` | single EPW download (`N_updated.epw` aliasing handled) |
| `GET /api/site/{id}/bundle.zip` | one site, all available scenarios, zipped on the fly |
| `GET /api/downloads` | status of the precomputed corpus-level zip artifacts |
| `GET /api/downloads/{name}` | per-scenario all-sites zip or full-corpus zip (resumable) |

Interactive docs: `http://localhost:8610/docs` (Swagger UI).

## Expected `/data` layout

```
<data-dir>/
  locations.csv                # epwIndex,latitude,longitude
  Historical_MostSevere/  {i}.epw
  Midfuture MostSevere/   {i}_updated.epw | {i}.epw
  FutureSevere_2084/      {i}.epw
```

Override the mount with `UFWE_DATA_DIR`; scenario folders and filename patterns
are declared in `app/config.py` — drop in new eras without touching code.

## Architecture

```
app/
  config.py   # scenario registry & data paths
  epw.py      # bulk-read EPW summarizer (single-syscall file reads)
  main.py     # FastAPI: lazy per-site stats, threaded warming precompute
static/
  index.html  # Leaflet + Chart.js single-page UI (no build step)
```

Design choices:

- **Light by design** — FastAPI + Leaflet + Chart.js from CDN; the whole
  app is 4 small files.
- **Lazy per-site, bulk once** — clicking a site parses 3 EPWs on demand;
  the warming map is one background pass, cached to disk.
- **9p-aware reads** — files are read in one syscall each; buffered small
  reads are pathological on Docker Desktop Windows mounts.
- **Honest data** — sites missing from a scenario are surfaced as such in the
  UI, never silently skipped.

## Roadmap

- [ ] Multi-city corpora (registry already supports extra scenario folders)
- [ ] Degree-day base-temperature picker (10/12/18/21 °C)
- [ ] Zip-a-selection batch export (draw a polygon, download its sites)
- [ ] UTCI / thermal-comfort metrics per site
- [ ] Batch EPW export (zip a selection)
- [ ] GHCR publication + CI mirror of the Auto-SOF pipeline

## Author & context

**[Alireza Karimi](https://github.com/Alirezza18)** — Computational Building
Scientist, PhD candidate (Architecture), Universidad de Sevilla.
UFWE is the web front of the Urban-Future-Weather research framework;
its sibling project [nepenthe-auto-sof](https://github.com/Alirezza18/nepenthe-auto-sof)
provides no-code surrogate-based optimization over datasets like this one.

ORCID: [0000-0002-6296-9496](https://orcid.org/0000-0002-6296-9496)

## License

[MIT](LICENSE)
