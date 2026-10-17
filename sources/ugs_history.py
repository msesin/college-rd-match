"""UGS's past admissions results: how many UGS students went to each college per year.

The team's sheet has one row per college and one column per year (sheet "General": College | 2018 | ... | Total
admits). `import_ugs_history` reads it, stores the whole table as a SourceRecord (also the colleges that are not on
our list) and gives each of our colleges `ugs_admits` ({year: students}, every year, 0 included) and `ugs_capacity`
(the average of the last 3 years, rounded, at least 1; used for crowding in sources/matching.py).
"""

import json
import re
from pathlib import Path

import openpyxl

NAMES_FILE = "ugs_history_names.json"   # in data/: {"names": {sheet name: unitid}} for names that need it
RECENT_YEARS = 3
RECORD_ID = "admissions_results"   # one SourceRecord, replaced by each import


def read(path):
    """(years, {name in the sheet: {year: students}}) from the sheet "General"."""
    rows = list(openpyxl.load_workbook(Path(path), read_only=True, data_only=True)["General"].iter_rows(values_only=True))
    header = rows[0]
    cols = {int(h): i for i, h in enumerate(header) if isinstance(h, int) or (isinstance(h, str) and h.isdigit())}
    years = sorted(cols)
    table = {}
    for row in rows[1:]:
        name = str(row[0] or "").strip()
        if name:
            table[name] = {str(y): int(row[cols[y]] or 0) for y in years}
    return years, table


def _norm(name):
    return re.sub(r"[^a-z0-9]+", " ", name.lower().replace("&", "and").replace("*", "")).replace(" the ", " ").strip()


def name_map(sheet_names):
    """{sheet name: unitid} for the colleges on our list: from data/ugs_history_names.json when the file has the name,
    otherwise by matching the name to a college's name or its name in the college list (case and punctuation ignored).
    Names that match nothing are not on our list (or need a line in the file)."""
    from django.conf import settings

    from colleges.models import College

    path = settings.DATA_DIR / NAMES_FILE
    given = json.loads(path.read_text()).get("names", {}) if path.exists() else {}
    known = {}
    for c in College.objects.all():
        for n in (c.name, c.list_name):
            if n:
                known.setdefault(_norm(n), c.unitid)
    ids = set(known.values())
    return {n: given[n] if given.get(n) in ids else known[_norm(n)]
            for n in sheet_names if given.get(n) in ids or _norm(n) in known}


def capacity(admits):
    """Average UGS students a year over the last RECENT_YEARS years, rounded, at least 1."""
    recent = sorted(admits)[-RECENT_YEARS:]
    return max(1, round(sum(admits[y] for y in recent) / len(recent))) if recent else 1


def average(admits):
    """Average UGS students a year over every year in the results (None without results)."""
    return sum(admits.values()) / len(admits) if admits else None


def stored_table():
    """The last imported results: {"file", "years", "colleges": {name: {year: n}}, "unitids": {name: unitid}}."""
    from colleges.models import SourceRecord

    rec = SourceRecord.objects.filter(source="ugs", external_id=RECORD_ID).first()
    return rec.raw_json if rec else None
