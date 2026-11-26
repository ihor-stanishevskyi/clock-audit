"""Tests for the coverage-audit service.

The regression test on the degradation curve matters most: it pins the numbers
measured on 2026-11-19 so that a later refactor cannot quietly change the
science while the API still looks fine.
"""
import io
import pathlib
import re
from itertools import pairwise

import pytest
from fastapi.testclient import TestClient

from app.clocks import catalogue
from app.degradation import RETAINED, SHIFT_YEARS, retained_signal, shift_years
from app.main import app

client = TestClient(app)
HORVATH = sorted(catalogue()["clocks"]["Horvathv1"]["site_set"])


# --- the science, pinned ----------------------------------------------------

@pytest.mark.parametrize("coverage,pair", RETAINED)
def test_curve_reproduces_measured_points(coverage, pair):
    """Every measured point must come back out of the interpolation. The curve
    reports the worse of the two cohorts, so that is what must come back."""
    assert retained_signal(coverage) == pytest.approx(min(pair), abs=1e-6)


@pytest.mark.parametrize("coverage,pair", SHIFT_YEARS)
def test_shift_reproduces_measured_points(coverage, pair):
    """Same for the shift table, which reports the larger of the two."""
    assert shift_years(coverage) == pytest.approx(max(pair), abs=1e-6)


def test_shift_falls_as_coverage_rises():
    xs = [i / 200 for i in range(201)]
    ys = [shift_years(x) for x in xs]
    assert all(b <= a + 1e-9 for a, b in pairwise(ys)), "shift must not grow as coverage rises"


def test_ten_percent_loss_is_the_size_of_a_real_effect():
    """The number that makes this tool worth running: losing a tenth of the
    probes moves the median clock about as far as smoking does (+2.70 years on
    PhenoAge, measured on GSE50660). If a refresh ever makes this benign, the
    curve changed and the page's warning no longer matches it."""
    assert 2.0 < shift_years(0.90) < 3.5


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
    # Measured on real cohorts this is worse than the old single-clock curve
    # said: 0.37 of the spread survives at 30% coverage, not 0.71.
    assert res["verdict"] == "unusable"
    assert 0.33 < res["retained_signal"] < 0.42
    assert res["expected_shift_years"] > 10


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


def test_results_sorted_by_the_coverage_the_verdict_used():
    """Sorted on the figure the verdict came from, not on the flattering one.

    A clock that normalises against a larger probe set can top the table on its
    own coefficients while being unusable, which is exactly the row a reader
    needs to see first rather than last.
    """
    r = client.post("/audit", json={"cpgs": HORVATH})
    covs = [x["effective_coverage"] for x in r.json()["results"]]
    assert covs == sorted(covs, reverse=True)


def test_caveat_is_always_present():
    """The honesty of the response is part of the contract, so it is tested."""
    r = client.post("/audit", json={"cpgs": HORVATH})
    b = r.json()
    assert "rule of thumb" in b["caveat"]
    assert "does not replicate" in b["caveat"]
    # measured_on must name the cohorts the curve actually came from, so a
    # stale curve cannot hide behind a fresh-looking response.
    assert "GSE40279" in b["measured_on"] and "GSE50660" in b["measured_on"]
    assert "2026-11-26" in b["measured_on"]


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


def test_health_carries_the_caveat_so_the_page_can_show_it_unprompted():
    """The block headed "what this cannot tell you" sat on "loading" until
    someone ran an audit - which is exactly the reader who had not yet been
    warned. The limits ship with the status, not with the answer."""
    c = client.get("/health").json()["caveat"]
    # The words change as the measurement improves; what must not disappear is
    # that the caveat still names its three live limits.
    assert "rule of thumb" in c, "the bands are still a judgement call"
    assert "does not replicate" in c, "per-clock ranking is not supported"
    assert "random" in c, "dropout was random; real missingness is not"


# --- what an array carries -------------------------------------------------

def test_platforms_are_listed_with_their_real_sizes():
    ps = client.get("/platforms").json()["platforms"]
    assert len(ps) >= 3
    for p in ps:
        # The builder refuses a parse more than 2% off the published size; this
        # keeps that promise visible from the outside too.
        assert abs(p["probes"] - p["published_probes"]) / p["published_probes"] < 0.02
        assert p["accession"].startswith("GPL")


