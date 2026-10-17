"""Matching engine: how well each student matches each college (student match %), and the 12 best
matches the student sees.

The match % is not a chance of admission: a perfect match can still be turned down, especially when
the student needs full financial aid. Everything here is computed in code. Gemini provides only ratings of
the student's own texts, saved in the database before the engine runs (sources/student_ai.py): school type,
talent/ability, extracurricular activities, volunteer work, work experience, and the self-summary against
each college vibe.

1. HARD RULES. The college is excluded when
   - pronouns: a student who uses he/him and a women's college (she/her and a men's college);
   - DET: below the college's minimum or recommended score, including the UGS recommendation of 135 (all are
     treated as the bare minimum); students in IB, AP or A-levels are exempt;
   - SAT: below a published SAT minimum; or the college requires the SAT and the student has none or is in
     its bottom 30%;
   - majors: none of the student's majors is related to the college's top 20 programs (majors graph: 0).
2. METRICS, worth points out of 100, in three categories (academic, personal, fit). Nine follow the factors
   of CDS C7 (what the college says matters in admission): the team's points x the college's rating (very
   important 1.5, important 1, considered 0.5, not considered 0), rescaled to share 87.5 points. Majors (12.5)
   are the same at every college. Most metrics have three levels: full, half or no points.
3. PRELIMINARY MATCH % = the points earned. Saved per student (refresh_students).
4. CROWDING, applied when the results are shown (with_crowding): when many UGS students have the college on
   their list compared with how many UGS students it usually admits, the match is cut by up to 20%. It uses
   the current lists, so it changes live; the student sees only the final %.
All numbers are at the top of this file.
"""

from dataclasses import dataclass, field

from colleges.models import College, CollegeProfile, Fact, MatchResult, MatchRun, Student, VibeJudgement
from sources import majors, transcript
from sources.programs import best_list

ENGINE = "Matching engine v3"

TEAM_POINTS = {        # the team's points (decision 41); crowding's 5 are spread over the C7 metrics (decision 42)
    "sat": 17.5,
    "rigor": 12.5,
    "major": 12.5,
    "character": 12.5,
    "gpa": 10,
    "talent": 10,
    "extracurricular": 10,
    "class_rank": 5,
    "volunteer": 2.5,
    "work": 2.5,
}
CATEGORIES = {"Academic": ["sat", "rigor", "gpa", "class_rank"],
              "Personal": ["character", "talent", "extracurricular", "volunteer", "work"],
              "Fit": ["major"]}
ORDER = [k for keys in CATEGORIES.values() for k in keys]   # metrics are listed in this order everywhere
CATEGORY = {k: name for name, keys in CATEGORIES.items() for k in keys}
LABELS = {"sat": "SAT", "rigor": "Rigor of school record", "major": "Majors", "character": "Character (self-summary)",
          "gpa": "GPA", "talent": "Talent/ability", "extracurricular": "Extracurricular activities",
          "class_rank": "Class rank", "volunteer": "Volunteer work", "work": "Work experience"}

