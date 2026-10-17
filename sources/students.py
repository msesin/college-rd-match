"""Student helpers. The only function that should feed student data to an AI model is for_ai()."""

from sources.redact import scrub_contacts


def for_ai(student):
    """What a model may see about a student: the random code, cohort and de-identified fields.

    Never includes StudentIdentity (names, emails). Free text is scrubbed of emails and
    phone numbers as a second line of defence.
    """
    profile = {
        f: (str(getattr(student, f)) if getattr(student, f) is not None else None)
        for f in ("pronouns", "det_score", "sat_score", "gpa", "gpa_note", "class_top_pct", "major_1", "major_2",
                  "major_3", "curriculum", "school_name", "academic_tier")
    }
    profile.update({f: scrub_contacts(getattr(student, f)) for f in ("transcript_note", "academic_note", "self_summary",
                                                                     "activities", "work_experience")})
    return {
        "student": student.code,
        "cohort": student.cohort,
        "profile": profile,
        "attributes": {k: scrub_contacts(v) if isinstance(v, str) else v for k, v in student.attributes.items()},
        "notes": scrub_contacts(student.notes),
    }


def applicant_counts():
    """{unitid: number of submitted students who listed the college among their choices}. Fictional sample
    students (the public demo included) never count, so they cannot change real students' matches."""
    from django.db.models import Count

    from colleges.models import CollegeChoice

    rows = (CollegeChoice.objects.filter(student__submitted_at__isnull=False).exclude(student__cohort="sample")
            .values("college_id").annotate(n=Count("student", distinct=True)))
    return {r["college_id"]: r["n"] for r in rows}


def delete_student(student):
    """Remove a student completely: files on disk, login account, and every linked row."""
    import shutil

    from django.conf import settings

    base = settings.STUDENT_FILES_DIR.resolve()
    folder = (base / student.code).resolve()
    if base in folder.parents and folder.is_dir():
        shutil.rmtree(folder)
    user = student.user
    student.delete()  # identity, choices, files, match results go with it
    if user is not None and not user.is_staff:
        user.delete()
