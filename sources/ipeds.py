"""IPEDS data via the Urban Institute Education Data API (no key needed).

Docs: https://educationdata.urban.org/documentation/colleges.html
Endpoint list: https://educationdata.urban.org/api/v1/api-endpoints/

Each endpoint returns rows for one year. Many rows have "dimension" columns
(sex, income_level, ...) coded as integers; the API's variable list gives a
label for every code, which we use to build readable fact labels.
"""

import ast
import json
import re
import time

import requests
from django.conf import settings

BASE = "https://educationdata.urban.org/api/v1/college-university/ipeds"
VARIABLES_URL = "https://educationdata.urban.org/api/v1/api-variables/"

# Endpoints imported for every college, with the year to request.
# Years are the latest available on the Urban API as of 2026-10-08; the API
# lags NCES by 1-3 years for some endpoints (test scores 2022, net price 2021).
# Each entry: (endpoint path template, year, filters applied to keep the data relevant)
ENDPOINTS = [
    ("directory/{year}", 2024, {}),
    ("institutional-characteristics/{year}", 2025, {}),
    ("admissions-enrollment/{year}", 2024, {}),
    ("admissions-requirements/{year}", 2022, {}),
    ("academic-year-tuition/{year}", 2023, {"level_of_study": 1}),
    ("academic-year-room-board-other/{year}", 2023, {"level_of_study": 1}),
    ("sfa-grants-and-net-price/{year}", 2021, {}),
    ("sfa-ftft/{year}", 2021, {}),
    ("fall-retention/{year}", 2024, {}),
    ("student-faculty-ratio/{year}", 2024, {}),
    ("grad-rates/{year}", 2023, {"sex": 99, "race": 99}),
    ("grad-rates-pell/{year}", 2023, {}),
    ("enrollment-headcount/{year}/undergraduate", 2024, {}),
    ("fall-enrollment/{year}/undergraduate/race/sex", 2024, {"sex": 99}),
]

# Columns that identify a row rather than carry a value.
ID_COLUMNS = {"unitid", "year", "fips"}
# Negative codes the API uses instead of values.
MISSING_CODES = {-1: "missing", -2: "not applicable", -3: "suppressed"}


def _get(url, params=None, retries=4):
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=120)
        except (requests.Timeout, requests.ConnectionError):
            # The API is occasionally slow; back off and retry.
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))
            continue
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
            time.sleep(2 * (attempt + 1))
            continue
        resp.raise_for_status()


def fetch_all(url, params=None):
    """Follow the API's pagination and return all result rows."""
    rows = []
    data = _get(url, params)
    rows.extend(data["results"])
    while data.get("next"):
        data = _get(data["next"])
        rows.extend(data["results"])
    return rows


def fetch_directory(year=2024):
    """All 4-year public and private nonprofit institutions (for name matching).

    Cached in data/ipeds/ because the full list is slow to download.
    """
    cache = settings.DATA_DIR / "ipeds" / f"directory_{year}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    rows = []
    for sector in (1, 2):
        rows.extend(fetch_all(f"{BASE}/directory/{year}/", {"sector": sector}))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows))
    return rows


def fetch_endpoint(path, year, unitids, extra_filters=None):
    params = {"unitid": ",".join(str(u) for u in unitids)}
    params.update(extra_filters or {})
    return fetch_all(f"{BASE}/{path.format(year=year)}/", params)


def load_variables():
    """Variable labels and value labels, cached in data/ipeds/variables.json."""
    cache = settings.DATA_DIR / "ipeds" / "variables.json"
    if cache.exists():
        return json.loads(cache.read_text())
    rows = fetch_all(VARIABLES_URL)
    variables = {}
    for r in rows:
        values = {}
        raw = r.get("values")
        if raw and raw != "None":
            # Values are a Python-dict-like string: {1: '1 - Male', 2: '2 - Female'}
            try:
                parsed = ast.literal_eval(raw)
                values = {str(k): str(v).replace("&ndash;", "-") for k, v in parsed.items()}
            except Exception:
                values = {}
        variables[r["variable"]] = {
            "label": r.get("label") or r["variable"],
            "is_filter": str(r.get("is_filter")) == "1",
            "values": values,
        }
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(variables))
    return variables


