"""Full rides and yearly aid to international students, per college: what reliable sources say.

The research itself is data, not code: data/research/full_rides.json (not in git), with
- "full_rides": {unitid: [value, "intl" | "all", note, source link]}: only numbers or shares that a source states
  (college pages, student newspapers, news, or the organisation's own notes when the link is empty). Nothing is
  calculated. value "" = no reliable count found;
- "not_found": {unitid: note}: what was found instead, for colleges without a count;
- "intl_aid_extra": {unitid: [total dollars, students, note]}: CDS H6 figures read by hand where the import has none.
Without the file, colleges show "No count published" and international aid comes from the CDS import alone.

INTERNATIONAL AID PER YEAR: the college's Common Data Set, section H6: total institutional aid awarded
to international (nonresident) undergraduates in one year, with the number of students and the average.
"""

import json

from colleges.models import Fact

INTL, ALL = "intl", "all"


def research():
    """(full_rides, not_found, intl_aid_extra) from data/research/full_rides.json; empty without the file."""
    from django.conf import settings

    path = settings.DATA_DIR / "research" / "full_rides.json"
    if not path.exists():
        return {}, {}, {}
    data = json.loads(path.read_text())
    return ({int(k): tuple(v) for k, v in data.get("full_rides", {}).items()},
            {int(k): v for k, v in data.get("not_found", {}).items()},
            {int(k): tuple(v) for k, v in data.get("intl_aid_extra", {}).items()})


def full_rides_updates(college):
    """[(field, value, source, detail)] for build_profiles."""
    rides, notes, _ = research()
    if college.unitid in rides:
        value, scope, note, url = rides[college.unitid]
        source = "hubspot" if not url else "web"
    else:
        value, scope, url = "", "", ""
        note = notes.get(college.unitid, "No count published.")
        source = "web"
    detail = f"Reviewed 2026-10-13: {url or 'HubSpot notes'} (sources/full_rides.py)"
    return [("full_rides", value, source, detail), ("full_rides_scope", scope, source, detail),
            ("full_rides_url", url, source, detail), ("full_rides_note", note, source, detail)]


def intl_aid_updates(college):
    """Yearly institutional aid to international undergraduates, from CDS H6."""
    extra = research()[2]
    if college.unitid in extra:
        total, n, note = extra[college.unitid]
        detail = "CDS H6 read from the college's site (sources/full_rides.py)"
        return [("intl_aid_total", total, "official_site", detail), ("intl_aid_students", n, "official_site", detail),
                ("intl_aid_note", note, "official_site", detail)]
    facts = {f.key: f for f in Fact.objects.filter(college=college, source="cds", record__is_primary=True,
                                                    key__in=["INTL_RECD_N", "INTL_AVG_D", "INTL_TOT_D"])}
    n = facts.get("INTL_RECD_N") and facts["INTL_RECD_N"].value_num
    avg = facts.get("INTL_AVG_D") and facts["INTL_AVG_D"].value_num
    total = facts.get("INTL_TOT_D") and facts["INTL_TOT_D"].value_num
    if not total and n and avg:
        total = n * avg  # the CDS gives the count and the average but left the total blank
    if not total:
        return [("intl_aid_total", None, "cds", "No CDS H6 figures"), ("intl_aid_students", None, "cds", "No CDS H6 figures"),
                ("intl_aid_note", "No CDS figures on aid to international students.", "cds", "No CDS H6 figures")]
    period = next(iter(facts.values())).period
    note = f"CDS {period}, H6: all international undergraduates in that year"
    if n:
        note += f"; {n:.0f} students on aid" + (f", average ${avg:,.0f}" if avg else "")
    detail = f"CDS {period} H6 (aid to nonresident undergraduates)"
    return [("intl_aid_total", round(total), "cds", detail), ("intl_aid_students", round(n) if n else None, "cds", detail),
            ("intl_aid_note", note + ".", "cds", detail)]
