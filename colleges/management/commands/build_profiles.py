"""Fill the dashboard's college profiles from CDS, IPEDS, HubSpot and official-site research.

Usage:
  python manage.py build_profiles
  python manage.py build_profiles --only Yale --force   # also overwrite manual edits

Safe to re-run: values entered by hand on the dashboard are kept unless --force.
Research files: data/research/admissions_*.json (from the official-site research).
"""

import re

from django.conf import settings
from django.core.management.base import BaseCommand

from colleges.models import College
from sources import full_rides, ipeds, profile_build
from sources.profile import get_profile, set_field


# DET score UGS counselors recommend where a college publishes none.
UGS_DET_RECOMMENDATION = 135


def allow_words():
    words = set()
    for c in College.objects.all():
        words |= {w.lower() for w in re.findall(r"[A-Za-z]+", f"{c.name} {c.list_name} {c.city}")}
    return words


class Command(BaseCommand):
    help = "Build college profiles for the dashboard"

    def add_arguments(self, parser):
        parser.add_argument("--only", help="Only colleges whose name contains this text")
        parser.add_argument("--force", action="store_true", help="Overwrite values edited by hand")

    def handle(self, *args, **opts):
        research = profile_build.load_research(settings.DATA_DIR / "research")
        allow = allow_words()
        colleges = College.objects.order_by("name")
        if opts["only"]:
            colleges = colleges.filter(name__icontains=opts["only"])
        written = skipped = 0
        body = ipeds.fetch_single_sex_flags([c.unitid for c in College.objects.all()])
        for college in colleges:
            get_profile(college)
            updates = profile_build.from_cds_ipeds(college)
            if college.unitid in body:
                updates.append(("student_body", body[college.unitid], "ipeds",
                                "College Scorecard single-sex flags (IPEDS, 2020); matches the sex of 2024 IPEDS applicants"))

            row = research.get(college.unitid)
            test_note = ""
            if row:
                r_updates, test_note = profile_build.from_research(row)
                updates += r_updates

            # HubSpot DET mentions are added to the DET note, with their date.
            mentions = profile_build.hubspot_det_mentions(college, allow)
            if mentions:
                base = next((u[1] for u in updates if u[0] == "det_note"), "")
                extra = " | ".join(f"HubSpot {d}: {t}" for d, t in mentions[:3])
                updates = [u for u in updates if u[0] != "det_note"]
                src = "official_site" if row else "hubspot"
                updates.append(("det_note", f"{base} {extra}".strip(), src, "Official site + HubSpot call/note notes" if row else "HubSpot calls/notes"))
                if not row or (row.get("det_minimum") is None and row.get("det_recommended") is None):
                    nums = [int(n) for _, t in mentions for n in profile_build.SCORE_RX.findall(t)]
                    if nums:
                        updates = [u for u in updates if u[0] != "det_recommended"]
                        updates.append(("det_recommended", max(nums), "hubspot", f"HubSpot {mentions[0][0]}: {mentions[0][1]}"))

            # No published DET number anywhere: use the UGS counseling recommendation (a recommendation,
            # not a college requirement).
            det_vals = {u[0]: u[1] for u in updates if u[0] in ("det_minimum", "det_recommended")}
            if not det_vals.get("det_minimum") and not det_vals.get("det_recommended"):
                updates = [u for u in updates if u[0] != "det_recommended"]
                updates.append(("det_recommended", UGS_DET_RECOMMENDATION, "ugs",
                                "UGS college counseling recommendation (the college publishes no DET score)"))
                base = next((u for u in updates if u[0] == "det_note"), None)
                note = (f"UGS college counseling recommendation: {UGS_DET_RECOMMENDATION} "
                        f"(a recommendation, not a college requirement). ")
                updates = [u for u in updates if u[0] != "det_note"]
                updates.append(("det_note", note + (base[1] if base else ""), "ugs",
                                "UGS college counseling recommendation" + (f"; {base[3]}" if base else "")))

            # Test policy note joins the SAT note.
            if test_note:
                base = next((u[1] for u in updates if u[0] == "sat_note"), "")
                updates = [u for u in updates if u[0] != "sat_note"]
                updates.append(("sat_note", f"{base}. Policy: {test_note}".strip(". "), "official_site",
                                f"CDS/IPEDS for scores; official site for policy"))

            updates += full_rides.full_rides_updates(college) + full_rides.intl_aid_updates(college)

            for field, value, source, detail in updates:
                if set_field(college, field, value, source, detail, force=opts["force"]):
                    written += 1
                else:
                    skipped += 1
        self.stdout.write(self.style.SUCCESS(
            f"{colleges.count()} profiles; {written} values written, {skipped} unchanged or kept (manual edits). "
            f"Research rows available: {len(research)}"
        ))
