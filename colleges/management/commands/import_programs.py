"""Import the strongest programs per college into the Programs table.

Usage:
  python manage.py import_programs --source ipeds                 # stand-in: largest majors (IPEDS 2023)
  python manage.py import_programs --source niche --file data/programs/niche.json

Re-running replaces that source's rows for each college. Rows added by hand
(source "manual") and rows edited on the dashboard (updated_by set) are kept.
"""

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from colleges.models import College, Program
from sources import programs


CIP_URL = "https://nces.ed.gov/ipeds/cipcode/Files/CIPCode2020.csv"


class Command(BaseCommand):
    help = "Import top programs per college"

    def add_arguments(self, parser):
        parser.add_argument("--source", choices=["ipeds", "niche"], required=True)
        parser.add_argument("--file", help="Niche JSON file (see sources/programs.py for the format)")
        parser.add_argument("--top", type=int, default=20)

    @transaction.atomic
    def handle(self, *args, **opts):
        colleges = {c.unitid: c for c in College.objects.all()}
        total = 0
        if opts["source"] == "ipeds":
            cip_csv = settings.DATA_DIR / "ipeds" / "CIPCode2020.csv"
            if not cip_csv.exists():   # the names of the program codes, from NCES (public, about 1 MB)
                self.stdout.write(f"Downloading {CIP_URL} ...")
                try:
                    response = requests.get(CIP_URL, timeout=60)
                    response.raise_for_status()
                except requests.RequestException as exc:
                    raise CommandError(f"Could not download {CIP_URL} ({exc}); save it as {cip_csv}")
                cip_csv.parent.mkdir(parents=True, exist_ok=True)
                cip_csv.write_bytes(response.content)
            data, year = programs.ipeds_largest(colleges.keys(), cip_csv, top=opts["top"])
            for unitid, rows in data.items():
                college = colleges[unitid]
                Program.objects.filter(college=college, source="ipeds", updated_by="").delete()
                kept = set(Program.objects.filter(college=college, source="ipeds").values_list("name", flat=True))
                Program.objects.bulk_create([
                    Program(college=college, position=i, name=name, graduates=n, source="ipeds",
                            ranking=f"#{i} by size: {n} bachelor's degrees (IPEDS {year})",
                            source_url=f"https://nces.ed.gov/collegenavigator/?id={unitid}#programs")
                    for i, (name, n) in enumerate(rows, start=1) if name not in kept
                ])
                total += len(rows)
        else:
            if not opts["file"]:
                raise CommandError("--file is required for --source niche")
            data = programs.load_niche(opts["file"])
            for unitid, rows in data.items():
                college = colleges.get(unitid)
                if college is None:
                    self.stderr.write(f"  unknown unitid {unitid}")
                    continue
                rows = sorted(rows, key=lambda r: (r.get("rank") is None, r.get("rank") or 0))[: opts["top"]]
                Program.objects.filter(college=college, source="niche", updated_by="").delete()
                kept = set(Program.objects.filter(college=college, source="niche").values_list("name", flat=True))
                Program.objects.bulk_create([
                    Program(college=college, position=i, name=r["name"][:200], rank_value=r.get("rank"),
                            ranking=(r.get("ranking") or "")[:300], source="niche", source_url=r.get("url") or "")
                    for i, r in enumerate(rows, start=1) if r["name"][:200] not in kept
                ])
                total += len(rows)
        self.stdout.write(self.style.SUCCESS(f"{total} {opts['source']} programs imported"))
