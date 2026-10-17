"""Fill CollegeProfile fields from data already in the database.

Each builder returns a list of (field, value, source, detail) tuples; the
build_profiles command writes them with sources.profile.set_field, which
keeps manual edits.
"""

import json
import re
from decimal import Decimal
from pathlib import Path

from colleges.models import Fact, SourceRecord
from sources.redact import filter_names


def _cds(college):
    """{tag: Fact} from the college's primary CDS document."""
    facts = Fact.objects.filter(college=college, source="cds", record__is_primary=True).select_related("record")
    return {f.key: f for f in facts}


def _ipeds(college, section):
    return {f.key: f for f in Fact.objects.filter(college=college, source="ipeds", section=section)}


def _num(fact):
    return fact.value_num if fact is not None and fact.value_num is not None else None


Z25, Z30 = 0.6745, 0.5244  # distance of the 25th and 30th percentiles from the median, in standard deviations


def sat_cutoffs(p25, p50, p75):
    """Estimated 30th and 70th percentiles (rounded to 10) from the 25th, 50th and 75th: on a normal curve the
    30th lies 22% of the way from the 25th to the median, and the 70th 78% of the way from the median to the 75th."""
    p50 = min(max(p50, p25), p75)
    p30 = p25 + (Z25 - Z30) / Z25 * (p50 - p25)
    p70 = p50 + Z30 / Z25 * (p75 - p50)
    return int(round(p30 / 10) * 10), int(round(p70 / 10) * 10)


def from_cds_ipeds(college):
    out = []
    cds = _cds(college)
    doc = next(iter(cds.values())).record.title if cds else ""

    # SAT median: CDS C9 50th percentile; else midpoint of 25th-75th; else section medians (CDS, then IPEDS).
    p25, p50, p75 = (_num(cds.get(f"SAT1_COMP_{p}TH_P")) for p in (25, 50, 75))
    if p25 and p75 and not (p25 < p75 and (p50 is None or p25 <= p50 <= p75)):
        p25 = p50 = p75 = None  # composite figures contradict each other (a CDS reading error): use the sections
    sv, sm = _num(cds.get("SAT1_VERB_50TH_P")), _num(cds.get("SAT1_MATH_50TH_P"))
    if p50:
        rng = f"; middle 50%: {p25:.0f}-{p75:.0f}" if p25 and p75 else ""
        out.append(("sat_median", int(p50), "cds", f"{doc}, C9 SAT composite 50th percentile"))
        out.append(("sat_note", f"CDS {cds['SAT1_COMP_50TH_P'].period} enrolled students{rng}", "cds", f"{doc}, C9"))
    elif p25 and p75:
        out.append(("sat_median", int(round((p25 + p75) / 2)), "cds", f"{doc}, C9: midpoint of 25th ({p25:.0f}) and 75th ({p75:.0f}) percentiles"))
        out.append(("sat_note", f"Midpoint of CDS middle 50% {p25:.0f}-{p75:.0f}", "cds", f"{doc}, C9"))
    elif sv and sm:
        out.append(("sat_median", int(sv + sm), "cds", f"{doc}, C9: sum of section medians (reading {sv:.0f} + math {sm:.0f})"))
        out.append(("sat_note", f"Approximate: sum of CDS {cds['SAT1_MATH_50TH_P'].period} section medians", "cds", f"{doc}, C9"))
    else:
        req = _ipeds(college, "admissions-requirements")
        rw, m = _num(req.get("admissions-requirements.sat_crit_read_50_pctl")), _num(req.get("admissions-requirements.sat_math_50_pctl"))
        if rw and m:
            year = req["admissions-requirements.sat_math_50_pctl"].period
            out.append(("sat_median", int(rw + m), "ipeds", f"IPEDS {year}: sum of section medians (reading {rw:.0f} + math {m:.0f})"))
            out.append(("sat_note", f"Approximate: sum of IPEDS {year} section medians (no SAT figure in the CDS)", "ipeds", f"IPEDS {year} admissions-requirements"))

    # SAT 25th/75th percentiles (composite; else the sum of the section percentiles, CDS then IPEDS),
    # and the red-flag (30th) and safety (70th) lines the matching engine uses.
    quartiles = None
    if p25 and p75:
        quartiles = (p25, p75, "cds", f"{doc}, C9 SAT composite 25th/75th percentiles")
    else:
        sec = [_num(cds.get(k)) for k in ("SAT1_VERB_25TH_P", "SAT1_MATH_25TH_P", "SAT1_VERB_75TH_P", "SAT1_MATH_75TH_P")]
        req = _ipeds(college, "admissions-requirements")
        ipq = [_num(req.get(f"admissions-requirements.{k}")) for k in
               ("sat_crit_read_25_pctl", "sat_math_25_pctl", "sat_crit_read_75_pctl", "sat_math_75_pctl")]
        if all(sec):
            quartiles = (sec[0] + sec[1], sec[2] + sec[3], "cds", f"{doc}, C9: sum of section 25th/75th percentiles (approximate)")
        elif all(ipq):
            year = req["admissions-requirements.sat_math_25_pctl"].period
            quartiles = (ipq[0] + ipq[1], ipq[2] + ipq[3], "ipeds",
                         f"IPEDS {year}: sum of section 25th/75th percentiles (approximate)")
    if quartiles:
        lo, hi, src, detail = quartiles
        median = next((u[1] for u in out if u[0] == "sat_median"), None) or (lo + hi) / 2
        p30, p70 = sat_cutoffs(lo, median, hi)
        out += [("sat_p25", int(lo), src, detail), ("sat_p75", int(hi), src, detail),
                ("sat_p30", p30, src, f"{detail}; 30th percentile estimated between the 25th and the median ({median:.0f})"),
                ("sat_p70", p70, src, f"{detail}; 70th percentile estimated between the median ({median:.0f}) and the 75th")]

    gpa = _num(cds.get("FRSH_GPA"))
    if gpa and 1 <= gpa <= 5:
        submit = _num(cds.get("FRSH_GPA_SUBMIT_P"))
        note = "CDS C12 average (CDS reports an average, not a median)"
        if submit:
            note += f"; {submit:.0f}% of first-years submitted a GPA"
        out.append(("gpa_average", Decimal(str(round(gpa, 2))), "cds", f"{doc}, C12"))
        out.append(("gpa_note", note, "cds", f"{doc}, C12"))

    top10 = _num(cds.get("FRSH_HS_RANK_10_P"))
    if top10 is not None:
        out.append(("top10_pct", round(top10, 1), "cds", f"{doc}, C10 (of students who submitted class rank)"))
    g1, g2 = _num(cds.get("EN_FRSH_GPA_1_P")), _num(cds.get("EN_FRSH_GPA_2_P"))
    if g1 is not None or g2 is not None:
        out.append(("gpa_375_pct", round((g1 or 0) + (g2 or 0), 1), "cds", f"{doc}, C11: GPA 4.0 plus 3.75-3.99 (all enrolled)"))
    return out