def test_27k_reproduces_what_we_measured_on_real_data():
    """On 2026-11-08 we ran these clocks over GSE19711 - 540 real samples on a
    27k array - and read the coverage off the data. This table is built the
    other way round, from the array manifest, and lands on the same numbers.
    Two independent routes agreeing is the reason to trust either."""
    r = {x["clock"]: x for x in
         client.get("/audit/platform/GPL8490", params={"kind": "age"}).json()["results"]}
    assert r["Horvathv1"]["coverage"] == 1.0            # measured then: 100%
    assert abs(r["Horvathv2"]["coverage"] - 0.279) < 0.01   # measured then: 27.9%
    assert abs(r["Hannum"]["coverage"] - 0.10) < 0.02       # measured then: 10.1%
    assert abs(r["DunedinPACE"]["coverage"] - 0.035) < 0.01  # measured then: 3.5%
    assert r["Horvathv2"]["verdict"] in ("degraded", "unusable")


def test_a_newer_array_is_not_strictly_better():
    """EPIC v1 dropped tens of thousands of probes 450k carried, so clocks
    built on 450k can lose sites on the newer chip. Worth a test: the
    assumption that newer means safer is the kind that costs an analysis."""
    def full(acc):
        rs = client.get(f"/audit/platform/{acc}").json()["results"]
        return sum(1 for x in rs if x["coverage"] == 1.0)
    assert full("GPL21145") < full("GPL13534")


def test_unknown_platform_says_so():
    assert client.get("/audit/platform/GPL9999").status_code == 404
    assert client.get("/audit/platform/GPL8490", params={"kind": "banana"}).status_code == 400


def test_the_array_answer_needs_no_data_and_says_so():
    b = client.get("/audit/platform/GPL8490").json()
    assert "input" not in b           # nothing was supplied, and none is implied
    assert b["platform"]["label"] and b["caveat"]


# --- a clock may need more than its coefficients ----------------------------
#
# DunedinPACE carries 173 weighted sites and quantile-normalises against 20,000
# probes first, filling whatever is absent from reference values. The service
# published 173 as the requirement for five days. These tests exist so that
# cannot come back.

NORMALISING = [n for n, c in catalogue()["clocks"].items() if c.get("norm_set")]


def test_the_catalogue_knows_which_clocks_need_more_than_their_coefficients():
    assert "DunedinPACE" in NORMALISING, (
        "DunedinPACE normalises against a 20,000-probe gold standard; if the "
        "catalogue has lost that, every coverage figure for it is overstated")
    c = catalogue()["clocks"]["DunedinPACE"]
    assert c["n_normalisation_sites"] > 10 * c["n_sites"]
    assert len(c["norm_set"]) == c["n_normalisation_sites"]


def test_the_extra_requirement_is_published_not_hidden():
    b = client.get("/clocks/DunedinPACE").json()
    assert b["normalisation_sites"] == len(catalogue()["clocks"]["DunedinPACE"]["norm_set"])
    assert b["normalisation_source"]
    assert str(b["required_sites"]) in b["normalisation_means"]
    assert str(b["normalisation_sites"]) in b["normalisation_means"]