# What each metric includes and how it is measured (College weights tab, "How the match is built").
METRIC_HELP = {
    "sat": "SAT score against the college's SAT range: top 30% full points, middle half. Bottom 30%: half at "
           "test-optional colleges (apply without it), excluded where scores are required. No SAT: half. Test-blind: half.",
    "rigor": "Half school type, rated by Gemini from the school's name (English curriculum incl. Ukrainian schools "
             "teaching IB/AP/A-levels 1, top Ukrainian lyceum or gymnasium 0.5, regular Ukrainian school 0); half "
             "grades in the subjects of the first major (strong 1, okay 0.5, weak 0).",
    "gpa": "Grades by subject turned into a level by the team's rules for each curriculum (will get in / maybe / red "
           "flags), against the college's GPA bar: at or above full, one level below half, two below none.",
    "class_rank": "Top 10% / top 10-25% / lower, against the share of the college's first-years who were in their "
                  "top 10%: at or above full, one below half, two below none. No rank: half.",
    "character": "Gemini compares the self-summary with the college vibe: high full, moderate half, none 0.",
    "talent": "Gemini reads the awards, olympiads, research and activities (academic, artistic or athletic): very "
              "strong = international level with consistent results (full); strong = national or regional (half); "
              "moderate = local, online, or nothing notable yet (0).",
    "extracurricular": "Gemini reads the activities: high = sustained, with leadership or impact beyond school "
                       "(full); medium = regular, some responsibility (half); low = little or occasional (0).",
    "volunteer": "Gemini reads the volunteering in the activities: high = sustained, with real impact (full); medium "
                 "= regular (half); low = occasional or none (0).",
    "work": "Gemini reads the work experience (jobs, a family business, caring for family): high = substantial and "
            "sustained (full); medium = some (half); low = none (0).",
    "major": "Majors graph: each of the student's majors (counting 50% / 30% / 20%) against the college's top 20 "
             "programs (#1 counts fully, #20 about half). 0 = no relation at all: the college is excluded.",
}
# The student's answers and what they feed: (key, label, rated by Gemini, metrics or "rules" / "crowding", note)
INPUTS = [
    ("sat_score", "SAT score", False, ["sat", "rules"], "From the form, compared with the college's SAT range."),
    ("det_score", "DET score", False, ["rules"], "A hard minimum only: below the college's minimum or recommended "
                                                  "score (or the UGS 135) excludes it. IB, AP and A-levels students are exempt."),
    ("pronouns", "Pronouns", False, ["rules"], "Students who use he/him are not matched with women's colleges."),
    ("school_name", "School name", True, ["rigor"], "Gemini rates the school type from its name and city."),
    ("curriculum", "IB / AP / A-levels", False, ["rigor", "gpa"],
     "Sets the grade scale; counts as an English curriculum until Gemini rates the school; exempt from DET."),
    ("subject_grades", "Grades by subject", False, ["rigor", "gpa"],
     "On the school's own scale: the GPA level, and the coursework level in the subjects of the first major."),
    ("class_top_pct", "Class rank", False, ["class_rank"], "Top X% of the class, if the school ranks."),
    ("self_summary", "Self-summary", True, ["character"], "300 words; Gemini rates it against each college's vibe."),
    ("academic_note", "Awards, olympiads, research", True, ["talent"], "Gemini rates talent/ability from it."),
    ("activities", "Activities & volunteering", True, ["talent", "extracurricular", "volunteer"],
     "Gemini rates talent, extracurricular activities and volunteer work from it."),
    ("work_experience", "Work experience", True, ["work"], "Gemini rates the work level from it."),
    ("majors", "Majors (up to 3)", False, ["major", "rules"], "Compared with each college's top 20 programs."),
    ("lists", "All UGS college lists", False, ["crowding"],
     "Every submitted student's list: how many UGS students apply to each college."),
]

FULL, HALF, NONE = 1.0, 0.5, 0.0
LIST_SIZE = 12
ENGLISH_CURRICULA = {"ib", "ap", "alevels"}

# College bars (high / medium / low) from the dashboard columns: (field, label, high from, medium from)
GPA_BAR_RULES = [("gpa_average", "average HS GPA {:.2f}", 3.9, 3.75),
                 ("gpa_375_pct", "{:.0f}% of first-years have GPA 3.75+", 80, 60)]
RANK_BAR_RULES = [("top10_pct", "{:.0f}% of first-years were in the top 10% of their class", 85, 60)]
ADMIT_RATE_BAR = (10, 25)  # no figures: overall admit rate up to 10% = high bar, up to 25% = medium

