"""Transcript metrics from structured grades: GPA level, class-rank level and relevant coursework.

Student.subject_grades holds the latest grade per subject on the school's own scale; the scale
follows the curriculum:
    national ("No")  Ukrainian 12-point scale, 1-12
    IB               1-7 per subject, plus "Core (TOK/EE)": 0-3 bonus points
    A-levels         A*, A, B, C, D, E
    AP (US school)   letter grades A+ to F; AP courses start with "AP"
Each metric has three levels (the team's rules, docs/algorithm.md); None when there is no data.
"""

import re

from sources import majors

SCALE = {"no": "ua12", "ib": "ib", "alevels": "alevels", "ap": "us"}
SCALE_LABEL = {"ua12": "Ukrainian 12-point", "ib": "IB", "alevels": "A-levels", "us": "US grades"}
IB_CORE = "core (tok/ee)"
US_POINTS = {"A+": 4.0, "A": 4.0, "A-": 3.7, "B+": 3.3, "B": 3.0, "B-": 2.7, "C+": 2.3, "C": 2.0, "C-": 1.7,
             "D+": 1.3, "D": 1.0, "D-": 0.7, "F": 0.0}
A_LEVEL_POINTS = {"A*": 6, "A": 5, "B": 4, "C": 3, "D": 2, "E": 1, "U": 0}

# School subject -> subject group, by key words; the first match wins.
SUBJECT_GROUPS = [
    ("math", r"math|algebra|geometry|calculus|statistic"),
    ("physics", r"physic"),
    ("chemistry", r"chemi"),
    ("biology", r"biolog"),
    ("computer science", r"comput|informatic|programming|\bict\b"),
    ("economics", r"econom|business"),
    ("psychology", r"psycholog"),
    ("history", r"histor"),
    ("government", r"government|politic|\blaw\b|civics|jurisprudence"),
    ("geography", r"geograph"),
    ("literature", r"literat"),
    ("english", r"english"),
    ("languages", r"language|spanish|french|german|latin|chinese|polish"),
    ("arts", r"\bart\b|\barts\b|music|design|drawing"),
]

GPA_LEVELS = {"top": "will get in", "maybe": "maybe", "red": "red flags"}
RANK_LEVELS = {"top": "top 10%", "middle": "top 10-25%", "low": "below the top 25%"}
COURSEWORK_LEVELS = {"strong": "strong", "okay": "okay", "weak": "weak"}


def scale(student):
    return SCALE.get(student.curriculum or "no", "ua12")


def subject_group(name):
    key = (name or "").lower()
    return next((g for g, rx in SUBJECT_GROUPS if re.search(rx, key)), None)


def parse_grades(text):
    """'Biology: 11' lines -> {"Biology": 11}. Numbers become ints; letter grades stay text."""
    out = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        subject, grade = (x.strip() for x in line.rsplit(":", 1))
        if subject and grade:
            out[subject] = int(grade) if re.fullmatch(r"\d{1,2}", grade) else grade.upper().replace(" ", "")
    return out


def format_grades(grades):
    return "\n".join(f"{k}: {v}" for k, v in (grades or {}).items())


def _value(grade, sc):
    """A grade as a number on its own scale (US: 4.0 points; A-levels: A* = 6 ... E = 1), or None."""
    if sc in ("ua12", "ib"):
        try:
            return float(grade)
        except (TypeError, ValueError):
            return None
    table = A_LEVEL_POINTS if sc == "alevels" else US_POINTS
    return table.get(str(grade).strip().upper())


def graded(student):
    """[(subject, grade as written, value)] without the IB core bonus; unreadable grades left out."""
    sc = scale(student)
    out = []
    for subject, grade in (student.subject_grades or {}).items():
        if subject.strip().lower() == IB_CORE:
            continue
        v = _value(grade, sc)
        if v is not None:
            out.append((subject, grade, v))
    return out


# ---------------------------------------------------------------- GPA

