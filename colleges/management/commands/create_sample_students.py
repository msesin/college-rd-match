"""Create fictional sample students to try the Students tab, the student portal and the matching engine.

Usage: python manage.py create_sample_students              (safe to re-run; resets the samples)
       python manage.py create_sample_students --demo-only  (resets only the demo student; for cron)
       python manage.py create_sample_students --delete

The people are invented. Their cohort is "sample" so they are easy to find and remove.
Each has full structured data (school, grades by subject on their school's scale, class rank, tests,
curriculum, majors, awards, activities, work), 12 college choices and a generated transcript image,
so they can open the portal and submit without changing anything. Re-running resets them to "not
submitted". The profile ratings (school type, talent, activities, volunteering, work) and the
self-summary ratings come from Gemini (run_matching --sample) and are kept while the texts are unchanged.
One of them is the public demo login (sources/demo.py; username and password in README.md); the others
have no login. Each gets the email <first name>.sample@example.com (use --email to give the second one a
real inbox, to test sign-up by email). Needs STUDENT_DATA_KEY in .env (names are stored encrypted).
"""

from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from colleges.models import CollegeChoice, Student, StudentFile, StudentIdentity
from sources import demo, matching
from sources.crypto import MissingKey, decrypt, email_fingerprint, encrypt
from sources.students import delete_student


def ua(**grades):
    """Ukrainian 12-point grades; keyword names use underscores for spaces."""
    return {k.replace("_", " "): v for k, v in grades.items()}


