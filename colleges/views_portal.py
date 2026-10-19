"""Student side: sign-up by email, the profile form, transcript uploads, and results.

A student only ever sees their own Student record (request.user.student). The
middleware keeps students inside /portal/. After submitting, Gemini rates the profile in the background
(sources/student_ai.py, sample students only unless allowed); the match itself is computed here in code.
"""

import hashlib
import re
import secrets
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from colleges.forms import SubjectGradesField
from colleges.models import College, CollegeChoice, CollegeProfile, Student, StudentFile, StudentIdentity
from sources import accounts, college_ai, demo, matching, student_ai, transcript
from sources.crypto import email_fingerprint, encrypt, normalise_email

N_CHOICES = 20      # colleges a student can list (on the form and afterwards)
N_RECOMMENDED = 12  # UGS college counseling recommends 12 at first; at least 12 to submit
ALLOWED_UPLOADS = {".png", ".jpg", ".jpeg", ".pdf", ".heic", ".heif", ".webp"}
EDIT_EVERY_DAYS = 7     # after submitting, a student may reopen their profile once a week (decision 52)
OCR_RUNS_PER_DAY = 10   # "Click to autofill" (from a transcript) per student per day (each run may use the precise model)


# ---------------------------------------------------------------- sign-up

class EmailForm(forms.Form):
    email = forms.EmailField(label="Your email address", help_text="The address UGS has on file for you.")


@login_not_required
def register(request):
    """Step 1: the student enters their email; if it is on the list, a one-time link is emailed."""
    form = EmailForm(request.POST or None)
    domains = accounts.allowed_domains()
    if domains:
        form.fields["email"].help_text = "Your " + " or ".join(f"@{d}" for d in domains) + " email address."
    if request.method == "POST" and form.is_valid() and not accounts.domain_allowed(form.cleaned_data["email"]):
        form.add_error("email", "Only " + " or ".join(f"@{d}" for d in domains) + " addresses can sign up.")
    if request.method == "POST" and form.is_valid():
        email = normalise_email(form.cleaned_data["email"])
        student, allowed = accounts.eligible(email)
        if allowed:
            link = request.build_absolute_uri(f"/register/{accounts.make_token(email, student)}/")
            existing = bool(student and student.user_id)
            send_mail(
                "Your UGS College Counseling link",
                render_template_text("colleges/portal/email_link.txt", {
                    "link": link, "existing": existing, "username": student.user.username if existing else "",
                    "hours": accounts.TOKEN_MAX_AGE // 3600,
                }),
                settings.DEFAULT_FROM_EMAIL, [email],
            )
        # Same answer either way, so the page never reveals who is on the list.
        return render(request, "colleges/portal/register_sent.html", {"email": email})
    return render(request, "colleges/portal/register.html", {"form": form, "domains": domains})


def render_template_text(name, context):
    from django.template.loader import render_to_string

    return render_to_string(name, context)


