# clock-audit

Does your methylation array carry the CpG sites an ageing clock needs? Find out
before you trust the age it gives you.

## The problem

An epigenetic clock is a weighted sum over a fixed set of CpG sites — Horvath
2013 uses 353 of them. If your array does not carry those sites, the two common
Python libraries do not stop. They fill the gaps from reference-cohort medians
and return a plausible age anyway.

Measured on 2026-11-26 on two real cohorts - GSE40279 (656 people) and
GSE50660 (464) - across 19 published clocks. Earlier the curve came from one
clock over 24
samples, through **biolearn 0.9.1** and **pyaging 0.6.2**:

| sites present of 353 | library said anything? | predicted ages | spread (sd) |
|---|---|---|---|
| 353 | — | 15.4–96.9 | 18.05 |
| 106 | biolearn: no · pyaging: yes | 20.2–81.0 | 12.85 |
| 17 | biolearn: no · pyaging: yes | 33.1–50.1 | 3.72 |
| 1 | biolearn: no · pyaging: yes | 37.8–38.9 | 0.33 |
| 0 | biolearn: no · pyaging: **error** | biolearn: 38.5 for all 24 | 0.00 |

Two things to take from that table.

**biolearn never warns.** With zero of the 353 required sites it still returns
38.5 years, for everybody, silently. That is a scale reading 70 kg with nothing
on it.

**The failure is not a crash, it is a collapse.** As coverage falls, the spread
between people falls with it. The clock stops measuring the person and starts
reporting the filler, and the number stays in a believable range the whole way
down. pyaging warns, which is the right thing to do — but the number it returns
at 95% missing is no better than biolearn's.

## What this service does

Give it the CpG identifiers your dataset carries. It reports, per clock, how
many of the required sites you actually have and how much between-person signal
survives at that coverage.

It takes **identifiers only, never methylation values**. No measurement and
nothing identifying a person crosses the wire.

```bash
curl -s localhost:8080/audit \
  -H 'content-type: application/json' \
  -d '{"cpgs": ["cg00000029", "cg00000108"], "clocks": ["Horvathv1"]}'
```

```json
{
  "clock": "Horvathv1",
  "required_sites": 353,
  "present_sites": 2,
  "coverage": 0.0057,
  "retained_signal": 0.034,
  "verdict": "unusable",
  "note": "Predictions are driven by the filler values, not by this sample."
}
```

| endpoint | what it does |
|---|---|
| `GET /health` | liveness, library versions, clock count |
| `GET /clocks` | the catalogue: 59 clocks and how many sites each needs |
| `POST /audit` | coverage per clock, from a list of CpG ids |
| `POST /audit/csv` | the same, from a CSV or TSV whose first column holds ids |
| `GET /docs` | OpenAPI browser |

## Honesty about the numbers

`retained_signal` and `expected_shift_years` are the **median of 19 published
clocks** on two real cohorts, not a prediction for any one clock. Per-clock
robustness does **not** replicate between those cohorts (rank correlation -0.39
to +0.43, never significant at any coverage level), so this tool gives one
population expectation instead of ranking clocks. Dropout was random; real
missingness is not, and the one real mask here is the 27k platform scenario.
Every API response says so in its
`caveat` field.

The verdict bands (`ok` / `caution` / `degraded` / `unusable`) are this tool's
rule of thumb. **No minimum coverage is published** for these clocks — not in
Horvath 2013, and not anywhere else we found. Treat `coverage`, which is a
fact, more seriously than `verdict`, which is a judgement.

## Running it

```bash
pip install -r requirements-dev.txt
pytest                                   # 31 tests
uvicorn app.main:app --reload --port 8080
```

With Docker:

```bash
docker build -t clock-audit .
docker run --rm -p 8080:8080 clock-audit
```

The build has two stages. The first installs biolearn — which pulls torch and
most of the scientific stack, about 3 GB — purely to extract the list of CpG
sites each clock requires. The runtime image keeps the resulting 1.5 MB file
and none of the libraries. CI asserts the runtime image stays under 600 MB, so
that separation cannot rot unnoticed.

## The clock catalogue

`app/clocks.json.gz` holds 59 clocks and 454,290 distinct CpG ids, extracted
from biolearn. It is committed because the tests need it and regenerating costs
a 3 GB install. To rebuild it:

```bash
pip install -r requirements-build.txt
python scripts/extract_clocks.py && gzip -9 app/clocks.json
```

## Layout

```
app/degradation.py   the measured curve, and what the bands mean
app/clocks.py        loads the catalogue
app/main.py          the API
scripts/             catalogue extraction (build-time only)
tests/               31 tests; the first three pin the measured numbers
```

The tests on the degradation curve exist so that a later refactor cannot quietly
change the science while the API still looks healthy.
