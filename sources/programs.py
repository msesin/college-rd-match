"""Strongest academic programs per college.

Two sources:
- "niche": subject rankings (e.g. "#4 Best Colleges for Economics in America"),
  loaded from a JSON file collected in a browser (Niche blocks automated requests).
  Format: [{"unitid": 166027, "programs": [{"name": "Economics", "rank": 4,
            "ranking": "#4 Best Colleges for Economics in America", "url": "..."}]}]
- "ipeds": stand-in until Niche data exists: the largest majors by bachelor's
  degrees awarded (IPEDS completions). Size is not strength; labelled as such.
"""

import csv
import json
import re
from collections import defaultdict

from sources import ipeds

SOURCE_PRIORITY = ["manual", "niche", "ipeds"]


def cip_titles(csv_path):
    """{'11.0701': 'Computer Science'} from the NCES CIP 2020 file."""
    titles = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            code = row["CIPCode"].strip('="')
            titles[code] = row["CIPTitle"].strip().rstrip(".")
    return titles


def _cip_code(n):
    s = f"{int(n):06d}"
    return f"{s[:2]}.{s[2:]}"


def ipeds_largest(unitids, cip_csv, year=2023, top=20):
    """{unitid: [(name, graduates)]} - largest first-major bachelor's programs."""
    rows = ipeds.fetch_endpoint("completions-cip-6/{year}", year, unitids,
                                {"award_level": 7, "majornum": 1, "sex": 99, "race": 99})
    titles = cip_titles(cip_csv)
    by_college = defaultdict(list)
    for r in rows:
        code, n = r.get("cipcode_6digit"), r.get("awards_6digit")
        if not code or code in (99, -1, -2, -3) or not n or n <= 0:
            continue
        name = titles.get(_cip_code(code), f"CIP {_cip_code(code)}")
        name = re.sub(r",\s*General$", "", name)
        by_college[r["unitid"]].append((name, int(n)))
    return {u: sorted(v, key=lambda x: -x[1])[:top] for u, v in by_college.items()}, year


def load_niche(path):
    """Read one JSON file, or every *.json file in a folder (batches pasted separately)."""
    from pathlib import Path

    path = Path(path)
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    out = {}
    for f in files:
        for c in json.loads(f.read_text()):
            out.setdefault(int(c["unitid"]), []).extend(c.get("programs", []))
    return out


def best_list(programs):
    """The college's ranked list from its best available source: manual, then Niche, then IPEDS."""
    by_source = defaultdict(list)
    for p in programs:
        by_source[p.source].append(p)
    for source in SOURCE_PRIORITY:
        if by_source.get(source):
            return sorted(by_source[source], key=lambda p: p.position)
    return sorted(programs, key=lambda p: (p.source, p.position))


def _weights(ranked):
    """Program name -> weight; the strongest program weighs most (20 for #1 ... 1 for #20)."""
    return {p.name.lower(): max(21 - p.position, 1) for p in ranked}


def similarity(a, b):
    """Cosine similarity (0-1) of two colleges' ranked program lists."""
    wa, wb = _weights(a), _weights(b)
    dot = sum(wa[k] * wb[k] for k in wa.keys() & wb.keys())
    na = sum(v * v for v in wa.values()) ** 0.5
    nb = sum(v * v for v in wb.values()) ** 0.5
    return dot / (na * nb) if na and nb else 0.0

