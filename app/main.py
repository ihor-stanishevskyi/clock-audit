"""Coverage audit for DNA-methylation ageing clocks.

The problem this answers: a clock needs a specific set of CpG sites. If your
array does not carry them, both common Python libraries fill the gaps from
reference-cohort medians and return a plausible-looking age anyway - biolearn
0.9.1 silently, pyaging 0.6.2 with a warning. The number survives; the signal
does not. See project doc 34.

Deliberate design choice: this service takes CpG IDENTIFIERS only, never
methylation values. Nothing that could identify a person, and no health
measurement, crosses the wire.
"""
import csv
import io
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import __version__
from .clocks import KIND_NOTE, catalogue, kind_of, sources, summary
from .degradation import SOURCE, retained_signal, verdict
from .page import PAGE

MAX_SITES = 1_200_000          # EPIC v2 is ~935k; this is a generous ceiling
MAX_UPLOAD = 64 * 1024 * 1024  # 64 MiB

CAVEAT = (
    "retained_signal is interpolated from one experiment: Horvath 2013 (353 CpGs) over "
    "24 synthetic samples, 2026-11-19. Applying it to any other clock is extrapolation. "
    "The verdict bands are this tool's rule of thumb - no minimum coverage is published "
    "for these clocks. Treat coverage (a fact) more seriously than the verdict (a judgement)."
)

# Known array sizes, for a hint about which platform was supplied.
PLATFORMS = [(27_578, "Illumina 27k"), (485_512, "Illumina 450k"),
             (865_859, "Illumina EPIC v1"), (937_690, "Illumina EPIC v2")]

app = FastAPI(
    title="Ageing-clock coverage audit",
    version=__version__,
    summary="Tells you whether a methylation array carries what a clock needs - before you trust its number.",
    description=__doc__,
)


class AuditRequest(BaseModel):
    cpgs: list[str] = Field(..., min_length=1, max_length=MAX_SITES,
                            description="CpG identifiers present in your dataset, e.g. ['cg00000029', ...]")
    clocks: list[str] | None = Field(None, description="Restrict to these clocks. Omit for all.")


def guess_platform(n: int) -> str | None:
    for size, name in PLATFORMS:
        if abs(n - size) / size < 0.05:
            return name
    return None


def audit(given: list[str], only: list[str] | None) -> dict:
    cl = catalogue()["clocks"]
    if only:
        unknown = [c for c in only if c not in cl]
        if unknown:
            raise HTTPException(422, f"unknown clock(s): {sorted(unknown)[:5]}")
        chosen = {k: cl[k] for k in only}
    else:
        chosen = cl

    present_set = {s.strip() for s in given if s and s.strip()}
    if not present_set:
        raise HTTPException(422, "no usable CpG identifiers in the input")
    all_known = set().union(*(c["site_set"] for c in cl.values()))
    recognised = present_set & all_known

    results = []
    for name, c in chosen.items():
        hit = len(c["site_set"] & present_set)
        cov = hit / c["n_sites"]
        v, note = verdict(cov, hit)
        results.append({
            "clock": name, "library": c["library"], "output": c.get("output"),
            "required_sites": c["n_sites"], "present_sites": hit,
            "coverage": round(cov, 4),
            "retained_signal": round(retained_signal(cov), 3),
            "verdict": v, "note": note,
        })
    results.sort(key=lambda r: (-r["coverage"], r["clock"]))
    tally = {}
    for r in results:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1

    return {
        "input": {
            "ids_given": len(given),
            "ids_distinct": len(present_set),
            "ids_recognised": len(recognised),
            "ids_unrecognised": len(present_set) - len(recognised),
            "platform_guess": guess_platform(len(present_set)),
        },
        "tally": tally,
        "results": results,
        "caveat": CAVEAT,
        "measured_on": SOURCE,
    }


# A person opening this on a phone got a wall of JSON. The page is served from
# the same process and reads the same endpoints, so it cannot claim more than
# the API does.
@app.get("/", include_in_schema=False, response_class=HTMLResponse)
def index():
    return HTMLResponse(PAGE)


SITES_INLINE_MAX = 10_000


@app.get("/clocks/{name}", tags=["catalogue"])
def clock(name: str):
    cl = catalogue()["clocks"]
    if name not in cl:
        raise HTTPException(404, f"unknown clock {name!r}; see /clocks")
    c = cl[name]
    out = {"clock": name, "kind": kind_of(c), "library": c["library"],
           "required_sites": c["n_sites"], "output": c.get("output"),
           "year": c.get("year"), "tissue": c.get("tissue")}
    # SexEstimation needs essentially a whole array; sending that inline helps
    # nobody and would dwarf every other response.
    if c["n_sites"] <= SITES_INLINE_MAX:
        out["sites"] = sorted(c["site_set"])
    else:
        out["sites_omitted"] = (f"{c['n_sites']} sites, over the {SITES_INLINE_MAX} "
                                "inline limit")
    return out


@app.get("/health", tags=["ops"])
def health():
    # The caveat rides along here, not only on an audit reply. The page shows
    # it before anyone has asked a question, which is when a reader most needs
    # to know what the tool cannot tell them - and it stops that block from
    # sitting on "loading" for a visitor who never runs an audit.
    return {"status": "ok", "version": __version__, "caveat": CAVEAT, **sources()}


@app.get("/clocks", tags=["catalogue"])
def clocks(
    kind: Annotated[str | None, Query(description="Keep only one kind: age, "
                                      "gestational, mitotic or other. Omit for all.")] = None,
):
    if kind is not None and kind not in KIND_NOTE:
        raise HTTPException(400, f"unknown kind {kind!r}; expected one of {sorted(KIND_NOTE)}")
    return {"clocks": summary(kind), "filtered_to": kind, **sources()}


@app.post("/audit", tags=["audit"])
def audit_json(req: AuditRequest):
    return audit(req.cpgs, req.clocks)


@app.post("/audit/csv", tags=["audit"])
async def audit_csv(
    file: Annotated[UploadFile, File(description="CSV or TSV whose first column holds CpG identifiers. "
                                                 "Methylation values, if present, are ignored and never read.")],
    column: Annotated[int, Query(ge=0, description="Zero-based index of the identifier column.")] = 0,
    has_header: Annotated[bool, Query(description="Skip the first row.")] = True,
):
    body = await file.read(MAX_UPLOAD + 1)
    if len(body) > MAX_UPLOAD:
        raise HTTPException(413, f"file larger than {MAX_UPLOAD // 1024 // 1024} MiB")
    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as e:
        raise HTTPException(415, "file is not UTF-8 text") from e
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    rows = csv.reader(io.StringIO(text), dialect)
    ids = []
    for i, row in enumerate(rows):
        if has_header and i == 0:
            continue
        if len(row) > column and row[column].strip():
            ids.append(row[column].strip())
        if len(ids) > MAX_SITES:
            raise HTTPException(413, f"more than {MAX_SITES} identifiers")
    if not ids:
        raise HTTPException(422, "no identifiers found - check 'column' and 'has_header'")
    return audit(ids, None)
