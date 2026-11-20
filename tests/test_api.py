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
    assert b["model_count"] > 0
    assert "biolearn" in b["catalogue_from"]


def test_a_library_is_named_a_source_only_if_it_put_models_here():
    """The defect this pins: the service listed pyaging beside biolearn while
    every model in the catalogue came from biolearn. A version number is not a
    contribution, and the page said otherwise for a whole day."""
    b = client.get("/health").json()
    libs = {c["library"] for c in client.get("/clocks").json()["clocks"]}
    assert set(b["catalogue_from"]) == libs
    assert not (set(b.get("installed_but_contributed_nothing", {})) & libs)


def test_counts_add_up_and_age_clocks_are_not_the_whole_catalogue():
    b = client.get("/health").json()
    assert sum(b["models_by_kind"].values()) == b["model_count"]
    assert b["age_clock_count"] == b["models_by_kind"]["age"]
    # Most of the gallery predicts something other than age; saying "N ageing
    # clocks" about the whole catalogue overstates it by more than double.
    assert b["age_clock_count"] < b["model_count"]
    # One sex predictor needs nearly the whole array, so the all-models site
    # count says little about ageing clocks. Keep both, never just the big one.
    assert b["distinct_sites_age_clocks"] < b["distinct_sites_all_models"]


def test_gestational_clocks_are_not_filed_as_age_clocks():
    """Knight, Mayne and the Lee clocks read newborns. Horvath's cord-blood
    neighbour Bohlin even reports "Age (days)", so output text alone is not
    enough - tissue has to be read too."""
    rows = {c["clock"]: c["kind"] for c in client.get("/clocks").json()["clocks"]}
    for name in ("Knight", "Mayne", "Bohlin", "LeeControl"):
        assert rows[name] == "gestational", (name, rows[name])
    assert rows["Horvathv1"] == "age"


def test_clocks_catalogue():
    r = client.get("/clocks")
    assert r.status_code == 200
    cl = r.json()["clocks"]
    assert len(cl) > 40
    h = next(c for c in cl if c["clock"] == "Horvathv1")
    assert h["required_sites"] == 353


def test_clocks_can_be_filtered_by_kind():
    r = client.get("/clocks", params={"kind": "age"})
    assert r.status_code == 200
    body = r.json()
    assert body["clocks"] and all(c["kind"] == "age" for c in body["clocks"])
    assert len(body["clocks"]) == body["age_clock_count"]
    assert client.get("/clocks", params={"kind": "banana"}).status_code == 400


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


# --- the page a person actually opens --------------------------------------

def test_index_is_a_page_not_json():
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<!doctype html>" in r.text
    # Self-contained: a Lambda container has no business fetching a CDN, and an
    # offline viewer should still get the whole page.
    assert "http://" not in r.text and "https://" not in r.text


def test_one_clock_carries_its_sites():
    b = client.get("/clocks/Horvathv1").json()
    assert b["required_sites"] == 353 and len(b["sites"]) == 353
    assert b["kind"] == "age"
    assert client.get("/clocks/NoSuchClock").status_code == 404


def test_a_huge_model_does_not_dump_its_sites_inline():
    b = client.get("/clocks/SexEstimation").json()
    assert "sites" not in b and "sites_omitted" in b