class SetPasswordForm(forms.Form):
    first_name = forms.CharField(max_length=100, required=False)
    last_name = forms.CharField(max_length=100, required=False)
    password1 = forms.CharField(label="Choose a password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Repeat the password", widget=forms.PasswordInput)

    def __init__(self, *args, need_name=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.need_name = need_name
        if need_name:
            self.fields["first_name"].required = True
            self.fields["last_name"].required = True
        else:
            del self.fields["first_name"], self.fields["last_name"]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password1") != cleaned.get("password2"):
            raise ValidationError("The two passwords are different.")
        if cleaned.get("password1"):
            validate_password(cleaned["password1"])
        return cleaned


@login_not_required
def register_confirm(request, token):
    """Step 2: from the emailed link, the student sets a password (and gets their username)."""
    try:
        email, student = accounts.read_token(token)
    except signing.BadSignature:
        return render(request, "colleges/portal/register_invalid.html", status=400)
    if not accounts.domain_allowed(email):   # a link sent before the domain rule was set
        return render(request, "colleges/portal/register_invalid.html", status=400)

    existing_user = student.user if student and student.user_id else None
    name = accounts.stored_name(student) if student else ""
    first, last = accounts.split_name(name)
    need_name = existing_user is None and not (first and last)
    form = SetPasswordForm(request.POST or None, need_name=need_name)

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            if need_name:
                first, last = form.cleaned_data["first_name"].strip(), form.cleaned_data["last_name"].strip()
            if student is None:
                student = Student.objects.create()
                StudentIdentity.objects.create(
                    student=student, name_encrypted=encrypt(f"{first} {last}"),
                    email_encrypted=encrypt(email), email_hash=email_fingerprint(email))
            elif need_name:
                identity, _ = StudentIdentity.objects.get_or_create(student=student)
                identity.name_encrypted = encrypt(f"{first} {last}")
                identity.save()
            user = existing_user or User.objects.create_user(username=accounts.make_username(first, last))
            user.set_password(form.cleaned_data["password1"])
            user.save()
            if student.user_id != user.pk:
                student.user = user
                student.save(update_fields=["user"])
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return redirect("/portal/")

    username_preview = existing_user.username if existing_user else (
        accounts.make_username(first, last) if (first and last) else "")
    return render(request, "colleges/portal/register_confirm.html", {
        "form": form, "username": username_preview, "existing": bool(existing_user),
    })


# ---------------------------------------------------------------- portal

class RankField(forms.TypedChoiceField):
    """Class rank as one of the levels (top 1%, 5%, 10%, 25%, 50%, or not in the top half); stored as that number."""

    def __init__(self, *args, **kwargs):
        from sources.transcript import RANK_CHOICES

        for k in ("max_value", "min_value", "step_size", "localize", "required", "empty_value", "coerce", "choices"):
            kwargs.pop(k, None)
        super().__init__(*args, choices=[("", "Not ranked / I don't know")] + RANK_CHOICES, coerce=float,
                         empty_value=None, required=False, **kwargs)

    def prepare_value(self, value):
        from sources.transcript import rank_bucket

        return rank_bucket(float(value)) if value not in (None, "") else ""


class PortalForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = ["pronouns", "school_name", "det_score", "sat_score", "curriculum", "subject_grades", "subject_grades_prev",
                  "gpa", "gpa_note", "class_top_pct", "transcript_note", "major_1", "major_2", "major_3", "academic_note", "activities",
                  "work_experience", "self_summary"]
        field_classes = {"subject_grades": SubjectGradesField, "subject_grades_prev": SubjectGradesField,
                         "class_top_pct": RankField}
        labels = {
            "pronouns": "Pronouns", "school_name": "Your school and its city", "det_score": "Duolingo English Test score", "sat_score": "SAT score (if you took it)",
            "subject_grades": "Your grades by subject: latest school year",
            "subject_grades_prev": "Your grades by subject: the school year before",
            "gpa": "GPA on a 4.0 scale (if you know it)", "gpa_note": "Your average grade as on your transcript",
            "class_top_pct": "Class rank: top what %?", "transcript_note": "Anything we should know about your grades",
            "major_1": "First choice of major", "major_2": "Second choice", "major_3": "Third choice",
            "curriculum": "Does your school follow IB, AP or A-levels?",
            "academic_note": "Awards, olympiads, competitions and research",
            "activities": "Activities and volunteering", "work_experience": "Work experience",
            "self_summary": "Describe yourself (300 words or less)",
        }
        help_texts = {
            "gpa_note": "For example: 11.4 / 12, Ukrainian scale.",
            "class_top_pct": "Your place in your class by grades. Leave it empty if your school does not rank.",
            "school_name": "The full name, as on your transcript, e.g. 'Lyceum No. 145, Kyiv'.",
            "academic_note": "List results with level and year, e.g. 'National physics olympiad, 2nd place, 2025'.",
            "activities": "Clubs, sports, arts, projects and volunteering: what you did, your role, how long and how many "
                          "hours a week.",
            "work_experience": "Paid or family work, internships: what, how long and how many hours a week. Leave empty "
                               "if none.",
            "self_summary": "Your character, interests and what you want from a college. We match this with each college's culture.",
        }
        widgets = {
            "transcript_note": forms.Textarea(attrs={"rows": 3}),
            "academic_note": forms.Textarea(attrs={"rows": 4}),
            "activities": forms.Textarea(attrs={"rows": 5}),
            "work_experience": forms.Textarea(attrs={"rows": 3}),
            "self_summary": forms.Textarea(attrs={"rows": 5}),
        }


def _student(request):
    student = getattr(request.user, "student", None)
    if student is None:
        raise Http404("No student profile is linked to this account.")
    return student


def _word_count(text):
    return len(re.findall(r"\b\w[\w'’-]*\b", text or ""))


# The review form: every answer is shown as saved, with an Edit button that opens its input.
REVIEW_FIELDS = PortalForm.Meta.fields


def _required(curriculum):
    """Answers needed to submit. DET only for national-curriculum schools: IB, AP and A-levels students are exempt."""
    required = {"pronouns", "school_name", "curriculum", "major_1", "self_summary"}
    if curriculum in ("", "no"):
        required.add("det_score")
    return required


def _shown(student):
    """Each saved answer as it reads on the review form ('' when there is none)."""
    from sources.transcript import format_grades

    def text(value):
        return "" if value is None else str(value)

    return {
        "pronouns": student.get_pronouns_display() if student.pronouns else "", "school_name": student.school_name,
        "det_score": text(student.det_score), "sat_score": text(student.sat_score),
        "curriculum": student.get_curriculum_display() if student.curriculum else "",
        "subject_grades": format_grades(student.subject_grades),
        "subject_grades_prev": format_grades(student.subject_grades_prev),
        "gpa": text(student.gpa), "gpa_note": student.gpa_note,
        "class_top_pct": (dict(transcript.RANK_CHOICES).get(transcript.rank_bucket(student.class_top_pct), "")
                          if student.class_top_pct is not None else ""),
        "transcript_note": student.transcript_note, "major_1": student.major_1, "major_2": student.major_2,
        "major_3": student.major_3, "academic_note": student.academic_note, "activities": student.activities,
        "work_experience": student.work_experience, "self_summary": student.self_summary,
    }


def _review_fields(form, student, reopen=()):
    """{name: {"bf", "shown", "grades", "empty", "required", "open"}}: an empty required answer and any answer in
    `reopen` (changed or wrong after a failed submit) start open."""
    curriculum = form.data.get("curriculum", "") if form.is_bound else student.curriculum
    required, shown = _required(curriculum), _shown(student)
    return {name: {"bf": form[name], "shown": shown[name], "empty": not shown[name], "required": name in required,
                   "grades": list(getattr(student, name).items()) if name in ("subject_grades", "subject_grades_prev") else None,
                   "open": (not shown[name] and name in required) or name in reopen}
            for name in REVIEW_FIELDS}


def _read_choices(post, colleges, n=N_CHOICES):
    """[(rank, College or None)] from the form's rows college_1 ... college_n."""
    rows = []
    for rank in range(1, n + 1):
        unitid = post.get(f"college_{rank}", "")
        rows.append((rank, colleges.get(int(unitid)) if unitid.isdigit() else None))
    return rows


def _save_list(student, choices):
    CollegeChoice.objects.bulk_create([CollegeChoice(student=student, college=c, rank=i)
                                       for i, c in enumerate([c for _, c in choices if c], start=1)])


def _refresh_matches(student):
    """The student's preliminary matches now; returns a callable that redoes them (after Gemini's ratings).
    Crowding needs nothing here: it is applied from the current lists whenever results are shown."""
    pk = student.pk
    matching.refresh_students(Student.objects.filter(pk=pk))
    return lambda: matching.refresh_students(Student.objects.filter(pk=pk))


def _save_uploads(student, files):
    """Save uploaded transcript files: (errors, [StudentFile]). The file's content must be a photo or a PDF too,
    not only its name."""
    from sources.ocr import sniff_mime

    errors, saved = [], []
    folder = settings.STUDENT_FILES_DIR / student.code
    for f in files:
        ext = Path(f.name).suffix.lower()
        if ext not in ALLOWED_UPLOADS:
            errors.append(f"{f.name}: only photos (PNG, JPG, HEIC, WEBP) and PDF files can be uploaded.")
            continue
        head = f.read(16)
        f.seek(0)
        if sniff_mime(head + b"\0" * 16) is None:
            errors.append(f"{f.name}: this file is not a photo or a PDF inside (try saving it again as PDF or JPG).")
            continue
        if f.size > settings.STUDENT_UPLOAD_MAX_MB * 1024 * 1024:
            errors.append(f"{f.name}: larger than {settings.STUDENT_UPLOAD_MAX_MB} MB.")
            continue
        folder.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(f.name).stem)[:60] + ext
        stored = f"{timezone.now():%Y%m%d%H%M%S}_{secrets.token_hex(3)}_{safe}"
        with open(folder / stored, "wb") as out:
            for chunk in f.chunks():
                out.write(chunk)
        saved.append(StudentFile.objects.create(student=student, kind="transcript", file_path=f"{student.code}/{stored}",
                                                original_name=f.name[:255]))
    return errors, saved


