"""Read the team's college list and match each college to its IPEDS UNITID."""

import csv
import difflib
import re

OVERRIDES_FILE = "college_name_overrides.json"
# In data/ (not in git), optional, for names in your list that do not match IPEDS:
#   {"names": {"MIT": "Massachusetts Institute of Technology", ...},   list name -> exact IPEDS name
#    "states": {"Trinity College": "CT", ...}}                         IPEDS name shared by several -> its state


def overrides():
    """(names, states) from data/college_name_overrides.json; empty without the file."""
    import json

    from django.conf import settings

    path = settings.DATA_DIR / OVERRIDES_FILE
    if not path.exists():
        return {}, {}
    data = json.loads(path.read_text())
    return data.get("names", {}), data.get("states", {})


def read_team_list(path):
    """Rows of the team's CSV: College, Has CDS?, Latest CDS year."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = (row.get("College") or "").strip()
            if not name:
                continue
            has_cds = (row.get("Has CDS?") or "").strip().lower()
            yield {
                "list_name": name,
                "has_cds": {"yes": True, "no": False}.get(has_cds),
                "latest_cds_year": (row.get("Latest CDS year (only for colleges that stopped publishing)") or "").strip(),
            }


def _norm(name):
    name = name.lower().replace("&", "and")
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def match_unitid(list_name, directory):
    """Return (directory_row, how) for a team-list name, or (None, reason)."""
    names, states = overrides()
    target = names.get(list_name, list_name)
    state = states.get(target)
    candidates = [r for r in directory if not state or r.get("state_abbr") == state]
    exact = [r for r in candidates if _norm(r["inst_name"]) == _norm(target)]
    if len(exact) == 1:
        return exact[0], "exact"
    if len(exact) > 1:
        return None, f"ambiguous: {len(exact)} institutions named {target!r}"
    names = {_norm(r["inst_name"]): r for r in candidates}
    close = difflib.get_close_matches(_norm(target), names.keys(), n=1, cutoff=0.85)
    if close:
        return names[close[0]], f"fuzzy ({close[0]})"
    return None, "no match"
