"""Import UGS's past admissions results: how many UGS students went to each college per year.

Usage: python manage.py import_ugs_history --file "data/UGS 2018-2025 College Admissions results.xlsx"

The sheet "General" has one row per college and one column per year (no names). The whole table is stored as a
SourceRecord (for the UGS results page, also colleges not on our list). Each of our colleges gets `ugs_admits`
({year: students}, every year, 0 included) and `ugs_capacity`: the average of the last 3 years, rounded, at least 1
(also for colleges with no UGS students yet). Capacity edited by hand on the dashboard is kept. Safe to re-run.
The 2025 column was built from "2025 College Applicants.xlsx" by data/build_ugs_2025_results.py (decision 43).
"""

import hashlib
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from colleges.models import College, SourceRecord
from sources import ugs_history
from sources.profile import set_field


class Command(BaseCommand):
    help = "Import UGS students per college and year, and set each college's UGS capacity"

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True)

    def handle(self, *args, **opts):
        path = Path(opts["file"])
        if not path.exists():
            raise CommandError(f"No file at {path}")
        years, table = ugs_history.read(path)
        names = ugs_history.name_map(table)
        found = {names[n]: admits for n, admits in table.items() if n in names}
        skipped = [n for n in table if n not in names]
        SourceRecord.objects.update_or_create(source="ugs", external_id=ugs_history.RECORD_ID, defaults={
            "kind": "ugs_admissions_results", "title": "UGS admissions results", "period": str(years[-1]),
            "file_path": path.name, "checksum": hashlib.sha256(path.read_bytes()).hexdigest(),
            "raw_json": {"file": path.name, "years": years, "colleges": table,
                         "unitids": names},
            "parse_method": "openpyxl", "parse_status": "ok", "fetched_at": timezone.now(),
        })
        recent = years[-ugs_history.RECENT_YEARS:]
        detail = f"{path.name}: UGS students {years[0]}-{years[-1]}; capacity = average of {recent[0]}-{recent[-1]}, at least 1"
        changed = []
        for college in College.objects.all():
            admits = found.get(college.unitid, {str(y): 0 for y in years})
            profile = getattr(college, "profile", None)
            before = profile.ugs_capacity if profile else None
            set_field(college, "ugs_admits", admits, "ugs", detail)
            set_field(college, "ugs_capacity", ugs_history.capacity(admits), "ugs", detail)
            after = type(college).objects.get(pk=college.pk).profile.ugs_capacity
            if before is not None and after != before:
                changed.append(f"{college.name} {before} -> {after}")
        missing = [c.name for c in College.objects.exclude(unitid__in=found)]
        self.stdout.write(self.style.SUCCESS(f"{len(found)} colleges matched ({years[0]}-{years[-1]}); "
                                             f"capacity set for all {College.objects.count()}."))
        self.stdout.write(f"Capacity changed: {', '.join(changed) or 'none'}")
        self.stdout.write(f"Not in the sheet (capacity 1): {', '.join(missing) or 'none'}")
        self.stdout.write(f"Rows not on our list (kept for the UGS results page): {', '.join(skipped)}")