def _colleges_for(student):
    """{unitid: College} the student can see and choose (the public demo: its 15 colleges only)."""
    visible = demo.visible_college_ids(student)
    qs = College.objects.order_by("name")
    return {c.unitid: c for c in (qs.filter(unitid__in=visible) if visible is not None else qs)}


def portal(request):
    student = _student(request)
    colleges = _colleges_for(student)
    errors = []
    form = PortalForm(instance=student)
    choices = [(c.rank, c.college) for c in student.choices.select_related("college")]

    if request.method == "POST" and student.submitted_at and request.POST.get("action") == "save_list":
        # After submitting: the student keeps their list up to date (any number of colleges).
        n = min(int(request.POST.get("n_rows", "0") or 0), N_CHOICES)
        choices = _read_choices(request.POST, colleges, n)
        picked = [c.unitid for _, c in choices if c]
        if not picked:
            errors.append("Keep at least one college on your list.")
        if int(request.POST.get("n_rows", "0") or 0) > N_CHOICES:
            errors.append(f"Your list can have at most {N_CHOICES} colleges.")
        if len(picked) != len(set(picked)):
            errors.append("Each college can be on your list only once.")
        if not errors:
            with transaction.atomic():
                student.choices.all().delete()
                _save_list(student, choices)
            return redirect("/portal/?saved=list")

    if request.method == "POST" and not student.submitted_at:
        action = request.POST.get("action")
        form = PortalForm(request.POST, instance=student)
        choices = _read_choices(request.POST, colleges)
        picked = [c.unitid for _, c in choices if c]
        if len(picked) != len(set(picked)):
            errors.append("Each college can be chosen only once.")
        if demo.is_demo(student):
            if request.FILES.getlist("transcripts"):
                errors.append("Uploads are turned off in the demo; it already has a sample transcript.")
        else:
            errors += _save_uploads(student, request.FILES.getlist("transcripts"))[0]

        if action == "submit":
            data = form.data
            if not data.get("pronouns"):
                errors.append("Please choose your pronouns.")
            if not data.get("det_score") and "det_score" in _required(data.get("curriculum", "")):
                errors.append("Please enter your Duolingo English Test score (not needed at IB, AP or A-levels schools).")
            if not data.get("major_1"):
                errors.append("Please enter at least your first choice of major.")
            if not data.get("curriculum"):
                errors.append("Please answer the IB, AP or A-levels question.")
            if not data.get("self_summary"):
                errors.append("Please describe yourself.")
            minimum = min(N_RECOMMENDED, len(colleges))   # a smaller college list needs them all
            if len(picked) < minimum:
                errors.append(f"Please choose at least {minimum} colleges (you chose {len(set(picked))}).")
            if not data.get("school_name"):
                errors.append("Please enter the name of your school.")
            if not student.files.exists():
                errors.append("Please upload your transcript.")
        if _word_count(request.POST.get("self_summary")) > 300:
            errors.append("Your description is longer than 300 words.")

        if form.is_valid() and not errors:
            with transaction.atomic():
                form.save()
                student.choices.all().delete()
                _save_list(student, choices)
                if action == "submit":
                    student.submitted_at = timezone.now()
                    student.save(update_fields=["submitted_at"])
            if action == "submit":
                # Gemini rates the student's texts first, so the first match uses the ratings (about 10 seconds).
                # If it is skipped or fails, results come right away and a background retry updates them later.
                # Not for the public demo: its saved ratings are used as they are.
                rated = not demo.is_demo(student) and student_ai.process_on_submit(student)
                refresh = _refresh_matches(student)
                if not rated and not demo.is_demo(student):
                    student_ai.rate_in_background(student, then=refresh)
                return redirect("/portal/matches/?submitted=1")
            return redirect("/portal/?saved=draft")

    rows = dict(choices)
    saved = {c.rank: c.college_id for c in student.choices.all()}
    reopen = set(form.changed_data) | set(form.errors) if form.is_bound else set()
    choice_rows = [(r, rows.get(r)) for r in range(1, N_CHOICES + 1)]
    return render(request, "colleges/portal/portal.html", {
        "student": student, "username": request.user.username, "name": accounts.stored_name(student),
        "form": form, "errors": errors, "files": student.files.all(),
        "fields": _review_fields(form, student, reopen),
        "choice_edit": [{"rank": r, "college": c, "open": c is None or saved.get(r) != c.unitid} for r, c in choice_rows],
        "colleges": colleges.values(), "has_results": bool(student.submitted_at) and matching.latest_run(student) is not None,
        "n_choices": N_CHOICES, "n_recommended": N_RECOMMENDED, "n_minimum": min(N_RECOMMENDED, len(colleges)),
        "more_open": any(c for r, c in choice_rows if r > N_RECOMMENDED),
        "autofill": student_ai.allowed(student) and college_ai.provider()[0] == "gemini",
        "my_list": [c.college for c in student.choices.select_related("college").order_by("rank")],
        "saved": request.GET.get("saved"), "max_mb": settings.STUDENT_UPLOAD_MAX_MB,
        "next_edit_at": next_edit_at(student), "edit_every_days": EDIT_EVERY_DAYS,
        "reopened": bool((student.attributes or {}).get("reopens")) and not student.submitted_at,
        "lock_until": edit_lock_until(student),
    })


