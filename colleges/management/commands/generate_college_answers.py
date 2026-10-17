"""Fill the vibe, AP/IB, olympiad and HubSpot feedback columns with an LLM: one request per college.

The single request asks all three questions and gets a structured (JSON) answer
with one field per dashboard column. Colleges with HubSpot notes also get the
notes as context; the model fact-checks them, and its feedback goes to the
"HubSpot feedback" column. Colleges without notes get no feedback.

Usage:
  python manage.py generate_college_answers --dry-run --only Harvard   # show the prompt, no API call
  python manage.py generate_college_answers --only Harvard             # one real request
  python manage.py generate_college_answers                            # all colleges (71 requests)

Options: --force overwrites values edited by hand; --rpm sets the request limit per
minute (default LLM_RPM from .env, else 15).
Provider: Gemini if GEMINI_API_KEY is in .env (model GEMINI_MODEL), else Anthropic.
Every request and answer is saved in the AIAnswer table and shown on the college page.
"""

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.core.management.base import BaseCommand, CommandError

from colleges.models import AIAnswer, College
from sources import college_ai
from sources.profile import get_profile, set_field

# JSON field from the model -> CollegeProfile field
FIELD_MAP = {
    "vibe": "vibe",
    "apib_level": "apib_preference",
    "apib_explanation": "apib_rationale",
    "olympiad_level": "olympiad_preference",
    "olympiad_explanation": "olympiad_rationale",
    "hubspot_feedback": "hubspot_feedback",
}


class Command(BaseCommand):
    help = "Generate college vibe / AP-IB / olympiad / HubSpot feedback with an LLM (one request per college)"

    def add_arguments(self, parser):
        parser.add_argument("--only", help="Only colleges whose name contains this text")
        parser.add_argument("--force", action="store_true", help="Overwrite values edited by hand")
        parser.add_argument("--dry-run", action="store_true", help="Print prompts instead of calling the API")
        parser.add_argument("--rpm", type=int, default=int(os.environ.get("LLM_RPM") or 15),
                            help="Maximum requests per minute (default 15)")

    def handle(self, *args, **opts):
        colleges = College.objects.order_by("name")
        if opts["only"]:
            colleges = colleges.filter(name__icontains=opts["only"])
        if not colleges:
            raise CommandError(f"No college matches {opts['only']!r}")
        allow = set()
        for c in College.objects.all():
            allow |= {w.lower() for w in re.findall(r"[A-Za-z]+", f"{c.name} {c.list_name} {c.city}")}

        jobs = []
        for college in colleges:
            get_profile(college)
            context, n_items = college_ai.hubspot_context(college, allow)
            jobs.append((college, college_ai.build_prompt(college, context), context, n_items))

        if opts["dry_run"]:
            for college, prompt, context, n in jobs:
                self.stdout.write(f"\n===== {college.name} ({n} HubSpot items, {len(context)} chars)\n{prompt}")
            self.stdout.write(f"\n{len(jobs)} request(s) would be sent (one per college).")
            return

        name, model = college_ai.provider()
        if name is None:
            raise CommandError("Set GEMINI_API_KEY (or ANTHROPIC_API_KEY) in .env")
        client = college_ai.make_client(name)
        limiter = college_ai.RateLimiter(opts["rpm"], 60)
        self.stdout.write(f"{len(jobs)} request(s) to {name} {model}, max {opts['rpm']} per minute "
                          f"(~{len(jobs) / opts['rpm']:.0f} min)")

        done = failed = 0
        with ThreadPoolExecutor(max_workers=min(opts["rpm"], 8)) as pool:
            futures = {
                pool.submit(college_ai.ask, name, client, model, prompt, bool(context), limiter): (college, prompt, context, n)
                for college, prompt, context, n in jobs
            }
            for fut in as_completed(futures):
                college, prompt, context, n = futures[fut]
                try:
                    result = fut.result()
                except Exception as exc:  # keep going; report at the end
                    failed += 1
                    self.stderr.write(f"  !! {college.name}: {exc}")
                    continue
                AIAnswer.objects.create(college=college, question="all", prompt=prompt, context_sent=context,
                                        notes_used=n, model=result["model"], response=result)
                detail = (f"{name} {result['model']}, HubSpot notes fact-checked as context ({n} excerpts)" if n
                          else f"{name} {result['model']}, general knowledge only (no HubSpot notes)")
                parsed = result["parsed"]
                for key, field in FIELD_MAP.items():
                    if key in parsed:
                        set_field(college, field, str(parsed[key]).strip(), "ai", detail, force=opts["force"])
                done += 1
                self.stdout.write(f"  ok {college.name} ({college_ai.word_count(parsed.get('vibe', ''))}-word vibe"
                                  f"{', with HubSpot feedback' if 'hubspot_feedback' in parsed else ''})")
        self.stdout.write(self.style.SUCCESS(f"{done} colleges answered, {failed} failed"))
