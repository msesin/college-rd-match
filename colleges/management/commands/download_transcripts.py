"""Download the transcript images linked in a spreadsheet, one folder per student.

Usage (on your own computer):
  python manage.py download_transcripts --file "data/students/source/Applications-cohort (5).csv" --dry-run
  python manage.py download_transcripts --file "data/students/source/Applications-cohort (5).csv" --limit 3      # test on the first 3 rows
  python manage.py download_transcripts --file "data/students/source/Applications-cohort (5).csv"               # everything

Defaults: ID in column A, links in column C. Files go to data/students/raw/<ID>/, with a
download_log.csv. The name column is never read. Re-running skips files already downloaded.
No AI is involved; nothing leaves your computer except the downloads themselves.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from sources import transcript_links


class Command(BaseCommand):
    help = "Download transcript files linked in a spreadsheet column"

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Path to the .csv or .xlsx file")
        parser.add_argument("--id-column", default="A", help="Column with the student ID (default A)")
        parser.add_argument("--link-column", default="C", help="Column with the links (default C)")
        parser.add_argument("--sheet", help="Sheet name (default: the first sheet)")
        parser.add_argument("--out", default=str(settings.DATA_DIR / "students" / "raw"))
        parser.add_argument("--limit", type=int, help="Only the first N rows (for a test)")
        parser.add_argument("--dry-run", action="store_true", help="Count rows and links; download nothing")

    def handle(self, *args, **opts):
        try:
            summary = transcript_links.run(
                opts["file"], opts["out"], opts["id_column"].upper(), opts["link_column"].upper(),
                opts["sheet"], opts["limit"], opts["dry_run"], log=self.stdout.write)
        except FileNotFoundError:
            raise CommandError(f"File not found: {opts['file']}")
        self.stdout.write(self.style.SUCCESS(str(summary)))
