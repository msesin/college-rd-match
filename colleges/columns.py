"""Columns of the main dashboard.

The registry defines what each column shows and which CollegeProfile fields a
click on its cell edits. Labels, descriptions, order and visibility can be
changed from the dashboard header and are stored in ColumnSetting.
"""

from dataclasses import dataclass

from django.db import models

from colleges.models import ColumnSetting


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    description: str
    fields: tuple = ()
    kind: str = "text"


COLUMNS = [
    Column("student_body", "Student body",
           "Whether the college is co-ed, a women's college or a men's college. From the College Scorecard "
           "single-sex flags (via IPEDS); checked against the sex of 2024 applicants.",
           ("student_body",), "body"),
    Column("det", "DET (Duolingo)",
           "Duolingo English Test: minimum and recommended score for international applicants, from the "
           "college's official admissions site. HubSpot mentions are added to the note.",
           ("det_minimum", "det_recommended", "det_note"), "det"),
    Column("sat", "SAT median",
           "SAT of enrolled first-years: median and 25th-75th percentiles (CDS C9; IPEDS when there is no CDS), "
           "and the lines the matching engine uses: bottom 30% below the 30th percentile (red flag), top 30% from "
           "the 70th (safety). Colleges publish only the 25th, 50th and 75th, so the 30th and 70th are estimated "
           "between them on a normal curve. Plus the SAT/ACT policy for this cycle (official site).",
           ("sat_median", "sat_p25", "sat_p75", "sat_p30", "sat_p70", "sat_minimum", "test_policy", "sat_note"), "sat"),
    Column("gpa", "Avg HS GPA",
           "Average high-school GPA of enrolled first-years (CDS C12). The CDS reports an average, not a median.",
           ("gpa_average", "gpa_note"), "gpa"),
    Column("transcript_perf", "Transcript performance",
           "Typical grades of enrolled first-years: share in the top 10% of their class (CDS C10) and share "
           "with a GPA of 3.75 or higher (CDS C11).",
           ("top10_pct", "gpa_375_pct"), "perf"),
    Column("programs", "Top 3 programs",
           "The first three entries of the college's list on the Programs page: Niche rankings when loaded, "
           "otherwise the largest majors by graduates (IPEDS).",
           (), "programs"),
    Column("apib", "AP/IB preference",
           "Whether the college favours IB/AP schools over national-curriculum schools. Answer from a "
           "context-free Claude model, given HubSpot notes when the college has any.",
           ("apib_preference", "apib_rationale"), "choice"),
    Column("olympiad", "Olympiads & research",
           "Whether the college looks for academic stars (olympiads, research) or a strong all-round applicant "
           "such as a social activist would be competitive. Same method as AP/IB.",
           ("olympiad_preference", "olympiad_rationale"), "choice"),
    Column("vibe", "College vibe",
           "Key traits of the students the college wants (100 words max). Answer from a context-free Claude "
           "model acting as director of admissions, given HubSpot notes when the college has any. Will be "
           "matched to students' self-summaries.",
           ("vibe",), "longtext"),
    Column("hubspot", "HubSpot notes",
           "All HubSpot calls, notes and meetings about the college, newest first (scroll inside the cell).",
           (), "hubspot"),
    Column("hubspot_feedback", "HubSpot feedback",
           "Fact-check of the college's HubSpot notes by the same model that wrote the vibe: which claims "
           "agree with what is known about the college, which look wrong or outdated, and why. Empty when "
           "the college has no HubSpot notes.",
           ("hubspot_feedback",), "longtext"),
    Column("full_rides", "Full rides",
           "Full rides as a reliable source states them (HubSpot notes, college pages, student newspapers, news): a "
           "number or a share, who is counted (international students only, or all students) and a link to the source. "
           "Empty when no source gives a count; the note says what was found instead. Nothing is calculated.",
           ("full_rides", "full_rides_scope", "full_rides_url", "full_rides_note"), "full_rides"),
    Column("intl_aid", "Intl aid / year",
           "Total institutional aid the college gave all its international undergraduates in one year, with how many "
           "received it (CDS H6).",
           ("intl_aid_total", "intl_aid_students", "intl_aid_note"), "intl_aid"),
    Column("ugs_avg", "UGS students / year",
           "How many UGS students went to this college per year on average, over every year in UGS's admissions "
           "results (2018-2025). Click for the results by year.", (), "ugs_avg"),
    Column("ugs_applicants", "UGS applicants",
           "How many UGS students have this college on their list (submitted forms), against its UGS capacity: how "
           "many UGS students it usually admits a year (average of the last 3 years in UGS's admissions results, at "
           "least 1; editable). Applied after the match: no cut up to 2x capacity, then a cut growing evenly to 20% "
           "of the match at 4x and above.",
           ("ugs_capacity",), "applicants"),
]
BY_KEY = {c.key: c for c in COLUMNS}

CHOICE_ORDER = {
    "strong_preference": 3, "some_preference": 2, "no_preference": 1,
    "academic_excellence": 3, "balanced": 2, "holistic": 1,
}


HUBSPOT_COLUMNS = ("hubspot", "hubspot_feedback")   # optional CRM integration (UGS); hidden when there is no data