SAMPLES = [
    {
        "name": "Solomiya Solomiya", "pronouns": "she", "school_name": "Kyiv Natural Science Lyceum No. 145, Kyiv", "det_score": 140, "sat_score": 1490, "class_top_pct": 3,
        "curriculum": "no", "gpa_note": "Year 11 (2025-26), Ukrainian 12-point scale",
        "subject_grades": ua(Ukrainian_language=11, Ukrainian_literature=11, World_literature=11, English=12,
                             History_of_Ukraine=10, World_history=11, Algebra=12, Geometry=12, Physics=12,
                             Chemistry=11, Biology=11, Geography=11, Informatics=12, Economics=12),
        "transcript_note": "Mathematics lyceum; top marks in maths and physics every year.",
        "major_1": "Mathematics", "major_2": "Computer Science", "major_3": "Economics",
        "academic_note": "Silver medal, European Girls' Mathematical Olympiad 2025. 1st place, Ukrainian national maths "
                         "olympiad 2025; 2nd place 2024. Regional informatics olympiad winner 2024.",
        "activities": "Leader of the school maths circle (2023-now, 4 h/week): I prepare younger students for olympiads. "
                      "Volunteer maths tutor for displaced children online (2024-now, 2 h/week). Chess club.",
        "work_experience": "",
        "self_summary": "Ambitious and competitive; I love hard proofs and I lead my school's maths circle, where I "
                        "prepare younger students for olympiads. I like pushing myself and being around people who "
                        "push me back. I want a rigorous college with research opportunities from the first year, "
                        "where I can study mathematics deeply and also learn how it is used in economics and computing.",
    },
    {
        "name": "Andrii Melnyk", "pronouns": "he", "school_name": "Secondary School No. 12, Bila Tserkva", "det_score": 125, "sat_score": None, "class_top_pct": 10,
        "curriculum": "no", "gpa_note": "Year 11 (2025-26), Ukrainian 12-point scale",
        "subject_grades": ua(Ukrainian_language=11, Ukrainian_literature=12, World_literature=12, English=10,
                             History_of_Ukraine=12, World_history=12, Law=11, Algebra=9, Geometry=9, Physics=9,
                             Chemistry=10, Biology=10, Geography=11, Informatics=10),
        "transcript_note": "Strong in humanities; studied online for two years during displacement.",
        "major_1": "Political Science", "major_2": "History", "major_3": "Philosophy",
        "academic_note": "Regional history olympiad finalist 2025.",
        "activities": "Founder and coordinator of a volunteer group supporting displaced families in my town (2023-now, "
                      "8 h/week; 15 volunteers, 40 families helped). Captain of the school debate club (2024-now).",
        "work_experience": "Weekend shifts at a grocery store to help my family (2024-now, 10 h/week).",
        "self_summary": "A philosophical, global thinker who asks why before how. Since my family had to move, I organise "
                        "people around causes: our volunteer group now helps forty families. I read history and political "
                        "philosophy for fun. I want small discussion-based classes and a community that cares about the world.",
    },
    {
        "name": "Sofiia Bondarenko", "pronouns": "she", "school_name": "Pechersk School International, Kyiv", "det_score": 135, "sat_score": 1400, "class_top_pct": None,
        "curriculum": "ib", "gpa_note": "IB Diploma, predicted grades",
        "subject_grades": {"Biology HL": 7, "Chemistry HL": 6, "English A HL": 6, "Mathematics AA SL": 5,
                           "History SL": 6, "Ukrainian A SL": 7, "Core (TOK/EE)": 2},
        "transcript_note": "International school in Kyiv; the school does not rank students.",
        "major_1": "Biology", "major_2": "Neuroscience", "major_3": "",
        "academic_note": "National biology olympiad, 3rd degree diploma 2025. Summer research project on plant stress "
                         "responses at a university lab (2025).",
        "activities": "School choir soloist (2021-now, 3 h/week). Biology club member. Helped at a school charity "
                      "fair once a year.",
        "work_experience": "",
        "self_summary": "Curious and collaborative; I am happiest in a lab team, asking questions and testing them. I sing in "
                        "a choir and I like quiet, supportive places more than competitive ones. I want a close-knit college "
                        "where I can do undergraduate research and still have time for music.",
    },
    {
        "name": "Maksym Shevchenko", "pronouns": "he", "school_name": "Lviv Physics and Mathematics Lyceum, Lviv", "det_score": 130, "sat_score": 1520, "class_top_pct": 5,
        "curriculum": "no", "gpa_note": "Year 11 (2025-26), Ukrainian 12-point scale",
        "subject_grades": ua(Ukrainian_language=10, Ukrainian_literature=9, World_literature=10, English=11,
                             History_of_Ukraine=10, World_history=10, Algebra=12, Geometry=12, Physics=12,
                             Chemistry=10, Biology=10, Geography=10, Informatics=12),
        "transcript_note": "Physics and maths lyceum; perfect marks in STEM subjects.",
        "major_1": "Engineering", "major_2": "Physics", "major_3": "Computer Science",
        "academic_note": "National physics olympiad finalist 2025. Regional physics olympiad 1st place 2024 and 2025.",
        "activities": "Robotics team, lead engineer (2023-now, 6 h/week): we built a drone navigation project with a "
                      "university lab. Repair workshop for classmates' devices.",
        "work_experience": "Summer assistant at a local electronics repair shop (2025, 2 months, 20 h/week).",
        "self_summary": "A hands-on team player who likes building things that work. I spend evenings in our school "
                        "workshop and I enjoy helping classmates fix their projects. I want a practical, collaborative "
                        "STEM college where students help each other rather than compete.",
    },
    {
        "name": "Dmytro Lysenko", "pronouns": "he", "school_name": "Secondary School No. 7, Kremenchuk", "det_score": 120, "sat_score": 1250, "class_top_pct": 35,
        "curriculum": "no", "gpa_note": "Year 11 (2025-26), Ukrainian 12-point scale",
        "subject_grades": ua(Ukrainian_language=8, Ukrainian_literature=8, World_literature=9, English=9,
                             History_of_Ukraine=9, World_history=9, Algebra=9, Geometry=8, Physics=8, Chemistry=7,
                             Biology=8, Geography=9, Informatics=10, Economics=11),
        "transcript_note": "General school; no advanced courses offered.",
        "major_1": "Business", "major_2": "Economics", "major_3": "Accounting",
        "academic_note": "School economics competition winner 2025. Took part in an online national business case "
                         "contest (no award).",
        "activities": "School football team (2022-now). Occasionally help at church events.",
        "work_experience": "Run a small business reselling refurbished phones to classmates (2024-now, about 6 h/week). "
                           "Help in my uncle's car parts shop in summers.",
        "self_summary": "Practical and outgoing. I resell refurbished phones to classmates and I like sales and numbers "
                        "more than theory. I want a friendly college with strong business connections and internships.",
    },
    {
        "name": "Iryna Tkachenko", "pronouns": "she", "school_name": "American School of Warsaw, Poland", "det_score": None, "sat_score": 1380, "class_top_pct": 15,
        "curriculum": "ap", "gpa": Decimal("3.50"), "gpa_note": "American school in Warsaw since 2022, unweighted GPA",
        "subject_grades": {"AP US Government": "A", "AP World History": "A-", "AP Macroeconomics": "B+",
                           "English 11": "A", "Precalculus": "B", "Chemistry": "B+", "Spanish III": "A-",
                           "Physics": "B"},
        "transcript_note": "AP exams: US Government 5, World History 4, Macroeconomics 4.",
        "major_1": "International Relations", "major_2": "Political Science", "major_3": "Economics",
        "academic_note": "Best Delegate at two regional Model UN conferences (2024, 2025). Finalist, national essay "
                         "competition on European integration (2025).",
        "activities": "Chair of the school Model UN club (2023-now, 5 h/week; organised a conference for 200 students). "
                      "Volunteer at a Ukrainian refugee centre in Warsaw (2022-now, weekly): translation and children's "
                      "activities.",
        "work_experience": "",
        "self_summary": "A debater and organiser who chairs my school's Model UN. Sociable and diplomatic, a bit scattered: "
                        "I start too many projects at once. I want a college near a big city with internships in "
                        "international organisations.",
    },
    {
        "name": "Nazar Hrytsenko", "pronouns": "he", "school_name": "British International School, Kyiv", "det_score": 150, "sat_score": 1560, "class_top_pct": 1,
        "curriculum": "alevels", "gpa_note": "A-level predicted grades",
        "subject_grades": {"Mathematics": "A*", "Further Mathematics": "A*", "Physics": "A*", "Computer Science": "A"},
        "transcript_note": "British curriculum school in Kyiv.",
        "major_1": "Physics", "major_2": "Mathematics", "major_3": "Computer Science",
        "academic_note": "Gold medal, International Physics Olympiad 2026. Silver medal, European Physics Olympiad 2025. "
                         "Co-author of a paper on plasma simulation with a university group (2025).",
        "activities": "Physics olympiad training, self-study (10+ h/week). Astronomy club.",
        "work_experience": "",
        "self_summary": "Quiet, intensely curious and self-driven. I read physics papers for fun and spend weekends on "
                        "numerical simulations. I prefer a few deep friendships and long problem sets to big parties, and "
                        "want professors who take undergraduates into their labs.",
    },
    {
        "name": "Kateryna Marchenko", "pronouns": "she", "school_name": "Gymnasium No. 1, Zhytomyr", "det_score": 135, "sat_score": 1420, "class_top_pct": 8,
        "curriculum": "no", "gpa_note": "Year 11 (2025-26), Ukrainian 12-point scale",
        "subject_grades": ua(Ukrainian_language=11, Ukrainian_literature=12, World_literature=12, English=12,
                             History_of_Ukraine=11, World_history=11, Law=11, Algebra=10, Geometry=10, Physics=9,
                             Chemistry=8, Biology=8, Geography=10, Informatics=11, Art=12),
        "transcript_note": "Good overall, but science grades are the weakest.",
        "major_1": "Biology", "major_2": "Psychology", "major_3": "Chemistry",
        "academic_note": "2nd place, school biology olympiad 2025. Regional youth painting competition, 1st place 2024.",
        "activities": "Volunteer at an animal shelter (2022-now, every weekend). Art studio (2019-now, 4 h/week); my "
                      "paintings were shown at a city exhibition.",
        "work_experience": "Look after my two younger brothers after school while my mother works (daily).",
        "self_summary": "Empathetic and artistic: I paint, I volunteer with animals, and I want to understand how living "
                        "things work. I learn best by doing and by talking things through with friends. I want a warm, "
                        "creative college community where I can explore before I choose.",
    },
]