def _value_label(variables, column, value):
    label = variables.get(column, {}).get("values", {}).get(str(value))
    if label:
        # "1 - Less than $30,000" -> "Less than $30,000"
        return label.split(" - ", 1)[1] if " - " in label else label
    return str(value)


def dimension_columns(rows, variables):
    """Coded columns that vary between one college's rows (sex, income_level, ...).

    Coded columns with a single value (e.g. admission requirements) are values,
    not dimensions.
    """
    dims = set()
    for col in rows[0] if rows else []:
        var = variables.get(col, {})
        if col in ID_COLUMNS or not (var.get("is_filter") and var.get("values")):
            continue
        if len({r.get(col) for r in rows}) > 1:
            dims.add(col)
    return dims


def _label(variables, col):
    # The API's labels for some percentile columns are wrong ("ACT writing 50th
    # percentile" for act_composite_50_pctl), so build those from the column name.
    m = re.fullmatch(r"(sat|act)_([a-z_]+)_(25|50|75)_pctl", col)
    if m:
        test, part, pct = m.groups()
        return f"{test.upper()} {part.replace('_', ' ')} {pct}th percentile score"
    return variables.get(col, {}).get("label", col)


def row_to_facts(endpoint, row, variables, dims=()):
    """Turn one API row into facts.

    Dimension columns become part of the key and label; every other column
    becomes one fact.
    """
    section = endpoint.split("/")[0]
    dim_items = [(c, row[c]) for c in sorted(dims) if c in row]
    dim_key = "".join(f"[{c}={v}]" for c, v in dim_items if v != 99)
    dim_label = ", ".join(
        f"{variables.get(c, {}).get('label', c)}: {_value_label(variables, c, v)}" for c, v in dim_items if v != 99
    )

    facts = []
    for col, val in row.items():
        if col in ID_COLUMNS or col in dims:
            continue
        label = _label(variables, col)
        if dim_label:
            label = f"{label} ({dim_label})"
        value_num, value_text = None, ""
        if isinstance(val, bool):
            value_num = float(val)
        elif isinstance(val, (int, float)):
            if val in MISSING_CODES:
                value_text = MISSING_CODES[val]
            else:
                value_num = float(val)
                coded = variables.get(col, {}).get("values", {}).get(str(val))
                if coded:
                    value_text = _value_label(variables, col, val)
        elif val is None or str(val).strip() in ("", "-2", "-1", "-3"):
            continue
        else:
            value_text = str(val)
        facts.append(
            {
                "section": section,
                "key": f"{section}.{col}{dim_key}",
                "label": label,
                "value_num": value_num,
                "value_text": value_text,
                "method": "api",
                "period": str(row.get("year", "")),
            }
        )
    return facts


SCORECARD_URL = "https://educationdata.urban.org/api/v1/college-university/scorecard/institutional-characteristics/{year}/"


def fetch_single_sex_flags(unitids, year=2020):
    """{unitid: 'men' | 'women' | 'coed'} from the College Scorecard flags (latest year on the Urban API).

    Cached in data/ipeds/ so it is fetched once.
    """
    cache = settings.DATA_DIR / "ipeds" / f"single_sex_{year}.json"
    if cache.exists():
        rows = json.loads(cache.read_text())
    else:
        rows = fetch_all(SCORECARD_URL.format(year=year), {"unitid": ",".join(str(u) for u in unitids)})
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(rows))
    out = {}
    for r in rows:
        if r.get("womenonly") == 1:
            out[r["unitid"]] = "women"
        elif r.get("menonly") == 1:
            out[r["unitid"]] = "men"
        elif r.get("womenonly") == 0 and r.get("menonly") == 0:
            out[r["unitid"]] = "coed"
    return out