RANK = {"top": 2, "maybe": 1, "red": 0, "middle": 1, "low": 0, "high": 2, "medium": 1}
SCHOOL_POINTS = {"english": FULL, "top_ua": HALF, "regular_ua": NONE}
COURSEWORK_POINTS = {"strong": FULL, "okay": HALF, "weak": NONE}
TALENT_POINTS = {"very_strong": FULL, "strong": HALF, "moderate": NONE}
LEVEL_POINTS = {"high": FULL, "medium": HALF, "low": NONE}
VIBE_POINTS = {"high": FULL, "moderate": HALF, "none": NONE}
MAJOR_PREFERENCE = [0.5, 0.3, 0.2]   # weight of the student's 1st, 2nd, 3rd major
PROGRAM_RANK_STEP = 0.025            # a college's #1 program counts fully, #20 counts 0.525
CROWDING = (2, 4)         # UGS applicants up to 2x the college's UGS capacity: no cut; the cut grows evenly ...
CROWDING_MAX_CUT = 0.20   # ... to 20% of the match at 4x capacity and above


# ---------------------------------------------------------------- points per college (CDS C7)
C7_FACTORS = {                   # metric: its CDS C7 factor
    "sat": "Q111_4",             # standardized test scores
    "rigor": "Q111_1",           # rigor of secondary school record
    "character": "Q112_4",       # character/personal qualities
    "gpa": "Q111_3",             # academic GPA
    "talent": "Q112_3",          # talent/ability
    "extracurricular": "Q112_2", # extracurricular activities
    "class_rank": "Q111_2",      # class rank
    "volunteer": "Q112_11",      # volunteer work
    "work": "Q112_12",           # work experience
}
C7_NAMES = {"Q111_1": "Rigor of secondary school record", "Q111_2": "Class rank", "Q111_3": "Academic GPA",
            "Q111_4": "Standardized test scores", "Q112_2": "Extracurricular activities", "Q112_3": "Talent/ability",
            "Q112_4": "Character/personal qualities", "Q112_11": "Volunteer work", "Q112_12": "Work experience"}
C7_LEVELS = {3: "very important", 2: "important", 1: "considered", 0: "not considered"}
C7_MULTIPLIER = {3: 1.5, 2: 1.0, 1: 0.5, 0: 0.0}
FIXED = ("major",)    # the same at every college


def college_points(c7):
    """{metric: points out of 100} for a college with C7 levels {factor key: 0-3}: the team's points x the C7
    multipliers (a blank factor counts as important), rescaled so the C7 metrics share what FIXED leaves."""
    raw = {k: TEAM_POINTS[k] * C7_MULTIPLIER.get(c7.get(f), 1.0) for k, f in C7_FACTORS.items()}
    if not sum(raw.values()):
        raw = {k: TEAM_POINTS[k] for k in C7_FACTORS}
    budget = 100 - sum(TEAM_POINTS[k] for k in FIXED)
    total = sum(raw.values())
    return {k: TEAM_POINTS[k] if k in FIXED else raw[k] * budget / total for k in ORDER}


POINTS = college_points({})   # default points out of 100 (colleges without a CDS C7)


def step(student_rank, college_rank):
    """Full points when the student is at or above the college's bar, half one level below, none two below."""
    gap = college_rank - student_rank
    return FULL if gap <= 0 else HALF if gap == 1 else NONE


# ---------------------------------------------------------------- college data

@dataclass
class CollegeData:
    college: College
    profile: CollegeProfile
    programs: list
    overall_rate: float = None      # %, for context and as a last-resort bar
    intl_rate: float = None         # %, for context only
    gpa_bar: str = "medium"
    gpa_bar_note: str = ""
    rank_bar: str = "medium"
    rank_bar_note: str = ""
    c7: dict = field(default_factory=dict)      # {C7 factor key: 0-3}
    c7_year: str = ""
    points: dict = field(default_factory=lambda: dict(POINTS))


def _facts(source, keys):
    out = {}
    qs = Fact.objects.filter(source=source, key__in=keys)
    if source == "cds":
        qs = qs.filter(record__is_primary=True)
    for f in qs:
        if f.value_num is not None:
            out.setdefault(f.college_id, {})[f.key] = f.value_num
    return out