def portal_matches(request):
    """The student's results: their best matches, the other colleges and the excluded ones, with the reasons.
    The match shown is the final one, after the crowding cut from the current lists."""
    student = _student(request)
    run = matching.latest_run(student) if student.submitted_at else None
    if run is None:
        return redirect("/portal/")
    visible = demo.visible_college_ids(student)
    results = run.results.filter(student=student).select_related("college")
    rows = matching.with_crowding(results.filter(college_id__in=visible) if visible is not None else results)
    mine = {c.college_id: c.rank for c in student.choices.all()}
    profiles = {p.college_id: p for p in CollegeProfile.objects.filter(college_id__in=[x["r"].college_id for x in rows])}
    for x in rows:
        x["choice"], x["profile"] = mine.get(x["r"].college_id), profiles.get(x["r"].college_id)
    return render(request, "colleges/portal/matches.html", {
        "student": student, "name": accounts.stored_name(student), "run": run, "top_n": matching.LIST_SIZE,
        "rows": [x for x in rows if not x["r"].excluded], "excluded": [x for x in rows if x["r"].excluded],
        "n_mine": sum(1 for x in rows if x["choice"] and not x["r"].excluded), "has_results": True,
        "ugs_years": _ugs_years(), "n_list": len(mine), "max_list": N_CHOICES, "error": request.GET.get("error", ""),
        "pending": (student.attributes or {}).get("ai_pending"), "submitted": request.GET.get("submitted"),
        "state": _matches_state(student, run),
    })