@pytest.mark.parametrize("name", NORMALISING)
def test_full_coefficient_coverage_is_not_enough_to_pass(name):
    """Every coefficient present, little of the normalisation set: not "ok".

    This is the failure the old code shipped. Coverage read 100% and the
    verdict read "ok", while the answer was built from reference values.
    """
    c = catalogue()["clocks"][name]
    ids = sorted(c["site_set"]) + sorted(c["norm_set"])[: len(c["norm_set"]) // 10]
    r = client.post("/audit", json={"cpgs": ids, "clocks": [name]}).json()["results"][0]
    assert r["coverage"] == 1.0, "the coefficients were all supplied"
    assert r["normalisation_coverage"] < 0.5
    assert r["effective_coverage"] == r["normalisation_coverage"]
    assert r["verdict"] != "ok"
    assert "verdict follows the lower figure" in r["normalisation_note"]


@pytest.mark.parametrize("name", NORMALISING)
def test_both_sets_present_passes(name):
    """The control: supply everything and the clock is fine. Otherwise the test
    above would pass for a service that simply condemned this clock always."""
    c = catalogue()["clocks"][name]
    ids = sorted(c["site_set"] | c["norm_set"])
    r = client.post("/audit", json={"cpgs": ids, "clocks": [name]}).json()["results"][0]
    assert r["coverage"] == 1.0
    assert r["normalisation_coverage"] == 1.0
    assert r["verdict"] == "ok"


def test_unmeasured_normalisation_coverage_is_stated_not_assumed(monkeypatch):
    """A platform table built before this field existed must not be read as zero.

    Reporting zero would condemn the clock on no evidence - the mirror of the
    overstatement being fixed - and reporting nothing would let the flattering
    number stand unqualified. It has to say which it is.
    """
    monkeypatch.setattr("app.main.present_normalisation", lambda acc: {})
    b = client.get("/audit/platform/GPL13534?kind=age").json()
    rows = {r["clock"]: r for r in b["results"]}
    for name in NORMALISING:
        if name not in rows:
            continue
        r = rows[name]
        assert r["normalisation_coverage"] is None
        assert "not been measured" in r["normalisation_note"]
        assert "upper bound" in r["normalisation_note"]
        assert "normalisation_present" not in r


# --- the page cannot claim more than the API returns ------------------------

def test_the_page_reads_only_fields_a_response_actually_has():
    """Every r.<field> the script touches must exist in some result row.

    The page once read a field the API had renamed and threw on every load
    while every test passed, because no test looked at the page.
    """
    import re

    from app.page import PAGE

    ids = sorted(catalogue()["clocks"]["DunedinPACE"]["norm_set"]) + HORVATH
    rows = client.post("/audit", json={"cpgs": ids}).json()["results"]
    available = set().union(*(set(r) for r in rows))
    read = set(re.findall(r"\br\.([a-z_]+)\b", PAGE))
    assert read, "the pattern stopped matching; fix the test, not the page"
    assert read <= available, f"page reads fields no response carries: {sorted(read - available)}"


def test_the_page_shows_the_coverage_the_verdict_used():
    from app.page import PAGE

    assert "effective_coverage" in PAGE, (
        "the table must not show coefficient coverage beside a verdict reached "
        "on a lower figure - that reads as a bug in the table")
    assert "normalisation probes" in PAGE


def test_the_extractor_refuses_to_ship_an_unrecorded_preprocessing_set():
    """The tripwire, checked as text because the extractor needs biolearn.

    If a later biolearn gives another clock a preprocessing step, the build must
    fail rather than publish an understated requirement for it.
    """
    src = pathlib.Path("scripts/extract_clocks.py").read_text(encoding="utf-8")
    assert "PREPROCESS_SETS" in src
    assert "DunedinPACE_Gold_Means.csv" in src
    assert "unaccounted" in src and "sys.exit" in src

def test_table_header_and_row_have_the_same_number_of_columns():
    """A column was once added to the row and not to the header, which silently
    shifts every cell. Count both in the served page rather than trusting the
    eye: the row template is one template literal, so its cells are countable."""
    page = client.get("/").text
    head = re.search(r"<thead>.*?</thead>", page, re.S)
    assert head, "no table header in the page"
    # "<th" also matches "<thead", which is how this test first miscounted.
    n_head = len(re.findall(r"<th[\s>]", head.group(0)))
    body = re.search(r"return `<tr>(.*?)</tr>`", page, re.S)
    assert body, "no row template in the page"
    n_row = len(re.findall(r"<td[\s>]", body.group(1)))
    assert n_head == n_row, f"{n_head} headers against {n_row} cells per row"


def test_law_agrees_with_the_measured_table():
    """Two descriptions of one experiment must not drift apart.

    retained = coverage ** 0.728 (project doc 44) against the measured medians in
    RETAINED. This catches GROSS drift: a table rewritten against a different
    experiment, or an exponent edited without the table.

    What it does NOT catch, checked rather than assumed: the GrimAge inflation
    corrected on 2026-11-26. Those values sat 0.022-0.029 off, and the largest
    LEGITIMATE gap between law and table is 0.085 (at 50% coverage, GSE40279), so
    no tolerance can pass the right table and fail that one. The regression pin in
    test_covariate_readers_are_not_in_the_retained_table is what guards that case.
    Found by putting the defect back and watching only one of the two tests fail.
    """
    from app.degradation import RETAINED, LAW_EXPONENT, LAW_MEDIAN_TOLERANCE
    for coverage, pair in RETAINED:
        if coverage in (0.0, 1.0):
            continue
        law = coverage ** LAW_EXPONENT
        for measured in pair:
            assert abs(law - measured) <= LAW_MEDIAN_TOLERANCE, (
                f"at {coverage:.0%} coverage the law gives {law:.3f} but the "
                f"table says {measured:.3f}")


def test_covariate_readers_are_not_in_the_retained_table():
    """A regression pin on the correction of 2026-11-26.

    GrimAge V1/V2 are handed chronological age and sex, so at 5% coverage they
    still keep ~0.8 of their spread. With them in, the median retained at 5% read
    0.123/0.171; without them it is 0.099/0.149. If a future edit puts them back,
    the table drifts optimistic and this catches it.
    """
    from app.degradation import RETAINED
    at_five = dict(RETAINED)[0.05]
    assert at_five == (0.099, 0.149), f"5% row is {at_five}, expected the 17-clock medians"
    assert max(at_five) < 0.20, "a row this high means covariate readers are back in"