DET_RX = re.compile(r"(duolingo|\bdet\b)", re.I)
SCORE_RX = re.compile(r"\b(8\d|9\d|1[0-5]\d|160)\b")


def hubspot_det_mentions(college, allow_words):
    """[(date, clause)] where HubSpot calls/notes mention a DET score, name-filtered."""
    out = []
    recs = SourceRecord.objects.filter(source="hubspot", college=college).exclude(kind="hubspot_company")
    for r in recs.order_by("-period", "-title"):
        kept, _, _ = filter_names(r.raw_text, allow_words)
        for seg in kept.split("\n"):
            if DET_RX.search(seg) and SCORE_RX.search(seg):
                date = (r.raw_json or {}).get("timestamp", "")[:10] or r.period
                out.append((date, seg.strip()[:220]))
    return out


def load_research(folder):
    """{unitid: row} from all JSON files in data/research/."""
    rows = {}
    for path in sorted(Path(folder).glob("admissions_*.json")):
        for row in json.loads(path.read_text()):
            rows[int(row["unitid"])] = row
    return rows


STRONGLY_PREFERRED = re.compile(r"strongly encourag|strongly recommend|recommended if available", re.I)


def from_research(row):
    out = []
    url = row.get("det_url") or ""
    year = row.get("policy_year", "")
    detail = f"Official site ({year}): {url}" if url else f"Official site ({year})"
    out.append(("det_minimum", row.get("det_minimum"), "official_site", detail))
    out.append(("det_recommended", row.get("det_recommended"), "official_site", detail))
    note = row.get("det_note") or ""
    if row.get("det_accepted") is False:
        note = "DET not accepted. " + note
    out.append(("det_note", note, "official_site", detail))
    policy = row.get("test_policy") if row.get("test_policy") in ("required", "optional", "blind") else "unknown"
    # "Optional" on paper but the college asks international applicants to send scores: treat as strongly preferred.
    if policy == "optional" and STRONGLY_PREFERRED.search(row.get("test_policy_note") or ""):
        policy = "preferred"
    tdetail = f"Official site ({year}): {row.get('test_policy_url') or ''}"
    out.append(("test_policy", policy, "official_site", tdetail))
    return out, (row.get("test_policy_note") or "")