def _ugs_years():
    from sources import ugs_history

    stored = ugs_history.stored_table()
    return f"{stored['years'][0]}-{stored['years'][-1]}" if stored else "UGS's admissions results"


def _matches_state(student, run):
    return f"{run.pk}:{matching.crowding_state()}:{(student.attributes or {}).get('ai_pending', '')}"


def portal_matches_state(request):
    """A short token that changes whenever the student's matches would look different; the page polls it."""
    from django.http import JsonResponse

    student = _student(request)
    run = matching.latest_run(student) if student.submitted_at else None
    return JsonResponse({"state": _matches_state(student, run) if run else ""})


def portal_file(request, pk):
    student = _student(request)
    f = get_object_or_404(StudentFile, pk=pk, student=student)
    base = settings.STUDENT_FILES_DIR.resolve()
    path = (base / f.file_path).resolve()
    if base not in path.parents or not path.exists():
        raise Http404
    return FileResponse(open(path, "rb"), filename=f.original_name or path.name)


@require_POST
def portal_list_change(request):
    """Add a college to the end of the student's list, or remove one, from the matches table (after submitting).
    The same limits as the list editor: at most N_CHOICES colleges, at least one. Crowding needs no rerun."""
    from django.http import JsonResponse

    student = _student(request)
    college = College.objects.filter(unitid=int(request.POST.get("college") or 0)).first()
    action = request.POST.get("action")
    error = ""
    if not student.submitted_at:
        error = "Submit your application first; until then, choose colleges on the My application tab."
    elif college is None or action not in ("add", "remove"):
        error = "Something went wrong. Please reload the page."
    elif action == "add" and college.unitid not in _colleges_for(student):
        error = "This college is not part of the demo."
    else:
        with transaction.atomic():
            ids = list(student.choices.order_by("rank").values_list("college_id", flat=True))
            if action == "add" and college.unitid not in ids:
                if len(ids) >= N_CHOICES:
                    error = f"Your list already has {N_CHOICES} colleges, the most it can have. Remove one first."
                else:
                    ids.append(college.unitid)
            elif action == "remove" and college.unitid in ids:
                if len(ids) == 1:
                    error = "Keep at least one college on your list."
                else:
                    ids.remove(college.unitid)
            if not error:
                student.choices.all().delete()
                CollegeChoice.objects.bulk_create([CollegeChoice(student=student, college_id=c, rank=i)
                                                   for i, c in enumerate(ids, start=1)])
    if request.headers.get("Accept") == "application/json":
        return JsonResponse({"ok": not error, "error": error}, status=400 if error else 200)
    from urllib.parse import urlencode

    return redirect("/portal/matches/" + (f"?{urlencode({'error': error})}" if error else ""))


