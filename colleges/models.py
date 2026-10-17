"""College-side data model.

Three tables, deliberately source-agnostic so the schema can keep evolving:

- College: one row per college in scope, keyed by IPEDS UNITID.
- SourceRecord: one raw item fetched from a source (a CDS file, one IPEDS
  endpoint response, one HubSpot company or note). Keeps the raw text/JSON
  so parsing can be redone when the schema changes.
- Fact: one structured value parsed from a SourceRecord. Facts are tagged with
  their source, so the dashboard can filter by CDS / IPEDS / HubSpot / any
  future source without schema changes.
"""

from django.db import models


class College(models.Model):
    unitid = models.IntegerField(primary_key=True, help_text="IPEDS UNITID")
    name = models.CharField(max_length=200, help_text="Official IPEDS name")
    list_name = models.CharField(max_length=200, help_text="Name as written in the team's college list")
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=2, blank=True)
    website = models.CharField(max_length=200, blank=True)
    has_cds = models.BooleanField(null=True, help_text="From the team's list: does the college publish a CDS?")
    latest_cds_year = models.CharField(
        max_length=16, blank=True, help_text="Set only for colleges that stopped publishing a CDS"
    )
    hubspot_company_ids = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SourceRecord(models.Model):
    """One raw item from a source, stored as fetched."""

    source = models.CharField(max_length=32, db_index=True, help_text="cds, ipeds, hubspot, ...")
    kind = models.CharField(max_length=64, db_index=True, help_text="e.g. cds_document, ipeds_endpoint, hubspot_note")
    external_id = models.CharField(max_length=255, help_text="Stable ID within the source (file name, endpoint/year, HubSpot ID)")
    college = models.ForeignKey(
        College, null=True, blank=True, on_delete=models.CASCADE, related_name="records",
        help_text="Empty when the record could not be matched to a college yet",
    )
    title = models.CharField(max_length=300, blank=True)
    period = models.CharField(max_length=16, blank=True, help_text="Data year, e.g. 2025-26 or 2024")
    is_primary = models.BooleanField(
        default=True, help_text="False for secondary documents, e.g. Columbia General Studies CDS"
    )
    file_path = models.CharField(max_length=500, blank=True, help_text="Path relative to data/")
    checksum = models.CharField(max_length=64, blank=True)
    raw_text = models.TextField(blank=True)
    raw_json = models.JSONField(null=True, blank=True)
    parse_method = models.CharField(max_length=32, blank=True)
    parse_status = models.CharField(max_length=32, blank=True, help_text="ok, partial, needs_ocr, failed")
    parse_log = models.TextField(blank=True)
    fetched_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "external_id"], name="unique_source_record"),
        ]
        ordering = ["source", "kind", "title"]

    def __str__(self):
        return f"{self.source}: {self.title or self.external_id}"


class Fact(models.Model):
    """One structured value about a college, traced back to its raw record."""

    METHOD_MANUAL = "manual"

    college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="facts")
    record = models.ForeignKey(SourceRecord, on_delete=models.CASCADE, related_name="facts")
    source = models.CharField(max_length=32, db_index=True)
    section = models.CharField(max_length=64, db_index=True, help_text="CDS section (C1, C7) or IPEDS endpoint")
    key = models.CharField(max_length=200, db_index=True, help_text="Canonical field key, e.g. AP_ADMT_INTL_1ST_N")
    label = models.CharField(max_length=500)
    value_num = models.FloatField(null=True, blank=True)
    value_text = models.TextField(blank=True, help_text="Value as written in the source")
    period = models.CharField(max_length=16, blank=True)
    method = models.CharField(
        max_length=32, help_text="How the value was obtained: xlsx, pdf_form, pdf_text, api, manual"
    )
    needs_review = models.BooleanField(default=False)
    review_note = models.CharField(max_length=300, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["record", "key"], name="unique_fact_per_record"),
        ]
        indexes = [models.Index(fields=["college", "source", "section"])]
        ordering = ["source", "section", "key"]

    def __str__(self):
        return f"{self.college_id} {self.key}={self.display_value}"

    @property
    def display_value(self):
        if self.value_num is not None:
            return f"{self.value_num:,.2f}".rstrip("0").rstrip(".")
        return self.value_text


