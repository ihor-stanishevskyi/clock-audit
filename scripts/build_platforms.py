"""Work out what each array can even measure, once, so the service need not.

The question people actually have is not "what is in my file" but "can this
clock be trusted on my chip at all". That needs no person's data: the list of
probes an array carries answers it.

GEO publishes those lists under stable platform accessions. This downloads
three of them, intersects each clock's required sites with the array, and
writes the counts - sixty clocks by three arrays is a few hundred integers, so
the result is committed to the repo and the runtime image needs no network and
no manifest.

Run through .github/workflows/refresh-data.yml, not at image build time: the
arrays do not change, and a deploy should not fail because NCBI is slow.
"""
import gzip
import json
import re
import sys
import urllib.request

# Published probe counts, used as a tripwire. A parse that silently returns
# half an array would quietly understate every clock's coverage, which is the
# exact failure this whole service exists to catch.
PLATFORMS = [
    ("GPL8490",  "Illumina 27k",     27_578),
    ("GPL13534", "Illumina 450k",   485_577),
    ("GPL21145", "Illumina EPIC v1", 866_091),
]
TOLERANCE = 0.02
URL = ("https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi"
       "?acc={acc}&targ=self&form=text&view=data")
PROBE = re.compile(r"^(cg|ch\.|rs)\d|^(cg|ch\.)")


def probes(acc: str) -> set[str]:
    """Stream the platform table and keep the first column of each data row."""
    url = URL.format(acc=acc)
    # The linter is right to ask: urlopen will happily take file: or ftp:.
    # The accession is ours and the host is fixed, so state that rather than
    # silence the check.
    if not url.startswith("https://www.ncbi.nlm.nih.gov/"):
        raise ValueError(f"refusing to fetch {url!r}")
    req = urllib.request.Request(url, headers={  # noqa: S310 - scheme and host checked above
        "User-Agent": "clock-audit/0.1 (+github.com/ihor-stanishevskyi/clock-audit)"})
    found: set[str] = set()
    in_table = False
    with urllib.request.urlopen(req, timeout=600) as fh:  # noqa: S310 - as above
        for raw in fh:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if not in_table:
                if line.startswith("!platform_table_begin"):
                    in_table = True
                continue
            if line.startswith("!platform_table_end"):
                break
            first = line.split("\t", 1)[0].strip()
            if first and PROBE.match(first):
                found.add(first)
    return found


def main() -> int:
    with gzip.open("app/clocks.json.gz", "rt", encoding="utf-8") as fh:
        cat = json.load(fh)
    clocks = cat["clocks"]
    out = {"generated": cat["generated"], "source": "NCBI GEO platform tables",
           "platforms": {}}

    for acc, label, published in PLATFORMS:
        print(f"{acc} ({label}) ...", flush=True)
        got = probes(acc)
        drift = abs(len(got) - published) / published
        print(f"  {len(got)} probes parsed, {published} published, off by {drift:.2%}")
        if drift > TOLERANCE:
            # Loud, not soft: a wrong probe set produces plausible coverage
            # numbers that are wrong, which is worse than no numbers.
            print(f"  REFUSING: parsed count is {drift:.1%} off the published size",
                  file=sys.stderr)
            return 1
        out["platforms"][acc] = {
            "label": label, "accession": acc, "probes": len(got),
            "published_probes": published,
            "url": f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={acc}",
            # present[clock] = how many of its required sites this array carries
            "present": {name: len(set(c["sites"]) & got) for name, c in clocks.items()},
            # Some clocks normalise against a probe set far larger than their
            # own coefficients - DunedinPACE against 20,000. An array can carry
            # every coefficient and little of that set, and the answer is then
            # built from reference values. Counted separately so the service can
            # take the worse of the two rather than the flattering one.
            "present_normalisation": {
                name: len(set(c["normalisation_sites"]) & got)
                for name, c in clocks.items() if c.get("normalisation_sites")},
        }
        full = [n for n, c in clocks.items() if out["platforms"][acc]["present"][n] == c["n_sites"]]
        print(f"  clocks fully covered: {len(full)} of {len(clocks)}")
        for n, hit in out["platforms"][acc]["present_normalisation"].items():
            need = clocks[n]["n_normalisation_sites"]
            print(f"  {n}: {out['platforms'][acc]['present'][n]}/{clocks[n]['n_sites']} "
                  f"coefficients but {hit}/{need} ({hit/need:.1%}) of its "
                  f"normalisation set")

    with gzip.open("app/platforms.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(out, fh)
    print(f"written: {len(out['platforms'])} platforms x {len(clocks)} clocks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