UNREADABLE = ("We could not read {names} reliably. Please upload it in a different format (a sharp photo taken "
              "straight from above, a scan or a PDF), or type your grades in manually.")


@require_POST
def portal_transcript_autofill(request):
    """"Click to autofill" (from a transcript): save the uploaded files, read them (sources/ocr.py: fast model, then the precise
    one when needed), and answer with the grades for the two most recent years, the GPA and the class rank, for the
    page to fill into the form. Nothing is saved to the profile here: the student checks the grades, then saves."""
    from datetime import timedelta

    from django.http import JsonResponse

    from sources import ocr, transcript

    student = _student(request)

    def fail(message, files=()):
        return JsonResponse({"ok": False, "error": message, "files": list(files)}, status=400)

    if student.submitted_at:
        return fail("Your application is already submitted.")
    if demo.is_demo(student):
        return fail("Reading transcripts is turned off in the demo.")
    if college_ai.provider()[0] != "gemini" or not student_ai.allowed(student):
        return fail("Reading transcripts automatically is not available yet. Please type your grades in.")
    now = timezone.now()
    runs = [t for t in (student.attributes or {}).get("ocr_runs", []) if t > (now - timedelta(days=1)).isoformat()]
    if len(runs) >= OCR_RUNS_PER_DAY:
        return fail(f"You have used the transcript reader {OCR_RUNS_PER_DAY} times today. Please type your grades in, "
                    "or try again tomorrow.")
    errors, saved = _save_uploads(student, request.FILES.getlist("transcripts"))
    if errors:
        return fail(" ".join(errors))
    files = saved or list(student.files.filter(kind="transcript"))
    if not files:
        return fail("Please choose your transcript files first.")

    to_read = ocr.pending_files(student, files)
    if to_read:
        student.attributes = {**(student.attributes or {}), "ocr_runs": runs + [now.isoformat()]}
        student.save(update_fields=["attributes", "updated_at"])
        ocr.store(to_read, ocr.read_files(to_read))

    summary = [{"name": f.original_name, "status": f.ocr.get("status")} for f in files]
    merged = ocr.merge([f.ocr for f in files])
    unread = [f.original_name for f in files if f.ocr.get("status") != "accepted"]
    not_transcripts = [f.original_name for f in files if f.ocr.get("status") == "not_transcript"]
    if not merged["latest"]:
        if not_transcripts and len(not_transcripts) == len(files):
            return fail(f"{', '.join(not_transcripts)} does not look like a transcript. Please upload your grades for "
                        "the past 2 school years, or type them in manually.", summary)
        return fail(UNREADABLE.format(names=", ".join(unread) or "your transcript"), summary)
    gpa, gpa_note = transcript.compute_gpa([merged["latest"], merged["prev"]], merged["scale"])
    student.attributes = {**(student.attributes or {}), "transcript_read": {
        "labels": merged["labels"], "scale": merged["scale"], "notes": merged["notes"], "at": now.isoformat()}}
    student.save(update_fields=["attributes", "updated_at"])
    return JsonResponse({
        "ok": True, "files": summary, "labels": merged["labels"],
        "grades_latest": transcript.format_grades(merged["latest"]), "grades_prev": transcript.format_grades(merged["prev"]),
        "gpa": f"{gpa:.2f}" if gpa is not None else "", "gpa_note": gpa_note,
        "class_top_pct": merged["class_top_pct"] or "", "curriculum": ocr.CURRICULUM_FOR_SCALE.get(merged["scale"], ""),
        "warning": " ".join(filter(None, [
            UNREADABLE.format(names=", ".join(unread)) if unread else "",
            "Some files use a different grading scale and were left out: please upload transcripts from one school "
            "system, or type the other grades in." if merged["other_scale"] else ""])),
        "one_year": not merged["prev"],
    })