# ---------------------------------------------------------------- college profile (dashboard)
#
# The college side of the future matching algorithm: one row per college, one
# column per item (1NF). Values are filled by import commands and can be edited
# on the dashboard. FieldHistory records where every value came from.


class CollegeProfile(models.Model):
    TEST_POLICY_CHOICES = [
        ("required", "Required"),
        ("preferred", "Strongly preferred"),
        ("optional", "Optional"),
        ("blind", "Test-blind"),
        ("unknown", "Unknown"),
    ]
    APIB_CHOICES = [
        ("strong_preference", "Strong preference for IB/AP"),
        ("some_preference", "Some preference for IB/AP"),
        ("no_preference", "No preference (national curriculum fine)"),
    ]
    OLYMPIAD_CHOICES = [
        ("academic_excellence", "Academic stars (olympiads, research)"),
        ("balanced", "Balanced"),
        ("holistic", "Holistic (impact, activism fine)"),
    ]

    STUDENT_BODY_CHOICES = [("coed", "Co-ed"), ("women", "Women's college"), ("men", "Men's college")]

    college = models.OneToOneField(College, primary_key=True, on_delete=models.CASCADE, related_name="profile")

    student_body = models.CharField("Student body", max_length=8, choices=STUDENT_BODY_CHOICES, blank=True)

    det_minimum = models.PositiveSmallIntegerField("DET minimum", null=True, blank=True)
    det_recommended = models.PositiveSmallIntegerField("DET recommended", null=True, blank=True)
    det_note = models.TextField("DET note", blank=True)

    sat_median = models.PositiveSmallIntegerField("SAT median", null=True, blank=True)
    sat_p25 = models.PositiveSmallIntegerField("SAT 25th percentile", null=True, blank=True,
                                               help_text="Enrolled first-years (CDS C9; IPEDS sections summed if no CDS)")
    sat_p75 = models.PositiveSmallIntegerField("SAT 75th percentile", null=True, blank=True)
    sat_p30 = models.PositiveSmallIntegerField(
        "SAT red-flag line (30th percentile)", null=True, blank=True,
        help_text="Below this: bottom 30%. Estimated from the 25th, 50th and 75th percentiles")
    sat_p70 = models.PositiveSmallIntegerField(
        "SAT safety line (70th percentile)", null=True, blank=True,
        help_text="From this score up: top 30%. Estimated from the 25th, 50th and 75th percentiles")
    sat_minimum = models.PositiveSmallIntegerField("SAT minimum", null=True, blank=True,
                                                   help_text="Only if the college publishes a minimum SAT")
    test_policy = models.CharField("Test policy", max_length=16, choices=TEST_POLICY_CHOICES, blank=True)
    sat_note = models.TextField("SAT note", blank=True)

    gpa_average = models.DecimalField("Average HS GPA", max_digits=4, decimal_places=2, null=True, blank=True)
    gpa_note = models.TextField("GPA note", blank=True)

    top10_pct = models.FloatField("% in top 10% of class", null=True, blank=True)
    gpa_375_pct = models.FloatField("% with GPA 3.75+", null=True, blank=True)

    FULL_RIDES_SCOPE_CHOICES = [("intl", "International students only"), ("all", "All students (US and international)")]
    full_rides = models.CharField(
        "Full rides", max_length=120, blank=True,
        help_text="As published: a number (\"25 / year\") or a share (\"30% of all undergraduates\"). Empty when no "
                  "reliable source gives one")
    full_rides_scope = models.CharField("Full rides: who is counted", max_length=8, choices=FULL_RIDES_SCOPE_CHOICES,
                                        blank=True)
    full_rides_url = models.URLField("Full rides: source link", max_length=500, blank=True)
    full_rides_note = models.TextField("Full rides note", blank=True)

    intl_aid_total = models.PositiveIntegerField(
        "International aid per year ($)", null=True, blank=True,
        help_text="Institutional aid to all international undergraduates in one year (CDS H6)")
    intl_aid_students = models.PositiveIntegerField("International students on aid", null=True, blank=True)
    intl_aid_note = models.TextField("International aid note", blank=True)

    ugs_admits = models.JSONField("UGS admits by year", default=dict, blank=True,
                                  help_text="{year: UGS students admitted}, from UGS's admissions results")
    ugs_capacity = models.PositiveSmallIntegerField(
        "UGS capacity per year", null=True, blank=True,
        help_text="How many UGS students the college usually admits a year (average of the last 3 years, at least 1)")

    @property
    def ugs_admits_avg(self):
        """Average UGS students a year over every year in UGS's results (None before the import)."""
        from sources.ugs_history import average

        return average(self.ugs_admits or {})

    apib_preference = models.CharField("AP/IB preference", max_length=24, choices=APIB_CHOICES, blank=True)
    apib_rationale = models.TextField("AP/IB rationale", blank=True)
    olympiad_preference = models.CharField("Olympiad/research preference", max_length=24, choices=OLYMPIAD_CHOICES, blank=True)
    olympiad_rationale = models.TextField("Olympiad/research rationale", blank=True)

    vibe = models.TextField("College vibe", blank=True)
    hubspot_feedback = models.TextField(
        "HubSpot feedback", blank=True,
        help_text="The model's fact-check of the HubSpot notes: which claims hold up, which don't, and why",
    )


    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile: {self.college}"