# Earlier names of sample students: a reset renames them instead of creating a second student.
RENAMED = {"Olena Kovalenko": "Solomiya Solomiya"}

DEFAULTS = {"gpa": None, "class_top_pct": None, "notes": "", "submitted_at": None}


def previous_year(grades):
    """A made-up year before, close to the latest one: some numeric grades one lower; letter grades as they are."""
    out = {}
    for i, (subject, grade) in enumerate(grades.items()):
        if subject.lower().startswith("core"):
            continue
        out[subject] = max(1, grade - 1) if isinstance(grade, int) and i % 3 == 1 else grade
    return out


def sample_choices(student, colleges, n=12):
    """The colleges the student can apply to (no hard rule against them) whose top programs fit the student's
    majors best. With fewer than n of those (a short list, like the demo's), the others fill it up, last."""
    levels = matching.student_levels(student)
    fits, others = [], []
    for d in colleges.values():
        row = matching.score(student, d, levels)
        if not row.excluded:
            fits.append((-row.metrics["major"].score, d.college.name, d))
        else:
            others.append((d.college.name, d))
    chosen = [d.college for _, _, d in sorted(fits)[:n]]
    return chosen + [d.college for _, d in sorted(others)[:n - len(chosen)]]


def write_transcript(student):
    """A plain image listing the sample student's grades, clearly marked as fictional."""
    from PIL import Image, ImageDraw, ImageFont

    rows = [("FICTIONAL SAMPLE STUDENT - NOT A REAL TRANSCRIPT", ""), ("", ""), ("Student", student.code),
            ("Curriculum", "National curriculum" if student.curriculum == "no" else student.get_curriculum_display()),
            ("Grades", student.gpa_note), ("", "")]
    rows += [(subject, str(grade)) for subject, grade in student.subject_grades.items()]
    if student.class_top_pct is not None:
        rows += [("", ""), ("Class rank", f"top {student.class_top_pct:g}%")]
    font = ImageFont.load_default(size=20)
    img = Image.new("RGB", (1000, 70 + 32 * len(rows)), "white")
    draw = ImageDraw.Draw(img)
    for i, (left, right) in enumerate(rows):
        draw.text((40, 35 + 32 * i), left, fill="black", font=font)
        draw.text((520, 35 + 32 * i), right, fill="black", font=font)
    folder = settings.STUDENT_FILES_DIR / student.code
    folder.mkdir(parents=True, exist_ok=True)
    img.save(folder / "sample_transcript.png")
    StudentFile.objects.create(student=student, kind="transcript", file_path=f"{student.code}/sample_transcript.png",
                               original_name="sample_transcript.png")


