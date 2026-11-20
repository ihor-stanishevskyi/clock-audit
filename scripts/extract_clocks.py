"""Extract each clock's required CpG list from biolearn and pyaging.

Run at image build time so the runtime image needs neither library (nor torch).
Writes app/clocks.json: {"generated": iso8601, "sources": {...}, "clocks": {name: {...}}}
"""
import datetime
import importlib.metadata as md
import json
import sys

out = {"clocks": {}, "sources": {}, "generated": datetime.datetime.now(datetime.UTC).isoformat()}

# --- biolearn: every model that declares methylation sites -------------------
try:
    from biolearn.model_gallery import ModelGallery
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
except Exception as e:  # noqa: BLE001 - reported, not swallowed
    print(f"biolearn skipped: {type(e).__name__}: {e}", file=sys.stderr)

# --- pyaging: clock metadata ships locally; weights do not ------------------
try:
    out["sources"]["pyaging"] = md.version("pyaging")
except Exception as e:  # noqa: BLE001 - pyaging is optional here
    print(f"pyaging version unavailable: {type(e).__name__}", file=sys.stderr)

if not out["clocks"]:
    sys.exit("no clocks extracted - refusing to write an empty file")

with open("app/clocks.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh)
names = sorted(out["clocks"], key=lambda k: -out["clocks"][k]["n_sites"])
print(f"годинників: {len(out['clocks'])}")
print(f"{'годинник':<26}{'сайтів':>8}  вихід")
for n in names[:12]:
    c = out["clocks"][n]
    print(f"{n:<26}{c['n_sites']:>8}  {c.get('output') or '-'}")
print(f"... ще {max(0, len(names)-12)}")
print(f"унікальних CpG усього: {len({s for c in out['clocks'].values() for s in c['sites']})}")