class FieldHistory(models.Model):
    """Append-only log of every value written to a CollegeProfile field.

    The newest row for (college, field) says where the current value came from.
    Imports skip fields whose newest row has source "manual".
    """

    SOURCE_MANUAL = "manual"

    college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="field_history")
    field = models.CharField(max_length=64, db_index=True)
    value = models.TextField(blank=True)
    source = models.CharField(max_length=32, help_text="cds, ipeds, hubspot, official_site, ai, manual")
    detail = models.TextField(blank=True, help_text="Which document, URL, model or person")
    user = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["college", "field", "-created_at"])]

    def __str__(self):
        return f"{self.college_id}.{self.field} <- {self.source}"


class Program(models.Model):
    """One strong academic program at a college (up to ~20 per college)."""

    college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="programs")
    position = models.PositiveSmallIntegerField(help_text="1 = strongest at this college")
    name = models.CharField(max_length=200)
    ranking = models.CharField(max_length=300, blank=True, help_text='e.g. "#4 Best Colleges for Economics in America"')
    rank_value = models.PositiveIntegerField(null=True, blank=True, help_text="Numeric rank, if any")
    graduates = models.PositiveIntegerField(null=True, blank=True, help_text="Bachelor's degrees awarded (IPEDS)")
    source = models.CharField(max_length=32, help_text="niche, ipeds, manual")
    source_url = models.URLField(max_length=500, blank=True)
    updated_by = models.CharField(max_length=150, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["college__name", "source", "position"]
        constraints = [models.UniqueConstraint(fields=["college", "source", "name"], name="unique_program_per_source")]

    def __str__(self):
        return f"{self.college_id} #{self.position} {self.name}"


class ColumnSetting(models.Model):
    """Dashboard column labels and visibility, editable from the dashboard header."""

    key = models.CharField(max_length=64, primary_key=True)
    label = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    position = models.PositiveSmallIntegerField(default=0)
    visible = models.BooleanField(default=True)

    class Meta:
        ordering = ["position"]

    def __str__(self):
        return self.label


class AIAnswer(models.Model):
    """Raw record of one model call that produced a profile value."""

    college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="ai_answers")
    question = models.CharField(max_length=32, help_text="vibe, apib, olympiad")
    prompt = models.TextField()
    context_sent = models.TextField(blank=True, help_text="HubSpot text included in the prompt, after name filtering")
    notes_used = models.PositiveSmallIntegerField(default=0)
    model = models.CharField(max_length=64)
    response = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


# ---------------------------------------------------------------- students
#
# Privacy design: a student is known everywhere by a random code.
# Names and emails live only in StudentIdentity, encrypted with STUDENT_DATA_KEY.
# Anything sent to an AI model is built from Student (code, attributes, notes), never
# from StudentIdentity.


def new_student_code():
    import secrets

    alphabet = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # no 0/O/1/I/L to avoid misreading
    while True:
        code = "S-" + "".join(secrets.choice(alphabet) for _ in range(6))
        if not Student.objects.filter(code=code).exists():
            return code