def gpa_level(student):
    """('top' | 'maybe' | 'red' | None, reason) by the team's rules for each curriculum."""
    sc, items = scale(student), graded(student)
    if items:
        values = [v for _, _, v in items]
        if sc == "ua12":
            n89, low = sum(1 for v in values if 8 <= v <= 9), min(values)
            where = f"Ukrainian grades: average {sum(values) / len(values):.1f}, lowest {low:.0f}, {n89} of {len(values)} are 8-9"
            if low >= 10:
                return "top", where + " (all 10+ = will get in)"
            if low >= 8 and n89 <= len(values) / 3:
                return "maybe", where + " (a few 8-9s = maybe)"
            return "red", where + " (consistent 8-9s or lower = red flags)"
        if sc == "ib":
            best6 = sorted(values, reverse=True)[:6]
            core = next((g for k, g in student.subject_grades.items() if k.strip().lower() == IB_CORE), 0)
            total = round(sum(best6) * 6 / len(best6) + (_value(core, "ib") or 0))
            where = f"IB {total}/45"
            return ("top" if total >= 42 else "maybe" if total >= 36 else "red"), where + " (42+ will get in, 36-41 maybe)"
        if sc == "alevels":
            grades = [g for _, g, _ in items]
            stars, a = grades.count("A*"), grades.count("A")
            below_a = [g for g in grades if g not in ("A*", "A")]
            where = f"A-levels {''.join(grades)}"
            if stars > a and not below_a:
                return "top", where + " (more A* than A = will get in)"
            if all(g == "B" for g in below_a) and len(below_a) <= 1:
                return "maybe", where + " (at most one B = maybe)"
            return "red", where + " (two or more B, or lower = red flags)"
        if sc == "us":
            gpa = sum(values) / len(values)
            ap = [(s, g, v) for s, g, v in items if s.strip().upper().startswith("AP")]
            weak_ap = [s for s, _, v in ap if v <= 3.3]
            where = f"US GPA {gpa:.2f} unweighted, {len(ap)} AP courses"
            if gpa >= 3.85 and ap and not weak_ap:
                return "top", where + ", A/A- in every AP course (= will get in)"
            if len(weak_ap) >= 2 or gpa < 3.3:
                return "red", where + (f", B+ or lower in {len(weak_ap)} AP courses" if len(weak_ap) >= 2 else "") + " (= red flags)"
            return "maybe", where + " (about 3.5 with advanced courses = maybe)"
    if student.gpa is not None:
        g = float(student.gpa)
        return ("top" if g >= 3.9 else "maybe" if g >= 3.5 else "red"), f"GPA {g:.2f}/4 (no grades by subject)"
    return None, "no grades yet"


# ---------------------------------------------------------------- class rank

def class_rank_level(student):
    """('top' | 'middle' | 'low' | None, reason) from the class rank (top X%)."""
    pct = student.class_top_pct
    if pct is None:
        return None, "no class rank"
    level = "top" if pct <= 10 else "middle" if pct <= 25 else "low"
    return level, f"top {pct:g}% of the class"


# ---------------------------------------------------------------- relevant coursework

def coursework_level(student):
    """('strong' | 'okay' | 'weak' | None, reason): grades in the subjects that matter for the
    student's first major (the one they apply with); if it has none on the transcript, the next major."""
    sc, items = scale(student), graded(student)
    for major in (student.major_1, student.major_2, student.major_3):
        groups = majors.relevant_subjects(major)
        rel = [(s, g, v) for s, g, v in items if subject_group(s) in groups]
        if not groups or not rel:
            continue
        values = [v for _, _, v in rel]
        avg, low = sum(values) / len(values), min(values)
        shown = ", ".join(f"{s} {g}" for s, g, _ in rel)
        if sc == "ua12":
            level = "strong" if avg >= 10.5 and low >= 10 else "okay" if avg >= 9 else "weak"
        elif sc == "ib":
            level = "strong" if low >= 6 else "okay" if avg >= 5 else "weak"
        elif sc == "alevels":
            level = "strong" if low >= 5 else "okay" if low >= 4 and sum(1 for v in values if v < 5) <= 1 else "weak"
        else:
            level = "strong" if avg >= 3.7 and low >= 3.3 else "okay" if avg >= 3.0 else "weak"
        return level, f"for {majors.node(major) or major}: {shown}"
    return None, "no grades in the subjects for the student's majors"
