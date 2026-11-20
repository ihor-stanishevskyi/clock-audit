"""The clock catalogue: which CpG sites each clock needs.

Extracted from biolearn at image build time by scripts/extract_clocks.py, so
this module - and the runtime image - needs neither biolearn nor torch.
"""
import functools
import gzip
import json
import pathlib

DATA = pathlib.Path(__file__).with_name("clocks.json.gz")


@functools.lru_cache(maxsize=1)
def catalogue() -> dict:
    with gzip.open(DATA, "rt", encoding="utf-8") as fh:
        raw = json.load(fh)
    for c in raw["clocks"].values():
        c["site_set"] = frozenset(c["sites"])
    return raw


def clock_names() -> list[str]:
    return sorted(catalogue()["clocks"])


def summary() -> list[dict]:
    cl = catalogue()["clocks"]
    return [
        {"clock": n, "library": c["library"], "required_sites": c["n_sites"],
         "output": c.get("output"), "year": c.get("year"), "tissue": c.get("tissue")}
        for n, c in sorted(cl.items(), key=lambda kv: kv[0])
    ]


def sources() -> dict:
    c = catalogue()
    return {"libraries": c["sources"], "extracted": c["generated"],
            "clock_count": len(c["clocks"])}