class Student(models.Model):
    """One applicant. `user` is their login (created when they register with their email)."""

    PRONOUN_CHOICES = [("she", "she/her"), ("he", "he/him"), ("they", "they/them"), ("she_they", "she/they"),
                       ("he_they", "he/they"), ("other", "Other")]
    CURRICULUM_CHOICES = [("no", "No"), ("ib", "IB"), ("ap", "AP"), ("alevels", "A-levels")]
    ACADEMIC_TIER_CHOICES = [("very_strong", "Very strong"), ("strong", "Strong"), ("moderate", "Moderate")]
    SCHOOL_TYPE_CHOICES = [("english", "English curriculum (IB, AP, A-levels)"), ("top_ua", "Top Ukrainian school"),
                           ("regular_ua", "Regular Ukrainian school")]
    LEVEL_CHOICES = [("high", "High"), ("medium", "Medium"), ("low", "Low")]

    code = models.CharField(max_length=12, unique=True, default=new_student_code, editable=False)
    cohort = models.CharField(max_length=16, blank=True, help_text="Application year, e.g. 2024-25")
    user = models.OneToOneField("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="student")
    submitted_at = models.DateTimeField(null=True, blank=True, help_text="When the student submitted the form")

    # Student-side counterparts of the college dashboard columns.
    pronouns = models.CharField("Pronouns", max_length=8, choices=PRONOUN_CHOICES, blank=True,
                                help_text="he/him students are not matched with women's colleges")
    det_score = models.PositiveSmallIntegerField("DET score", null=True, blank=True)
    sat_score = models.PositiveSmallIntegerField("SAT score", null=True, blank=True)
    gpa = models.DecimalField("GPA (4.0 scale)", max_digits=4, decimal_places=2, null=True, blank=True)
    gpa_note = models.CharField("GPA note", max_length=300, blank=True,
                                help_text="e.g. original grade and scale: 11.4 / 12 (Ukrainian)")
    class_top_pct = models.FloatField("Class rank: top %", null=True, blank=True,
                                      help_text="e.g. 5 means top 5% of the class")
    transcript_note = models.TextField("Transcript note", blank=True)
    subject_grades = models.JSONField(
        "Grades by subject (latest year)", default=dict, blank=True,
        help_text="Latest grade per subject on the school's own scale: Ukrainian 1-12, IB 1-7 (plus "
                  "'Core (TOK/EE)': 0-3), A-levels A*-E, US letter grades (AP courses start with 'AP')")
    subject_grades_prev = models.JSONField(
        "Grades by subject (previous year)", default=dict, blank=True,
        help_text="The year before, on the same scale. Both years count for the GPA and coursework levels.")
    major_1 = models.CharField("Intended major 1", max_length=100, blank=True)
    major_2 = models.CharField("Intended major 2", max_length=100, blank=True)
    major_3 = models.CharField("Intended major 3", max_length=100, blank=True)
    curriculum = models.CharField("AP/IB", max_length=8, choices=CURRICULUM_CHOICES, blank=True)
    school_name = models.CharField("School", max_length=200, blank=True, help_text="School name and city")
    school_type = models.CharField("School type", max_length=12, choices=SCHOOL_TYPE_CHOICES, blank=True,
                                   help_text="Set by Gemini from the school's name; can be changed by hand")
    academic_tier = models.CharField("Talent/ability", max_length=12, choices=ACADEMIC_TIER_CHOICES, blank=True,
                                     help_text="Set by Gemini from the achievements and activities; can be changed by hand")
    academic_note = models.TextField("Awards, olympiads and research", blank=True,
                                     help_text="The student's achievements")
    activities = models.TextField("Activities", blank=True, help_text="Extracurricular activities and volunteering")
    ec_level = models.CharField("Extracurricular activities", max_length=8, choices=LEVEL_CHOICES, blank=True,
                                help_text="Set by Gemini from the activities; can be changed by hand")
    volunteer_level = models.CharField("Volunteer work", max_length=8, choices=LEVEL_CHOICES, blank=True,
                                       help_text="Set by Gemini from the activities; can be changed by hand")
    work_experience = models.TextField("Work experience", blank=True,
                                       help_text="Jobs, a family business, caring for family members")
    work_level = models.CharField("Work experience level", max_length=8, choices=LEVEL_CHOICES, blank=True,
                                  help_text="Set by Gemini from the work experience; can be changed by hand")
    self_summary = models.TextField("Student vibe", blank=True,
                                    help_text="How the student describes themselves (300 words or less)")
    attributes = models.JSONField(default=dict, blank=True,
                                  help_text="De-identified data points (no names, emails or phone numbers)")
    notes = models.TextField(blank=True, help_text="De-identified free text")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["cohort", "code"]

    def __str__(self):
        return self.code


class StudentIdentity(models.Model):
    """Encrypted personal details. Read only to show names to logged-in admins."""

    student = models.OneToOneField(Student, primary_key=True, on_delete=models.CASCADE, related_name="identity")
    name_encrypted = models.TextField(blank=True)
    email_encrypted = models.TextField(blank=True)
    source_ref_encrypted = models.TextField(blank=True, help_text="e.g. spreadsheet row or Airtable record id")
    email_hash = models.CharField(max_length=64, blank=True, db_index=True,
                                  help_text="Keyed fingerprint of the email, to find a student at sign-up without decrypting")

    def __str__(self):
        return f"Identity of {self.student_id}"


class StudentFile(models.Model):
    KIND_CHOICES = [("transcript", "Transcript"), ("other", "Other")]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="files")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default="transcript")
    file_path = models.CharField(max_length=500, help_text="Path relative to data/students/")
    original_name = models.CharField(max_length=255, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)
    ocr = models.JSONField("Transcript reading", default=dict, blank=True,
                           help_text="What the OCR pipeline read (sources/ocr.py): models used, confidence, grades")
    needs_verification = models.BooleanField(
        default=False, help_text="The OCR was not confident enough: a counselor should check the grades by hand")

    class Meta:
        ordering = ["student", "original_name"]

    def __str__(self):
        return f"{self.student_id}: {self.original_name or self.file_path}"