def _has_hubspot():
    from colleges.models import SourceRecord

    return SourceRecord.objects.filter(source="hubspot").exists()


def settings_by_key():
    """ColumnSetting rows for every column, created with defaults on first use."""
    existing = {s.key: s for s in ColumnSetting.objects.all()}
    for i, col in enumerate(COLUMNS):
        if col.key in existing:
            continue
        # A new column goes right after the column that precedes it in COLUMNS.
        prev = existing.get(COLUMNS[i - 1].key) if i else None
        position = prev.position + 1 if prev else i
        ColumnSetting.objects.filter(position__gte=position).update(position=models.F("position") + 1)
        for s in existing.values():
            if s.position >= position:
                s.position += 1
        existing[col.key] = ColumnSetting.objects.create(
            key=col.key, label=col.label, description=col.description, position=position,
            visible=col.key not in HUBSPOT_COLUMNS or _has_hubspot())
    return existing


def save_order(keys):
    """Store a new column order (list of column keys, left to right)."""
    for position, key in enumerate(k for k in keys if k in BY_KEY):
        ColumnSetting.objects.filter(key=key).update(position=position)


def ordered_columns():
    """[(Column, ColumnSetting)] in display order."""
    settings = settings_by_key()
    return sorted(((c, settings[c.key]) for c in COLUMNS), key=lambda cs: (cs[1].position, cs[0].key))


# ---------------------------------------------------------------- students tab
# Student-side counterparts of the dashboard columns, keyed by the same column keys so
# the Students tab follows the dashboard's column order.

ACADEMIC_TIER_MEANING = {
    "very_strong": "International level (olympiad medals, a publication, international competitions), consistent results.",
    "strong": "National or regional level, semi-consistent results.",
    "moderate": "Local or school level, national competitions held online, or nothing notable yet.",
}
# Student field rated by Gemini -> its key in attributes["profile_read"] (sources/student_ai.py)
RATED_FIELDS = {"school_type": "school_type", "academic_tier": "talent", "ec_level": "extracurricular",
                "volunteer_level": "volunteer", "work_level": "work"}

STUDENT_COLUMNS = {
    "student_body": Column("student_body", "Pronouns",
                           "The student's pronouns. Students who use he/him are not matched with women's colleges; "
                           "everyone else is.", ("pronouns",), "s_choice"),
    "det": Column("det", "DET", "The student's Duolingo English Test score.", ("det_score",), "s_number"),
    "sat": Column("sat", "SAT", "The student's SAT score (blank if not taken).", ("sat_score",), "s_number"),
    "gpa": Column("gpa", "GPA",
                  "Grades by subject for the past 2 school years, on the school's own scale. The GPA level (will "
                  "get in / maybe / red flags) is worked out from both years by the team's rules for each curriculum; "
                  "GPA on a 4.0 scale if known. 'Transcript: check by hand' = the transcript reader was not sure.",
                  ("subject_grades", "subject_grades_prev", "gpa", "gpa_note"), "s_gpa"),
    "transcript_perf": Column("transcript_perf", "Transcript performance",
                              "Class rank (top X%) and relevant coursework: grades in the subjects that matter for the "
                              "student's first major (strong / okay / weak). Both worked out from the data.",
                              ("class_top_pct", "transcript_note"), "s_perf"),
    "programs": Column("programs", "Top 3 programs", "The student's intended majors, in order of preference.",
                       ("major_1", "major_2", "major_3"), "s_majors"),
    "apib": Column("apib", "AP/IB", "Whether the student follows IB, AP or A-levels (an English-language curriculum).",
                   ("curriculum",), "s_choice"),
    "olympiad": Column("olympiad", "Talent/ability",
                       "Very strong / strong / moderate, rated by Gemini from the awards and the activities (a level "
                       "changed by hand is kept). Used for the Talent/ability metric (CDS C7).",
                       ("academic_note", "academic_tier"), "s_rated"),
    "vibe": Column("vibe", "Student vibe",
                   "How the student describes themselves: traits, interests and what they want from college "
                   "(300 words or less). Gemini judges it against each college vibe: high / moderate / none.",
                   ("self_summary",), "s_text"),
    # student-only columns (no college column of the same name), shown after the others
    "school": Column("school", "School",
                     "The school's name and city, and its type rated by Gemini from the name: English curriculum (IB, "
                     "AP, A-levels) / top Ukrainian school / regular Ukrainian school. Half of the Rigor metric.",
                     ("school_name", "school_type"), "s_rated"),
    "activities": Column("activities", "Activities",
                         "What the student wrote about their activities, with two levels rated by Gemini: "
                         "extracurricular activities and volunteer work (high / medium / low).",
                         ("activities", "ec_level", "volunteer_level"), "s_rated"),
    "work": Column("work", "Work experience",
                   "Jobs, a family business, caring for family members; the level (high / medium / low) is rated "
                   "by Gemini.", ("work_experience", "work_level"), "s_rated"),
}
STUDENT_ONLY = ("school", "activities", "work")


def student_columns():
    """Student columns in the dashboard's current column order."""
    order = [c.key for c, s in ordered_columns()]
    return [STUDENT_COLUMNS[k] for k in order if k in STUDENT_COLUMNS] + [STUDENT_COLUMNS[k] for k in STUDENT_ONLY]
