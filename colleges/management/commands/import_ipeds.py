"""Fetch IPEDS data for every college from the Urban Institute Education Data API.

Usage:
  python manage.py import_ipeds
  python manage.py import_ipeds --only admissions-enrollment

One request per endpoint covers all colleges. Each college gets one
SourceRecord per endpoint (raw rows kept) and one Fact per value.
Safe to re-run: records are keyed by endpoint/year/unitid and facts replaced.
"""

from collections import defaultdict

from django.core.management.base import BaseCommand

from colleges.models import College
from sources import ipeds
from sources.store import replace_facts, upsert_record


class Command(BaseCommand):
    help = "Import IPEDS data for all colleges"

    def add_arguments(self, parser):
        parser.add_argument("--only", help="Only endpoints whose path contains this text")

    def handle(self, *args, **opts):
        colleges = {c.unitid: c for c in College.objects.all()}
        variables = ipeds.load_variables()
        self.stdout.write(f"{len(colleges)} colleges, {len(variables)} IPEDS variable definitions")

        for path, year, filters in ipeds.ENDPOINTS:
            if opts["only"] and opts["only"] not in path:
                continue
            try:
                rows = ipeds.fetch_endpoint(path, year, colleges.keys(), filters)
            except Exception as exc:
                self.stderr.write(f"  !! {path} {year}: {exc}")
                continue
            by_college = defaultdict(list)
            for row in rows:
                by_college[row["unitid"]].append(row)

            endpoint = path.format(year=year)
            n_facts = 0
            for unitid, college_rows in by_college.items():
                college = colleges.get(unitid)
                if college is None:
                    continue
                record = upsert_record(
                    "ipeds",
                    f"{endpoint}/{unitid}",
                    kind="ipeds_endpoint",
                    college=college,
                    title=f"IPEDS {endpoint}",
                    period=str(year),
                    raw_json={"endpoint": endpoint, "filters": filters, "rows": college_rows},
                    parse_method="api",
                    parse_status="ok",
                )
                dims = ipeds.dimension_columns(college_rows, variables)
                facts = [f for row in college_rows for f in ipeds.row_to_facts(path, row, variables, dims)]
                n_facts += replace_facts(record, facts)
            missing = len(colleges) - len(by_college)
            self.stdout.write(
                f"  {endpoint:45} {len(rows):5} rows  {n_facts:6} facts"
                + (f"  ({missing} colleges without data)" if missing else "")
            )
        self.stdout.write(self.style.SUCCESS("IPEDS import done"))