def _bar(profile, rules, overall_rate):
    levels, parts = [], []
    for fname, label, high, medium in rules:
        v = getattr(profile, fname)
        if v is None:
            continue
        v = float(v)
        levels.append(2 if v >= high else 1 if v >= medium else 0)
        parts.append(label.format(v))
    if levels:
        avg = sum(levels) / len(levels)
        return ("high" if avg >= 1.5 else "medium" if avg >= 0.5 else "low"), "; ".join(parts)
    if overall_rate is not None:
        high, medium = ADMIT_RATE_BAR
        bar = "high" if overall_rate <= high else "medium" if overall_rate <= medium else "low"
        return bar, f"no figures; overall admit rate {overall_rate:.0f}%"
    return "medium", "no figures"


def load_colleges():
    """{unitid: CollegeData} with programs, admit rates, bars and the college's own points."""
    cds = _facts("cds", ["AP_RECD_1ST_N", "AP_ADMT_1ST_N", "AP_RECD_INTL_1ST_N", "AP_ADMT_INTL_1ST_N"])
    ipeds = _facts("ipeds", ["admissions-enrollment.number_applied", "admissions-enrollment.number_admitted"])
    programs = {c.unitid: best_list(list(c.programs.all())) for c in College.objects.prefetch_related("programs")}
    c7, c7_year = {}, {}
    for f in Fact.objects.filter(source="cds", record__is_primary=True, key__in=C7_NAMES):
        if f.value_num is not None:
            c7.setdefault(f.college_id, {})[f.key] = int(f.value_num)
            c7_year[f.college_id] = f.period
    data = {}
    for p in CollegeProfile.objects.select_related("college"):
        c, i = cds.get(p.college_id, {}), ipeds.get(p.college_id, {})
        d = CollegeData(college=p.college, profile=p, programs=programs.get(p.college_id, []))
        if c.get("AP_RECD_1ST_N") and c.get("AP_ADMT_1ST_N"):
            d.overall_rate = 100 * c["AP_ADMT_1ST_N"] / c["AP_RECD_1ST_N"]
        elif i.get("admissions-enrollment.number_applied") and i.get("admissions-enrollment.number_admitted"):
            d.overall_rate = 100 * i["admissions-enrollment.number_admitted"] / i["admissions-enrollment.number_applied"]
        if c.get("AP_RECD_INTL_1ST_N") and c.get("AP_ADMT_INTL_1ST_N"):
            d.intl_rate = 100 * c["AP_ADMT_INTL_1ST_N"] / c["AP_RECD_INTL_1ST_N"]
        d.gpa_bar, d.gpa_bar_note = _bar(p, GPA_BAR_RULES, d.overall_rate)
        d.rank_bar, d.rank_bar_note = _bar(p, RANK_BAR_RULES, d.overall_rate)
        d.c7, d.c7_year = c7.get(p.college_id, {}), c7_year.get(p.college_id, "")
        d.points = college_points(d.c7)
        data[p.college_id] = d
    return data


# ---------------------------------------------------------------- hard rules and metrics

@dataclass
class Metric:
    score: float      # 1.0 full, 0.5 half, 0.0 none (majors and rigor: anything in between)
    level: str        # short label of the level
    note: str         # why


class Excluded(Exception):
    """A college requirement the student does not meet."""


def det_gate(student, d):
    """DET: the college's minimum and recommended score (or the UGS 135) are all a bare minimum."""
    if student.curriculum in ENGLISH_CURRICULA or student.det_score is None:
        return
    p = d.profile
    bar = max(p.det_minimum or 0, p.det_recommended or 0)
    if bar and student.det_score < bar:
        kind = "UGS recommendation" if "UGS" in (p.det_note or "") else (
            "minimum" if p.det_minimum == bar else "recommended score")
        raise Excluded(f"DET {student.det_score} is below the college's {kind} {bar}")