class CollegeChoice(models.Model):
    """One of a student's 12 preferred colleges, with their reason."""

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="choices")
    college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="student_choices")
    rank = models.PositiveSmallIntegerField(help_text="1 = first choice")
    blurb = models.TextField(blank=True, help_text="Why the student thinks it is a good fit")

    class Meta:
        ordering = ["student", "rank"]
        constraints = [
            models.UniqueConstraint(fields=["student", "college"], name="one_choice_per_college"),
            models.UniqueConstraint(fields=["student", "rank"], name="one_college_per_rank"),
        ]

    def __str__(self):
        return f"{self.student_id} #{self.rank} {self.college_id}"


class MatchRun(models.Model):
    """One run of the matching algorithm over all submitted students."""

    METHOD_CHOICES = [("demo", "Demo (placeholder formula, not a prediction)"), ("algorithm", "Matching algorithm"),
                      ("student", "Student's own results (run when they submit or change their list)"),
                      ("import", "Imported results")]

    method = models.CharField(max_length=16, choices=METHOD_CHOICES)
    label = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=150, blank=True)
    released_at = models.DateTimeField(null=True, blank=True, help_text="When students could see their results")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_method_display()} {self.created_at:%Y-%m-%d %H:%M}"


class MatchResult(models.Model):
    run = models.ForeignKey(MatchRun, on_delete=models.CASCADE, related_name="results")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="match_results")
    college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="match_results")
    match_pct = models.FloatField("Match %", help_text="Student match %, 0-100 (not a chance of admission)")
    rank = models.PositiveSmallIntegerField(help_text="Position in the student's list: best match first")
    excluded = models.BooleanField(default=False, help_text="Ruled out by a hard rule (pronouns, DET, SAT)")
    details = models.JSONField(default=dict, blank=True, help_text="Component scores and reasons")

    class Meta:
        ordering = ["run", "student", "rank"]
        constraints = [models.UniqueConstraint(fields=["run", "student", "college"], name="one_result_per_college")]



class VibeJudgement(models.Model):
    """Cached LLM judgement: how well a student's self-summary fits a college's vibe."""

    LEVEL_CHOICES = [("high", "High similarity"), ("moderate", "Moderate"), ("none", "No similarity")]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="vibe_judgements")
    college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="vibe_judgements")
    level = models.CharField(max_length=8, choices=LEVEL_CHOICES)
    reason = models.TextField(blank=True)
    model = models.CharField(max_length=64)
    input_hash = models.CharField(max_length=64, help_text="Changes when the summary or the college vibe changes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["student", "college"], name="one_vibe_judgement")]

