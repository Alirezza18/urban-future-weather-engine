"""Unit tests for the EPW parser (no HTTP layer involved)."""
from app.epw import read_location_header, summarize_epw

from conftest import make_epw


def _write(tmp_path, name="test.epw", **overrides):
    path = tmp_path / name
    make_epw(path, **overrides)
    return path


def test_header_parsing(tmp_path):
    path = _write(tmp_path, city="TESTCITY", lat=40.47, lon=-3.64, elev=610.0)
    loc = read_location_header(path)
    assert loc["city"] == "TESTCITY"
    assert loc["lat"] == 40.47
    assert loc["lon"] == -3.64
    assert loc["elev_m"] == 610.0


def test_row_count_and_period(tmp_path):
    path = _write(tmp_path)
    s = summarize_epw(path, 0, "test", "#38bdf8")
    assert len(s.monthly_db) == 12
    assert all(m is not None for m in s.monthly_db)
    # diurnal cycle peaks 6 degC above the monthly floor
    assert s.tmax_db - s.tmin_db > 5.0


def test_degree_days(tmp_path):
    """base +6 diurnal over base=18.0 -> only cooling hours exist."""
    path = _write(tmp_path, base=18.0)
    s = summarize_epw(path, 0, "test", "#38bdf8")
    # daily cooling-hour sum = 0.6 * sum((h-5) mod 24) = 165.6 degCh
    assert abs(s.cdd18 - round(165.6 * 365 / 24)) <= 1
    assert s.hdd18 == 0.0
    assert s.frost_hours_0 == 0


def test_frost_and_hot_hours(tmp_path):
    path = _write(tmp_path, base=33.0)          # always >= 33 > 32
    s = summarize_epw(path, 0, "test", "#38bdf8")
    assert s.hot_hours_32 == 8760
    path2 = _write(tmp_path, "cold.epw", base=-2.0)
    s2 = summarize_epw(path2, 0, "test", "#38bdf8")
    # T < 0 while (h-5) mod 24 < 4 -> 4 h/day -> 1460 h/yr
    assert s2.frost_hours_0 == 1460
    assert s2.tmax_db == 11.8   # -2 + 6*(19 mod 24)/10
    assert s2.tmin_db == -2.0


def test_means_all_variables(tmp_path):
    path = _write(tmp_path, rh=55.0, wind=2.5, rad=180.0)
    s = summarize_epw(path, 0, "test", "#38bdf8")
    assert s.means["rh"] == 55.0
    assert s.means["wind"] == 2.5
    assert s.means["glohorz"] == 180.0
    assert set(s.monthly) == {"temp", "dewpoint", "rh", "glohorz", "wind"}


def test_sentinel_and_garbage_rows_skipped(tmp_path):
    path = _write(tmp_path, rad=0.0)
    text = path.read_text(encoding="latin-1").splitlines()
    # inject sentinel radiation + a garbage row
    text[100] = text[100].replace(",0.0,", ",999999,", 1)
    text[101] = "1983,13,32,25,1,X,bad,bad,bad,0,0,0,0,0,0,0,0,0,0,0,0,0"
    path.write_text("\n".join(text) + "\n", encoding="latin-1")
    s = summarize_epw(path, 0, "test", "#38bdf8")
    assert s.means["glohorz"] == 0.0        # sentinel 999999 excluded
    assert s.means["temp"] > 10             # garbage row didn't corrupt


def test_all_sentinel_file_raises(tmp_path):
    path = _write(tmp_path)
    lines = path.read_text(encoding="latin-1").splitlines()
    header = lines[0]
    body = ["1983,1,1,1,1,1,Monday,99.9,99.9,99.9,0,0,0,0,99.9,0,0,0,0,0,0,0"] * 8760
    path.write_text("\n".join([header] + body) + "\n", encoding="latin-1")
    try:
        summarize_epw(path, 0, "test", "#38bdf8")
        raised = False
    except ValueError:
        raised = True
    assert raised
