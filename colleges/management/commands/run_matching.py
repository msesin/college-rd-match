"""Refresh students' results with the matching engine (sources/matching.py): each student's own results,
as they see them on the portal and admins see them on the Match tab. Run it after college data changes.

Usage:
    python manage.py run_matching                     # every student who submitted the form
    python manage.py run_matching --sample            # the fictional sample students
    python manage.py run_matching --student S-ABC123 --explain
    python manage.py run_matching --sample --no-ai    # no Gemini calls: saved judgements only

Step 1, with GEMINI_API_KEY in .env (sources/student_ai.py), saved to the database:
  - the profile ratings (school type, talent, activities, volunteering, work) of students whose answers changed;
  - the self-summary vs college vibe judgements of students whose summary is new or changed.
  Only sample students are sent unless .env has ALLOW_STUDENT_DATA_TO_GEMINI=1; others keep
  half points for those metrics until rated.
Step 2: the engine scores every student and college in code.
Output lists students by code only.
"""

import os

from django.core.management.base import BaseCommand, CommandError

from colleges.models import College, Student
from sources import college_ai, matching, student_ai


class Command(BaseCommand):
    help = "Ask Gemini for missing ratings, then refresh students' match results"

    def add_arguments(self, parser):
        parser.add_argument("--sample", action="store_true", help="Run for the fictional sample students")
        parser.add_argument("--student", action="append", help="Student code (repeatable)")
        parser.add_argument("--all", action="store_true", help="Every student, including those who have not submitted")
        parser.add_argument("--no-ai", action="store_true", help="Do not call Gemini; use saved judgements only")
        parser.add_argument("--rejudge", action="store_true", help="Ask Gemini again even if nothing changed")
        parser.add_argument("--explain", action="store_true", help="Print each student's list with the points")

    def handle(self, *args, **opts):
        if opts["student"]:
            students = list(Student.objects.filter(code__in=opts["student"]))
            missing = set(opts["student"]) - {s.code for s in students}
            if missing:
                raise CommandError(f"Unknown student code(s): {', '.join(sorted(missing))}")
        elif opts["sample"]:
            students = list(Student.objects.filter(cohort="sample"))
        elif opts["all"]:
            students = list(Student.objects.all())
        else:
            students = list(Student.objects.filter(submitted_at__isnull=False))
        if not students:
            raise CommandError("No students to match (students must submit the form first; or use --sample / --all)")

        if not opts["no_ai"]:
            self.ask_gemini(students, opts["rejudge"])

        out = matching.refresh_students(students)
        self.stdout.write(self.style.SUCCESS(f"Results refreshed: {len(students)} student(s) x {College.objects.count()} colleges"))
        if opts["explain"]:
            for st, (rows, lv) in out.items():
                self.explain(st, rows, lv)

    def ask_gemini(self, students, rejudge):
        name, model = college_ai.provider()
        if name != "gemini":
            self.stdout.write("No GEMINI_API_KEY: profiles and self-summaries are not rated (half points).")
            return
        client = college_ai.make_client(name)
        limiter = college_ai.RateLimiter(int(os.environ.get("LLM_RPM") or 15), 60)
        colleges = list(College.objects.select_related("profile"))
        for st in students:
            if not student_ai.allowed(st):
                self.stdout.write(f"{st.code}: not sent to Gemini (real student; ALLOW_STUDENT_DATA_TO_GEMINI not set)")
                continue
            if rejudge or student_ai.profile_needs_rating(st, model):
                read = student_ai.rate_profile(st, client, model, limiter)
                self.stdout.write(f"{st.code}: " + "; ".join(f"{k} {v['level']}" for k, v in read.items()))
            if rejudge and st.self_summary.strip() or student_ai.vibe_needs_judging(st, colleges, model):
                read = student_ai.judge_vibe(st, client, model, limiter)
                levels = {lvl: st.vibe_judgements.filter(level=lvl).count() for lvl in ("high", "moderate", "none")}
                self.stdout.write(f"{st.code}: self-summary ({', '.join(read['traits'])}): "
                                  f"high {levels['high']}, moderate {levels['moderate']}, none {levels['none']}")

    def explain(self, st, rows, lv):
        short = {"sat": "SAT", "rigor": "Rigor", "major": "Major", "character": "Char", "gpa": "GPA", "talent": "Talent",
                 "extracurricular": "EC", "class_rank": "Rank", "volunteer": "Vol", "work": "Work"}
        self.stdout.write(f"\n=== {st.code}  GPA: {lv['gpa'][0]} | class rank: {lv['class_rank'][0]} | coursework: "
                          f"{lv['coursework'][0]} | school: {st.school_type or '-'} | talent: {st.academic_tier or '-'} | "
                          f"EC: {st.ec_level or '-'} | volunteer: {st.volunteer_level or '-'} | work: {st.work_level or '-'}")
        self.stdout.write("    (preliminary match, before the crowding cut for UGS applicants)")
        for i, r in enumerate((r for r in rows if r.recommended), start=1):
            parts = " ".join(f"{short[k]} {r.d.points[k] * r.metrics[k].score:.1f}" for k in matching.ORDER)
            self.stdout.write(f"{i:2}. {r.match:5.1f}%  {r.d.college.name[:34]:34}  [{parts}]")
        n_other = sum(1 for r in rows if not r.excluded and not r.recommended)
        excluded = [r for r in rows if r.excluded]
        self.stdout.write(f"    + {n_other} other college(s); {len(excluded)} excluded:")
        for r in excluded:
            self.stdout.write(f"      x {r.d.college.name[:40]:40} {r.excluded}")
