"""Tests for the coverage-audit service.

The regression test on the degradation curve matters most: it pins the numbers
measured on 2026-11-19 so that a later refactor cannot quietly change the
science while the API still looks fine.
"""
import io
from itertools import pairwise

import pytest
from fastapi.testclient import TestClient

from app.clocks import catalogue
from app.degradation import FULL_SD, MEASURED, retained_signal
from app.main import app

client = TestClient(app)
HORVATH = sorted(catalogue()["clocks"]["Horvathv1"]["site_set"])


# --- the science, pinned ----------------------------------------------------

@pytest.mark.parametrize("coverage,sd", MEASURED)
def test_curve_reproduces_measured_points(coverage, sd):
    """Every measured point must come back out of the interpolation."""
    expected = min(1.0, sd / FULL_SD)
    assert retained_signal(coverage) == pytest.approx(expected, abs=1e-6)


def test_curve_is_monotonic():
    xs = [i / 200 for i in range(201)]
    ys = [retained_signal(x) for x in xs]
    assert all(b >= a - 1e-9 for a, b in pairwise(ys)), "signal must not rise as coverage falls"


def test_curve_bounds():
    assert retained_signal(0) == 0.0
    assert retained_signal(1) == 1.0
    assert retained_signal(-5) == 0.0
    assert retained_signal(99) == 1.0


# --- ops -------------------------------------------------------------------

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    b = r.json()
    assert b["status"] == "ok"
    assert b["clock_count"] > 0
    assert "biolearn" in b["libraries"]


def test_clocks_catalogue():
    r = client.get("/clocks")
    assert r.status_code == 200
    cl = r.json()["clocks"]
    assert len(cl) > 40
    h = next(c for c in cl if c["clock"] == "Horvathv1")
    assert h["required_sites"] == 353


# --- audit, the happy and the unhappy --------------------------------------

def test_full_coverage_is_ok():
    r = client.post("/audit", json={"cpgs": HORVATH, "clocks": ["Horvathv1"]})
    assert r.status_code == 200
    res = r.json()["results"][0]
    assert res["present_sites"] == 353
    assert res["coverage"] == 1.0
    assert res["retained_signal"] == 1.0
    assert res["verdict"] == "ok"


def test_partial_coverage_degrades():
    r = client.post("/audit", json={"cpgs": HORVATH[:106], "clocks": ["Horvathv1"]})
    res = r.json()["results"][0]
    assert res["present_sites"] == 106
    assert res["coverage"] == pytest.approx(0.3003, abs=1e-3)
    assert res["verdict"] == "degraded"
    assert 0.70 < res["retained_signal"] < 0.73


def test_tiny_coverage_is_unusable():
    r = client.post("/audit", json={"cpgs": HORVATH[:1], "clocks": ["Horvathv1"]})
    res = r.json()["results"][0]
    assert res["verdict"] == "unusable"
    assert res["retained_signal"] < 0.05


def test_zero_overlap_is_refused():
    """The case biolearn answers with a confident number and pyaging refuses."""
    r = client.post("/audit", json={"cpgs": ["cg99999999", "notacpg"], "clocks": ["Horvathv1"]})
    res = r.json()["results"][0]
    assert res["present_sites"] == 0
    assert res["verdict"] == "refuse"
    assert "biolearn" in res["note"]


def test_every_clock_reported_when_unfiltered():
    r = client.post("/audit", json={"cpgs": HORVATH})
    b = r.json()
    assert len(b["results"]) > 40
    assert sum(b["tally"].values()) == len(b["results"])


def test_results_sorted_by_coverage_desc():
    r = client.post("/audit", json={"cpgs": HORVATH})
    covs = [x["coverage"] for x in r.json()["results"]]
    assert covs == sorted(covs, reverse=True)


def test_caveat_is_always_present():
    """The honesty of the response is part of the contract, so it is tested."""
    r = client.post("/audit", json={"cpgs": HORVATH})
    b = r.json()
    assert "extrapolation" in b["caveat"]
    assert "rule of thumb" in b["caveat"]
    assert "2026-11-19" in b["measured_on"]


def test_duplicates_do_not_inflate_coverage():
    r = client.post("/audit", json={"cpgs": HORVATH[:50] * 3, "clocks": ["Horvathv1"]})
    assert r.json()["results"][0]["present_sites"] == 50


def test_whitespace_is_trimmed():
    r = client.post("/audit", json={"cpgs": [f"  {c}  " for c in HORVATH[:10]], "clocks": ["Horvathv1"]})
    assert r.json()["results"][0]["present_sites"] == 10


# --- input validation ------------------------------------------------------

def test_empty_list_rejected():
    assert client.post("/audit", json={"cpgs": []}).status_code == 422


def test_only_blanks_rejected():
    assert client.post("/audit", json={"cpgs": ["", "  "]}).status_code == 422


def test_unknown_clock_rejected():
    r = client.post("/audit", json={"cpgs": HORVATH, "clocks": ["NoSuchClock"]})
    assert r.status_code == 422
    assert "unknown clock" in r.text


def test_platform_guess_recognises_27k():
    cl = catalogue()["clocks"]
    pool = sorted(set().union(*(c["site_set"] for c in cl.values())))[:27_578]
    r = client.post("/audit", json={"cpgs": pool, "clocks": ["Horvathv1"]})
    assert r.json()["input"]["platform_guess"] == "Illumina 27k"


def test_unrecognised_ids_are_counted():
    r = client.post("/audit", json={"cpgs": [*HORVATH[:10], "junk1", "junk2"], "clocks": ["Horvathv1"]})
    inp = r.json()["input"]
    assert inp["ids_distinct"] == 12
    assert inp["ids_recognised"] == 10
    assert inp["ids_unrecognised"] == 2


# --- csv upload ------------------------------------------------------------

def _csv(rows, header="cpg,sample1\n"):
    return io.BytesIO((header + "".join(rows)).encode())


def test_csv_upload():
    body = _csv([f"{c},0.5\n" for c in HORVATH])
    r = client.post("/audit/csv", files={"file": ("m.csv", body, "text/csv")})
    assert r.status_code == 200
    assert next(x for x in r.json()["results"] if x["clock"] == "Horvathv1")["coverage"] == 1.0


def test_csv_tab_separated():
    body = _csv([f"{c}\t0.5\n" for c in HORVATH[:20]], header="cpg\tsample1\n")
    r = client.post("/audit/csv", files={"file": ("m.tsv", body, "text/tab-separated-values")})
    assert r.status_code == 200
    assert next(x for x in r.json()["results"] if x["clock"] == "Horvathv1")["present_sites"] == 20


def test_csv_wrong_column_gives_a_useful_error():
    body = _csv([f"{c},0.5\n" for c in HORVATH[:5]])
    r = client.post("/audit/csv?column=1", files={"file": ("m.csv", body, "text/csv")})
    # column 1 holds values, not ids: parsed but nothing recognised
    assert r.status_code == 200
    assert r.json()["input"]["ids_recognised"] == 0


def test_csv_empty_rejected():
    r = client.post("/audit/csv", files={"file": ("m.csv", io.BytesIO(b"cpg,v\n"), "text/csv")})
    assert r.status_code == 422


def test_csv_not_utf8_rejected():
    r = client.post("/audit/csv", files={"file": ("m.csv", io.BytesIO(b"\xff\xfe\x00bad"), "text/csv")})
    assert r.status_code == 415
