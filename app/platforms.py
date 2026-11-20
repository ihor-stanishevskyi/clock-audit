"""What each array can measure, worked out once and shipped as a table.

The question behind "how many sites does this clock need" is "can I trust it
on my chip at all", and that one needs nobody's data - only the list of probes
the array carries. scripts/build_platforms.py intersects the two offline and
commits the counts, so this module is a lookup: three arrays by sixty models,
a kilobyte on disk, no network and no manifest at runtime.
"""
import functools
import gzip
import json
import pathlib

DATA = pathlib.Path(__file__).with_name("platforms.json.gz")


@functools.lru_cache(maxsize=1)
def table() -> dict:
    if not DATA.exists():            # pragma: no cover - the file is committed
        return {"platforms": {}}
    with gzip.open(DATA, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def listing() -> list[dict]:
    return [
        {"accession": a, "label": d["label"], "probes": d["probes"],
         "published_probes": d["published_probes"], "url": d["url"]}
        for a, d in sorted(table()["platforms"].items(),
                           key=lambda kv: kv[1]["probes"])
    ]


def present_counts(accession: str) -> dict[str, int] | None:
    p = table()["platforms"].get(accession)
    return p["present"] if p else None


def meta(accession: str) -> dict | None:
    p = table()["platforms"].get(accession)
    if not p:
        return None
    return {k: v for k, v in p.items() if k != "present"} | {"accession": accession}