def sat_metric(student, d):
    p = d.profile
    policy = p.test_policy or "unknown"
    sat = student.sat_score
    preferred = (" The college strongly prefers scores, so this counts as below its recommendation: "
                 "half of the test-optional points.")
    if policy == "blind":
        return Metric(HALF, "test-blind", "test-blind: the SAT is not considered")
    if sat and p.sat_minimum and sat < p.sat_minimum:
        raise Excluded(f"SAT {sat} is below the required minimum {p.sat_minimum}")
    if not sat:
        if policy == "required":
            raise Excluded("no SAT, and the college requires it")
        if policy == "preferred":
            return Metric(HALF * HALF, "below recommended", "no SAT." + preferred)
        return Metric(HALF, "no SAT", "no SAT: applies test-optional")
    if p.sat_p30 is None or p.sat_p70 is None:
        return Metric(HALF, "no figures", f"SAT {sat}; no SAT percentiles for this college")
    if sat >= p.sat_p70:
        return Metric(FULL, "top 30%", f"SAT {sat} is in the top 30% (from {p.sat_p70}): safety")
    if sat >= p.sat_p30:
        return Metric(HALF, "middle", f"SAT {sat} is in the middle ({p.sat_p30}-{p.sat_p70 - 10}): OK")
    bottom = f"SAT {sat} is in the bottom 30% (below {p.sat_p30})"
    if policy == "required":
        raise Excluded(bottom + ", and the college requires scores")
    if policy == "preferred":
        return Metric(HALF * HALF, "below recommended", bottom + "." + preferred)
    return Metric(HALF, "bottom 30%", bottom + ": apply test-optional and do not send it")


def rigor_metric(student, coursework):
    """Half school type (English curriculum / top Ukrainian / regular Ukrainian), half grades in the subjects of
    the student's major (strong / okay / weak)."""
    school = student.school_type or ("english" if student.curriculum in ENGLISH_CURRICULA else "")
    s = SCHOOL_POINTS.get(school, HALF)
    level, reason = coursework
    c = COURSEWORK_POINTS.get(level, HALF)
    school_label = dict(Student.SCHOOL_TYPE_CHOICES).get(school, "school type not rated")
    return Metric((s + c) / 2, f"{school_label.split(' (')[0].lower()}; coursework {level or 'unknown'}",
                  f"school: {school_label}{f' ({student.school_name})' if student.school_name else ''}; "
                  f"major-related coursework: {level or 'no grades'} ({reason})")


def gpa_metric(level, reason, d):
    if level is None:
        return Metric(HALF, "no grades", f"{reason}: half points")
    label = transcript.GPA_LEVELS[level]
    return Metric(step(RANK[level], RANK[d.gpa_bar]), label,
                  f"{label} ({reason}); college GPA bar {d.gpa_bar} ({d.gpa_bar_note})")


def class_rank_metric(level, reason, d):
    if level is None:
        return Metric(HALF, "no rank", f"{reason}: half points")
    label = transcript.RANK_LEVELS[level]
    return Metric(step(RANK[level], RANK[d.rank_bar]), label,
                  f"{reason}; college class-rank bar {d.rank_bar} ({d.rank_bar_note})")


def rated_metric(level, table, label, what):
    """A Gemini rating saved on the student: full, half or none; half until it is rated."""
    if not level:
        return Metric(HALF, "not rated", f"{what} not rated yet: half points")
    return Metric(table[level], label, f"{what}: {label}")


def major_metric(student, d):
    """0-1 from the majors graph. 0 (no major related to any of the top 20 programs) excludes the college."""
    wanted = [m for m in (student.major_1, student.major_2, student.major_3) if m]
    if not wanted:
        return Metric(HALF, "no majors", "no intended majors given")
    if not d.programs:
        return Metric(HALF, "no programs", "the college has no program list")
    if not any(majors.node(m) for m in wanted):
        return Metric(HALF, "not in the graph", f"{', '.join(wanted)}: not in the majors graph yet (half points)")
    weights = MAJOR_PREFERENCE[:len(wanted)]
    total, parts = 0.0, []
    for m, w in zip(wanted, weights):
        best, best_p = 0.0, None
        for prog in d.programs[:20]:
            v = majors.similarity(m, prog.name) * (1.0 - PROGRAM_RANK_STEP * (prog.position - 1))
            if v > best:
                best, best_p = v, prog
        total += w * best
        parts.append(f"{m} ~ {best_p.name} #{best_p.position} ({best:.2f})" if best_p else f"{m}: nothing close")
    value = total / sum(weights)
    if value == 0:
        raise Excluded(f"no programs related to {', '.join(wanted)} among its top 20")
    return Metric(value, f"{value:.2f}", "; ".join(parts))