def edit_lock_until(student):
    """A week after the student last reopened their profile (None if they never did)."""
    from datetime import datetime, timedelta

    reopens = (student.attributes or {}).get("reopens") or []
    return datetime.fromisoformat(max(reopens)) + timedelta(days=EDIT_EVERY_DAYS) if reopens else None


def next_edit_at(student):
    """When the submitted profile may be reopened: None = now, otherwise that date."""
    until = edit_lock_until(student)
    return until if until and until > timezone.now() else None


@require_POST
def portal_reopen(request):
    """The student reopens their submitted profile to change it, once a week. It goes back to "not submitted" (their
    matches are hidden) until they submit again; the week counts from now."""
    student = _student(request)
    if not student.submitted_at or next_edit_at(student):
        return redirect("/portal/")
    student.submitted_at = None
    student.attributes = {**(student.attributes or {}),
                          "reopens": ((student.attributes or {}).get("reopens") or []) + [timezone.now().isoformat()]}
    student.save(update_fields=["submitted_at", "attributes", "updated_at"])
    return redirect("/portal/?reopened=1")


@require_POST
def portal_file_delete(request, pk):
    student = _student(request)
    if student.submitted_at or demo.is_demo(student):
        return redirect("/portal/")
    f = get_object_or_404(StudentFile, pk=pk, student=student)
    path = (settings.STUDENT_FILES_DIR / f.file_path).resolve()
    if settings.STUDENT_FILES_DIR.resolve() in path.parents and path.exists():
        path.unlink()
    f.delete()
    return redirect("/portal/")
