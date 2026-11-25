"""Extract each clock's required CpG list from biolearn and pyaging.

Run at image build time so the runtime image needs neither library (nor torch).
Writes app/clocks.json: {"generated": iso8601, "sources": {...}, "clocks": {name: {...}}}

A clock's coefficient list is not always everything it needs. DunedinPACE
carries 173 weighted sites, but its implementation first quantile-normalises
the sample against a 20,000-probe gold standard and imputes anything missing
from it - so a chip carrying all 173 and few of the 20,000 produces a number
built mostly from reference values. Counting only the 173 understates the
requirement by a factor of 115, and the service said 173 for five days.
Both sets are recorded here, and a tripwire below refuses to build if biolearn
gains another clock like this.
"""
import datetime
import importlib.metadata as md
import json
import sys

out = {"clocks": {}, "sources": {}, "generated": datetime.datetime.now(datetime.UTC).isoformat()}

# Clocks whose implementation needs probes beyond their own coefficients, and
# the biolearn file that lists them. As of biolearn 0.9.1 this is the only
# methylation clock with a preprocessing step; the check after the loop makes
# sure that stays true rather than assuming it.
PREPROCESS_SETS = {"DunedinPACE": ("DunedinPACE_Gold_Means.csv", 20_000)}

# --- biolearn: every model that declares methylation sites -------------------
try:
    import pandas as pd
    from biolearn.model_gallery import ModelGallery
    from biolearn.util import get_data_file
    g = ModelGallery()
    out["sources"]["biolearn"] = md.version("biolearn")
    for name in g.model_definitions:
        try:
            sites = sorted(set(g.get(name).methylation_sites()))
        except Exception as e:  # noqa: BLE001 - one bad clock must not sink the catalogue
            print(f"  skipped {name}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        if not sites:
            continue
        d = g.model_definitions[name]
        out["clocks"][name] = {
            "library": "biolearn",
            "sites": sites,
            "n_sites": len(sites),
            "year": d.get("year"),
            "species": d.get("species"),
            "tissue": d.get("tissue"),
            "output": d.get("output"),
        }
        if name in PREPROCESS_SETS:
            fname, expected = PREPROCESS_SETS[name]
            ref = pd.read_csv(get_data_file(fname), index_col=0)
            probes = sorted(set(str(x) for x in ref.index))
            # A half-read reference would quietly inflate coverage against it,
            # which is the same class of error this whole field exists to fix.
            if abs(len(probes) - expected) > 0.02 * expected:
                sys.exit(f"{name}: {fname} has {len(probes)} probes, expected "
                         f"about {expected} - refusing to write a wrong requirement")
            out["clocks"][name]["normalisation_sites"] = probes
            out["clocks"][name]["n_normalisation_sites"] = len(probes)
            out["clocks"][name]["normalisation_source"] = fname
            print(f"  {name}: {len(probes)} normalisation probes beyond its "
                  f"{len(sites)} coefficients", file=sys.stderr)

    # The tripwire. If a future biolearn adds a preprocessing step to another
    # methylation clock, this build fails instead of publishing an understated
    # requirement for it.
    unaccounted = sorted(
        n for n in out["clocks"]
        if "preprocess" in (g.model_definitions[n].get("model") or {})
        and n not in PREPROCESS_SETS)
    if unaccounted:
        sys.exit(f"these clocks gained a preprocessing step and their extra probe "
                 f"sets are not recorded: {unaccounted}. Add them to "
                 f"PREPROCESS_SETS before shipping, or the service will "
                 f"understate what they need.")
except Exception as e:  # noqa: BLE001 - reported, not swallowed
    print(f"biolearn skipped: {type(e).__name__}: {e}", file=sys.stderr)

# --- pyaging: version only; it contributes NO models ------------------------
# Its clock metadata is downloaded per clock at runtime, so nothing is
# extracted here. The version is still recorded, and app/clocks.py reports it
# as installed-but-contributed-nothing rather than as a source of this
# catalogue - which is what the service wrongly implied for a day.
try:
    out["sources"]["pyaging"] = md.version("pyaging")
except Exception as e:  # noqa: BLE001 - pyaging is optional here
    print(f"pyaging version unavailable: {type(e).__name__}", file=sys.stderr)

if not out["clocks"]:
    sys.exit("no clocks extracted - refusing to write an empty file")

with open("app/clocks.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh)
names = sorted(out["clocks"], key=lambda k: -out["clocks"][k]["n_sites"])
print(f"моделей (не всі - годинники віку): {len(out['clocks'])}")
print(f"{'модель':<26}{'сайтів':>8}  вихід")
for n in names[:12]:
    c = out["clocks"][n]
    print(f"{n:<26}{c['n_sites']:>8}  {c.get('output') or '-'}")
print(f"... ще {max(0, len(names)-12)}")
print(f"унікальних CpG усього: {len({s for c in out['clocks'].values() for s in c['sites']})}")
