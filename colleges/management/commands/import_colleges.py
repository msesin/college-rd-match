"""Load the team's college list and match each college to its IPEDS UNITID.

Usage: python manage.py import_colleges [--file data/cds_decisions.csv]
Safe to re-run: existing colleges are updated, not duplicated.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from colleges.models import College
from sources import ipeds
from sources.college_list import match_unitid, read_team_list


class Command(BaseCommand):
    help = "Import the team's college list and match UNITIDs via IPEDS"

    def add_arguments(self, parser):
        parser.add_argument("--file", default=str(settings.DATA_DIR / "cds_decisions.csv"))

    def handle(self, *args, **opts):
        rows = list(read_team_list(opts["file"]))
        self.stdout.write(f"{len(rows)} colleges in {opts['file']}")
        directory = ipeds.fetch_directory()
        self.stdout.write(f"{len(directory)} IPEDS 4-year institutions loaded for matching")

        unmatched = []
        for row in rows:
            match, how = match_unitid(row["list_name"], directory)
            if not match:
                unmatched.append((row["list_name"], how))
                continue
            College.objects.update_or_create(
                unitid=match["unitid"],
                defaults={
                    "name": match["inst_name"],
                    "list_name": row["list_name"],
                    "city": match.get("city") or "",
                    "state": match.get("state_abbr") or "",
                    "website": (match.get("url_school") or "").strip("/"),
                    "has_cds": row["has_cds"],
                    "latest_cds_year": row["latest_cds_year"],
                },
            )
            self.stdout.write(f"  {row['list_name']:45} -> {match['unitid']} {match['inst_name']} [{how}]")

        for name, why in unmatched:
            self.stderr.write(f"  UNMATCHED {name}: {why}")
        self.stdout.write(self.style.SUCCESS(f"{College.objects.count()} colleges in database"))
        if unmatched:
            raise CommandError(f"{len(unmatched)} colleges not matched; add their exact IPEDS names to data/college_name_overrides.json (see sources/college_list.py)")