class Command(BaseCommand):
    help = "Create, reset or delete the fictional sample students, and the public demo login"

    def add_arguments(self, parser):
        parser.add_argument("--delete", action="store_true", help="Delete the sample students (and the demo login)")
        parser.add_argument("--demo-only", action="store_true",
                            help="Only reset the demo student (for cron: undoes what visitors changed)")
        parser.add_argument("--email", help=f"Give {SAMPLES[1]['name']} this email (to test sign-up with a real inbox)")

    def handle(self, *args, **opts):
        samples = Student.objects.filter(cohort="sample")
        if opts["delete"]:
            n = samples.count()
            for st in samples:
                delete_student(st)
            self.stdout.write(self.style.SUCCESS(f"{n} sample students deleted"))
            return
        existing = {decrypt(s.identity.name_encrypted): s for s in samples.select_related("identity") if hasattr(s, "identity")}
        for old, new in RENAMED.items():
            if old in existing and new not in existing:
                existing[new] = existing.pop(old)
        colleges = matching.load_colleges()
        for i, data in enumerate(SAMPLES):
            data = {**DEFAULTS, **data}
            data.setdefault("subject_grades_prev", previous_year(data.get("subject_grades", {})))
            name = data.pop("name")
            if opts["demo_only"] and name != demo.DEMO_STUDENT:
                continue
            try:
                token = encrypt(name)
            except MissingKey as exc:
                raise CommandError(str(exc))
            st = existing.get(name) or Student.objects.create(cohort="sample")
            for field, value in data.items():
                setattr(st, field, value)
            st.save()
            identity, _ = StudentIdentity.objects.get_or_create(student=st)
            identity.name_encrypted = token
            email = (opts["email"] if opts["email"] and i == 1 else None) or f"{name.split()[0].lower()}.sample@example.com"
            identity.email_encrypted = encrypt(email)
            identity.email_hash = email_fingerprint(email)
            identity.save()

            # 12 college choices and a transcript, so the form can be submitted as it is
            st.choices.all().delete()
            pool = colleges
            if name == demo.DEMO_STUDENT and demo.demo_college_ids():   # the public demo only sees its 15 colleges
                pool = {k: d for k, d in colleges.items() if k in demo.demo_college_ids()}
            CollegeChoice.objects.bulk_create([CollegeChoice(student=st, college=c, rank=rank)
                                               for rank, c in enumerate(sample_choices(st, pool), start=1)])
            for f in st.files.all():
                path = (settings.STUDENT_FILES_DIR / f.file_path).resolve()
                if settings.STUDENT_FILES_DIR.resolve() in path.parents and path.exists():
                    path.unlink()
                f.delete()
            write_transcript(st)

            if name == demo.DEMO_STUDENT:
                self.demo_login(st)
            elif st.user_id:   # only the demo student has a login
                user, st.user = st.user, None
                st.save(update_fields=["user"])
                if not user.is_staff:
                    user.delete()
        if opts["demo_only"]:
            self.stdout.write(self.style.SUCCESS(f"Demo student reset (login: {demo.DEMO_USERNAME})"))
        else:
            self.stdout.write(self.style.SUCCESS(f"{len(SAMPLES)} sample students ready (cohort 'sample'), not submitted"))
            self.stdout.write(f"Demo login: {demo.DEMO_USERNAME} / {demo.DEMO_PASSWORD} ({demo.DEMO_STUDENT}, fictional)")

    def demo_login(self, st):
        """The public demo login, with the password from README.md; set again on every reset."""
        user = st.user or User.objects.filter(username=demo.DEMO_USERNAME).first()
        if user and user.is_staff:
            raise CommandError(f"The staff account '{user.username}' cannot be the demo login.")
        user = user or User(username=demo.DEMO_USERNAME)
        user.username = demo.DEMO_USERNAME
        try:
            validate_password(demo.DEMO_PASSWORD, user)
        except ValidationError as exc:
            raise CommandError("The demo password does not pass the password rules: " + " ".join(exc.messages))
        user.set_password(demo.DEMO_PASSWORD)
        user.save()
        if st.user_id != user.pk:
            st.user = user
            st.save(update_fields=["user"])