def crowding_cut(applicants, capacity):
    """Share of the match taken off (0-0.2): UGS students with the college on their list (the student included,
    once they add it) against how many UGS students it usually admits a year. None up to 2x capacity, then
    growing evenly to 20% at 4x."""
    cap = capacity or 1
    free, full = CROWDING[0] * cap, CROWDING[1] * cap
    if applicants <= free:
        return 0.0
    if applicants >= full:
        return CROWDING_MAX_CUT
    return CROWDING_MAX_CUT * (applicants - free) / (full - free)


def character_metric(judgement):
    if judgement is None:
        return Metric(HALF, "not judged", "self-summary not judged yet")
    return Metric(VIBE_POINTS[judgement.level], judgement.get_level_display().lower(), judgement.reason)


# ---------------------------------------------------------------- scoring

@dataclass
class Row:
    d: CollegeData
    excluded: str = ""
    metrics: dict = field(default_factory=dict)
    match: float = 0.0
    recommended: bool = False


def student_levels(student):
    """The student-only inputs, worked out once per student."""
    return {"gpa": transcript.gpa_level(student), "class_rank": transcript.class_rank_level(student),
            "coursework": transcript.coursework_level(student),
            "vibes": {v.college_id: v for v in VibeJudgement.objects.filter(student=student)} if student.pk else {}}


def score(student, d, lv):
    """Row with either .excluded (the reason) or .metrics {key: Metric} and .match (0-100)."""
    p = d.profile
    if student.pronouns == "he" and p.student_body == "women":
        return Row(d, excluded="women's college (student uses he/him)")
    if student.pronouns == "she" and p.student_body == "men":
        return Row(d, excluded="men's college (student uses she/her)")
    try:
        det_gate(student, d)
        m = {"sat": sat_metric(student, d), "major": major_metric(student, d)}
    except Excluded as exc:
        return Row(d, excluded=str(exc))
    level = student.academic_tier
    m["rigor"] = rigor_metric(student, lv["coursework"])
    m["character"] = character_metric(lv["vibes"].get(d.college.unitid))
    m["gpa"] = gpa_metric(*lv["gpa"], d)
    m["talent"] = rated_metric(level, TALENT_POINTS, student.get_academic_tier_display().lower() if level else "",
                               "talent/ability")
    m["extracurricular"] = rated_metric(student.ec_level, LEVEL_POINTS, student.ec_level, "extracurricular activities")
    m["class_rank"] = class_rank_metric(*lv["class_rank"], d)
    m["volunteer"] = rated_metric(student.volunteer_level, LEVEL_POINTS, student.volunteer_level, "volunteer work")
    m["work"] = rated_metric(student.work_level, LEVEL_POINTS, student.work_level, "work experience")
    return Row(d, metrics=m, match=round(sum(d.points[k] * x.score for k, x in m.items()), 1))


def match_student(student, colleges):
    """(rows in list order, student levels): best preliminary match first (ties: majors, then name); excluded
    last."""
    lv = student_levels(student)
    rows = [score(student, d, lv) for d in colleges.values()]
    ok = sorted((r for r in rows if not r.excluded),
                key=lambda r: (-r.match, -r.metrics["major"].score, r.d.college.name))
    for r in ok[:LIST_SIZE]:
        r.recommended = True
    return ok + sorted((r for r in rows if r.excluded), key=lambda r: r.d.college.name), lv


