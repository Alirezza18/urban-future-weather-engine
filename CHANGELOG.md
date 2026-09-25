# Changelog

All notable changes to the Urban-Future-Weather Engine are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [SemVer](https://semver.org/).

## [1.3.1] — 2026-09-25

### Added
- **Methodology card** in the sidebar documenting the full generation
  pipeline: EURO-CORDEX trajectories → hybrid bias correction →
  heatwave-preserving morphing → UWG urban deltas on a 50 × 50 m grid.
- **Per-era provenance lines** on every site card (e.g. "EURO-CORDEX RCP 8.5 ·
  bias-corrected · heatwave-preserving morph · UWG urban Δ") and a
  methodology link in the map popup.

### Fixed
- Map overlay panel moved inside the map canvas — it no longer overlaps the
  sidebar; added collapse/expand toggle.
- Clean keyless **Light (Esri)** basemap added; OSM relabeled as "busy" to
  set expectations about its POI clutter.

### Infrastructure
- GitHub Actions **publish workflow**: every `v*` tag (or manual dispatch)
  builds the image and pushes it to `ghcr.io/alirezza18/urban-future-weather-engine`
  (`latest`, semver and major.minor tags), then smoke-tests the published image.

## [1.3.0] — 2026-09-25

### Added
- **Download-first site card**: primary **Download EPW** button, per-scenario
  EPW links, one-click all-eras `.zip` bundle, stat chips (CDD18, HDD18,
  hot hours > 32 °C, frost hours).
- **Direct-download map popups**: clicking any site shows immediate EPW links
  for every available era plus the bundle zip; unavailable eras render as
  disabled entries instead of broken links.
- **Multi-variable monthly charts** per site: temperature, dew point, RH,
  global horizontal radiation, wind speed — all three eras overlaid, with
  variable picker buttons.
- **City-wide factor overlay**: color sites by Δ temperature, Δ cooling
  degree days, Δ humidity, Δ radiation or Δ wind, each on an appropriate
  (diverging where negative values matter) color scale with legend.
- Warming precompute extended to all five variables (`ufwe-warming-v4` cache),
  with per-site Δ arrays and `delta_vars` metadata in `/api/warming`.

### Changed
- Parser upgraded to multi-variable aggregation (single bulk read retained);
  degree days now correctly computed as hourly-deviation sum / 24.

## [1.2.0] — 2026-09-25

### Added
- **Download ladder**: single EPW → per-site bundle.zip → per-scenario
  all-sites zips (251 / 234 / 236 MB) → full-corpus zip (721 MB), served
  with HTTP range support (resumable).
- Precomputed zip artifacts built once in a background thread with
  atomic-rename publication and lock-file status reporting.

## [1.1.0] — 2026-09-25

### Fixed
- Broken CARTO basemap (API-key wall) replaced with keyless **Esri Dark
  Gray** default; OSM streets and Esri satellite selectable; "no basemap"
  option added.

### Added
- Site search (id or "lat,lon") with `#site=ID` deep links.
- ΔT histogram, data-quality panel (corrupt/missing sites surfaced, never
  hidden), convex-hull domain outline, `GET /api/sites.geojson`,
  `GET /api/quality`, `GET /api/downloads`.

## [1.0.0] — 2026-09-25

### Added
- Initial release: FastAPI + Leaflet/Chart.js single-page explorer for the
  1,013-site Madrid morphed-EPW corpus (historical / mid-century / 2084).
- One-pass background warming precompute cached to `/cache`; idempotent
  corpus sync into a local volume (9p-safe single-syscall reads).
- Dark control-room UI, per-site climate cards, warming overlay.
