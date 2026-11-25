"""The clock catalogue: which CpG sites each model needs.

Extracted at image build time by scripts/extract_clocks.py, so this module -
and the runtime image - needs neither biolearn nor torch.

Two things this module is careful about, because getting them wrong is how the
service came to overstate itself:

1. A library counts as a source of the catalogue only if models in the
   catalogue actually came from it. The extractor used to write a version
   number for a library that contributed nothing, and every answer repeated it.
   Contributors are derived from the models themselves, so the claim cannot
   drift from the data again.
2. Not every model here is an ageing clock. biolearn's gallery also carries
   predictors of smoking, cholesterol, sex, disease status and cell
   composition. Reporting one number for all of them invites "60 ageing
   clocks", which is wrong. Each model carries its kind, and the counts are
   reported per kind.
3. A clock's coefficient list is not always everything it needs. DunedinPACE
   normalises against 20,000 probes before using its 173 weighted sites, so an
   array carrying all 173 and few of the 20,000 yields a number built mostly
   from reference values. Both sets are carried here; the service takes the
   worse of the two coverages, not the flattering one.
"""
import functools
import gzip
import json
import pathlib
import re
from collections import Counter

DATA = pathlib.Path(__file__).with_name("clocks.json.gz")


@functools.lru_cache(maxsize=1)
def catalogue() -> dict:
    with gzip.open(DATA, "rt", encoding="utf-8") as fh:
        raw = json.load(fh)
    for c in raw["clocks"].values():
        c["site_set"] = frozenset(c["sites"])
        c["norm_set"] = frozenset(c.get("normalisation_sites", ()))
    return raw


def clock_names() -> list[str]:
    return sorted(catalogue()["clocks"])


KIND_NOTE = {
    "age": "predicts age, or the rate of ageing, in people after birth",
    "gestational": "predicts gestational age of a newborn - not adult ageing",
    "mitotic": "counts cell divisions, not years lived",
    "other": "predicts something else entirely: smoking, cholesterol, sex, "
             "disease status, cell composition",
}


def kind_of(model: dict) -> str:
    """Sort a model by what it actually predicts, from its own declared output.

    Gestational clocks are the trap worth naming: Bohlin reports "Age (days)"
    and would read as an age clock, but it is cord blood at birth.
    """
    out = (model.get("output") or "").strip().lower()
    tissue = (model.get("tissue") or "").strip().lower()
    if "gestational" in out or "cord blood" in tissue or "placenta" in tissue:
        return "gestational"
    if "mitotic" in out or "stem cell division" in out:
        return "mitotic"
    if "aging rate" in out or "mortality adjusted age" in out or re.search(r"\bage\b", out):
        return "age"
    return "other"


def summary(kind: str | None = None) -> list[dict]:
    cl = catalogue()["clocks"]
    rows = [
        {"clock": n, "kind": kind_of(c), "library": c["library"],
         "required_sites": c["n_sites"],
         # Present only for the clocks that have one, so a reader does not take
         # a null to mean "none needed" for every other clock.
         **({"normalisation_sites": c["n_normalisation_sites"]}
            if c.get("n_normalisation_sites") else {}),
         "output": c.get("output"),
         "year": c.get("year"), "tissue": c.get("tissue")}
        for n, c in sorted(cl.items(), key=lambda kv: kv[0])
    ]
    return [r for r in rows if kind is None or r["kind"] == kind]


def sources() -> dict:
    c = catalogue()
    cl = c["clocks"]
    produced = Counter(m["library"] for m in cl.values())
    declared = c.get("sources", {})
    kinds = Counter(kind_of(m) for m in cl.values())
    age_sites = {s for m in cl.values() if kind_of(m) == "age" for s in m["sites"]}
    out = {
        # Only libraries that put models here. A declared version is not a claim.
        "catalogue_from": {k: v for k, v in declared.items() if produced.get(k)},
        "extracted": c["generated"],
        "model_count": len(cl),
        "models_by_kind": dict(sorted(kinds.items())),
        "kind_means": KIND_NOTE,
        "age_clock_count": kinds.get("age", 0),
        "distinct_sites_all_models": len({s for m in cl.values() for s in m["sites"]}),
        # The all-models figure is dominated by one sex predictor that needs
        # essentially the whole array, so it says little about ageing clocks.
        "distinct_sites_age_clocks": len(age_sites),
    }
    idle = {k: v for k, v in declared.items() if not produced.get(k)}
    if idle:
        out["installed_but_contributed_nothing"] = idle
    return out