def why(r):
    """One or two plain sentences: where the college gave full points and where points were lost."""
    if r.excluded:
        return f"Not possible: {r.excluded}."
    pts = r.d.points
    full = [LABELS[k] for k in ORDER if pts[k] >= 0.5 and r.metrics[k].score >= 0.999]
    lost = sorted(((pts[k] * (1 - r.metrics[k].score), k) for k in ORDER), reverse=True)
    lost = [f"{LABELS[k]} -{v:.1f} ({r.metrics[k].level})" for v, k in lost if v >= 0.5]
    parts = []
    if full:
        parts.append("Full points: " + ", ".join(full) + ".")
    if lost:
        parts.append("Lost points: " + "; ".join(lost) + ".")
    return " ".join(parts) or "Average on every measure."


def details(r):
    d = r.d
    out = {"intl_admit_rate": round(d.intl_rate, 1) if d.intl_rate is not None else None,
           "overall_admit_rate": round(d.overall_rate, 1) if d.overall_rate is not None else None,
           "why": why(r)}
    if r.excluded:
        out["excluded"] = r.excluded
        return out
    pts = r.d.points
    out["metrics"] = [{"key": k, "label": LABELS[k], "category": CATEGORY[k], "share": round(pts[k], 2),
                       "level": r.metrics[k].level, "score": round(r.metrics[k].score, 3),
                       "points": round(pts[k] * r.metrics[k].score, 2), "note": r.metrics[k].note} for k in ORDER]
    out["points_source"] = f"CDS {d.c7_year} C7" if d.c7 else "default points (no CDS C7)"
    if r.metrics["sat"].level == "bottom 30%":
        out["advice"] = "Apply test-optional: do not send the SAT."
    return out


def refresh_students(students=None):
    """Score the given students (default: everyone who submitted) and replace their results (the preliminary
    match; crowding is applied when they are shown). Each student gets their own run (method "student").
    Returns {student: (rows in list order, student levels)}."""
    students = list(Student.objects.filter(submitted_at__isnull=False) if students is None else students)
    colleges = load_colleges()
    out = {}
    for st in students:
        old = list(MatchRun.objects.filter(method="student", results__student=st).distinct())
        match_run = MatchRun.objects.create(method="student", created_by=st.code, label=f"{st.code} ({ENGINE})")
        rows, lv = match_student(st, colleges)
        out[st] = (rows, lv)
        MatchResult.objects.bulk_create([
            MatchResult(run=match_run, student=st, college=r.d.college, rank=rank,
                        match_pct=0.0 if r.excluded else r.match, excluded=bool(r.excluded), details=details(r))
            for rank, r in enumerate(rows, start=1)])
        for r in old:
            r.delete()
    return out


def latest_run(student):
    """The student's newest results."""
    return MatchRun.objects.filter(method="student", results__student=student).distinct().order_by("-created_at").first()


def crowding_state():
    """Changes whenever any submitted list or UGS capacity changes (the portal checks it to update live)."""
    from sources.students import applicant_counts

    caps = sorted(CollegeProfile.objects.exclude(ugs_capacity=None).values_list("college_id", "ugs_capacity"))
    return str(hash((tuple(sorted(applicant_counts().items())), tuple(caps))))


def with_crowding(results):
    """A student's saved results with the crowding cut, as the student sees them now:
    [{"r", "rank", "prelim", "cut" (%), "final", "applicants", "capacity", "recommended"}], best final match
    first; excluded colleges last."""
    from sources.students import applicant_counts

    counts = applicant_counts()
    caps = dict(CollegeProfile.objects.values_list("college_id", "ugs_capacity"))
    rows = []
    for r in results:
        n, cap = counts.get(r.college_id, 0), caps.get(r.college_id) or 1
        cut = 0.0 if r.excluded else crowding_cut(n, cap)
        rows.append({"r": r, "prelim": r.match_pct, "cut": round(100 * cut, 1), "applicants": n, "capacity": cap,
                     "final": round(r.match_pct * (1 - cut), 1), "recommended": False, "rank": None})
    ok = sorted((x for x in rows if not x["r"].excluded), key=lambda x: (-x["final"], -x["prelim"], x["r"].rank))
    for i, x in enumerate(ok, start=1):
        x["rank"], x["recommended"] = i, i <= LIST_SIZE
    return ok + [x for x in rows if x["r"].excluded]

