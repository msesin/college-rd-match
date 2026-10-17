"""Register CDS files, store their raw text, and extract structured values.

Usage:
  python manage.py import_cds            # all files in data/Common Data Sets/
  python manage.py import_cds --only Yale
  python manage.py import_cds --force    # re-parse even if the file is unchanged

Safe to re-run: records are keyed by file name, facts are replaced (manual
corrections made in the admin are kept).
"""

import re

from django.conf import settings
from django.core.management.base import BaseCommand

from colleges.models import College
from sources import cds
from sources.store import replace_facts, upsert_record


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower().replace("&", "and"))


def resolve_college(name):
    target = _norm(name)
    colleges = list(College.objects.all())
    for c in colleges:
        if target in (_norm(c.list_name), _norm(c.name)):
            return c
    starts = [c for c in colleges if _norm(c.name).startswith(target)]
    return starts[0] if len(starts) == 1 else None


class Command(BaseCommand):
    help = "Import CDS files from data/Common Data Sets/"

    def add_arguments(self, parser):
        parser.add_argument("--only", help="Only files whose name contains this text")
        parser.add_argument("--force", action="store_true", help="Re-parse unchanged files")

    def handle(self, *args, **opts):
        if not cds.FIELDS_PATH.exists():
            template = next(settings.CDS_DIR.glob("*.xlsx"))
            cds.build_field_dictionary(template)
            self.stdout.write(f"Built CDS field dictionary from {template.name}")

        from colleges.models import SourceRecord

        totals = {"files": 0, "facts": 0, "review": 0}
        for f in cds.discover_files(settings.CDS_DIR):
            if opts["only"] and opts["only"].lower() not in f["path"].name.lower():
                continue
            totals["files"] += 1
            college = resolve_college(f["college_name"] or "")
            if college is None:
                self.stderr.write(f"  ?? {f['path'].name}: no college matches {f['college_name']!r}")
                continue
            external_id = f"file:{f['path'].name}"
            checksum = cds.file_checksum(f["path"])
            existing = SourceRecord.objects.filter(source="cds", external_id=external_id).first()
            if existing and existing.checksum == checksum and not opts["force"]:
                self.stdout.write(f"  -- {f['path'].name}: unchanged, skipped")
                continue

            result = cds.extract(f["path"])
            record = upsert_record(
                "cds",
                external_id,
                kind="cds_document",
                college=college,
                title=f"{f['stem']} CDS {f['year']}",
                period=f["year"],
                is_primary=f.get("is_primary", True),
                file_path=str(f["path"].relative_to(settings.DATA_DIR)),
                checksum=checksum,
                raw_text=result["text"],
                raw_json={"values": {k: str(v) for k, v in result["values"].items()}, "review": result.get("review", {})},
                parse_method=result["method"],
                parse_status=result["status"],
                parse_log="\n".join(result["log"]),
            )
            facts = cds.to_facts(result, f["year"])
            n = replace_facts(record, facts)
            n_review = sum(1 for x in facts if x["needs_review"])
            totals["facts"] += n
            totals["review"] += n_review
            v = result["values"]
            c7 = sum(1 for k in v if k.startswith(("Q111_", "Q112_")))
            self.stdout.write(
                f"  {result['method']:9} {result['status']:9} {n:4} facts {n_review:2} review  C7={c7:2}  "
                f"apps={v.get('AP_RECD_1ST_N', '-'):>6} intl_apps={v.get('AP_RECD_INTL_1ST_N', '-'):>6} "
                f"intl_admits={v.get('AP_ADMT_INTL_1ST_N', '-'):>5}  {f['path'].name}"
            )
        self.stdout.write(self.style.SUCCESS(
            f"{totals['files']} files, {totals['facts']} facts, {totals['review']} flagged for review"
        ))
