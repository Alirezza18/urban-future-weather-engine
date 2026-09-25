"""API tests: every endpoint against a synthetic mini-corpus.

Run with:  pytest tests/ -v
No Docker, no real corpus needed — conftest.py builds a tiny one.
"""
import csv
import io
import zipfile

# --------------------------------------------------------------- health ----


def test_healthz_ready(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["warming_ready"] is True
    assert body["done"] == body["total"] == 3


# ---------------------------------------------------------------- sites ----


def test_sites_catalogue(client):
    r = client.get("/api/sites")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    ids = [s["id"] for s in body["sites"]]
    assert ids == [0, 1, 2]
    assert all(set(s) == {"id", "lat", "lon"} for s in body["sites"])


def test_sites_geojson(client):
    r = client.get("/api/sites.geojson")
    assert r.status_code == 200
    gj = r.json()
    assert gj["type"] == "FeatureCollection"
    assert len(gj["features"]) == 3
    feat = gj["features"][0]
    assert feat["geometry"]["type"] == "Point"
    assert feat["properties"]["site_id"] == 0


# ------------------------------------------------------------ site card ----


def test_site_detail_all_scenarios(client):
    r = client.get("/api/site/0")
    assert r.status_code == 200
    body = r.json()
    assert body["site"]["lat"] == 40.4691
    scens = {s["scenario"]: s for s in body["scenarios"]}
    assert set(scens) == {"historical", "midfuture", "future2084"}
    # synthetic corpus: midfuture is 3 degC warmer than historical
    assert scens["midfuture"]["mean_db"] - scens["historical"]["mean_db"] == 3.0
    assert scens["historical"]["cdd18"] > 0
    assert "means" in scens["historical"] and "monthly" in scens["historical"]


def test_site_detail_missing_midfuture_reported(client):
    """Site 2 has no midfuture file: reported as unavailable, not 500."""
    r = client.get("/api/site/2")
    assert r.status_code == 200
    scens = {s["scenario"]: s for s in r.json()["scenarios"]}
    assert "error" in scens["midfuture"]
    assert "error" not in scens["historical"]
    assert "error" not in scens["future2084"]


def test_site_detail_unknown_id_404(client):
    assert client.get("/api/site/999").status_code == 404


# -------------------------------------------------------------- warming ----


def test_warming_deltas(client):
    r = client.get("/api/warming")
    assert r.status_code == 200
    body = r.json()
    assert body["n_sites"] == 3
    assert set(body["delta_vars"]) == {"temp", "rh", "rad", "wind", "cdd"}
    mf = body["scenarios"]["midfuture"]
    temps = {d["id"]: d["delta"] for d in mf["deltas"]["temp"]}
    # site 2 absent from midfuture -> not in the delta map
    assert set(temps) == {0, 1}
    assert temps[0] == 3.0          # 18.0 vs 15.0
    assert body["unavailable"]["historical"] == []
    assert body["unavailable"]["midfuture"] == [2]


# ------------------------------------------------------------- quality ----


def test_quality_counts(client):
    r = client.get("/api/quality")
    assert r.status_code == 200
    q = r.json()
    assert q["status"] == "ok"
    scens = q["scenarios"]
    assert scens["historical"]["available"] == 3
    assert scens["midfuture"]["available"] == 2
    assert scens["midfuture"]["unavailable"] == [2]
    assert scens["future2084"]["unavailable"] == []


# ----------------------------------------------------------------- epw ----


def test_single_epw_download(client):
    r = client.get("/api/epw/historical/0")
    assert r.status_code == 200
    assert r.headers["content-disposition"].endswith('0.epw"')
    text = r.content.decode("latin-1")
    assert text.startswith("LOCATION,MADRID_TEST")
    assert len(text.splitlines()) == 8 + 8760


def test_epw_fallback_naming(client):
    """Site 1 midfuture is only present as 1.epw (no _updated suffix)."""
    assert client.get("/api/epw/midfuture/1").status_code == 200


def test_epw_unknown_scenario_404(client):
    assert client.get("/api/epw/2050/0").status_code == 404


# -------------------------------------------------------------- bundle ----


def test_site_bundle_zip(client):
    r = client.get("/api/site/1/bundle.zip")
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert any(n.startswith("site_1/historical__") for n in names)
    assert any(n.startswith("site_1/midfuture__") for n in names)
    assert any(n.startswith("site_1/future2084__") for n in names)


def test_site_bundle_404(client):
    assert client.get("/api/site/999/bundle.zip").status_code == 404


# ----------------------------------------------------------- downloads ----


def test_downloads_index(client):
    r = client.get("/api/downloads")
    assert r.status_code == 200
    arts = {a["name"]: a["state"] for a in r.json()["artifacts"]}
    assert len(arts) == 4
    assert all(s in {"ready", "building", "pending"} for s in arts.values())


def test_ui_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Urban-Future-Weather Engine" in r.text
