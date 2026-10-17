"""Admin dashboard: college profiles, programs, and the evidence behind them.

Every page requires login (LoginRequiredMiddleware). Edits are saved on the
server: profile edits go through sources.profile.set_field with source
"manual", so imports never overwrite them and FieldHistory shows who changed what.
"""

import json
from collections import defaultdict
from pathlib import Path

from django import forms
from django.conf import settings
from django.db.models import Count, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from colleges.columns import BY_KEY, CHOICE_ORDER, ordered_columns, save_order, settings_by_key
from colleges.forms import ColumnSettingForm, ProgramForm, profile_form_class
from colleges.models import (AIAnswer, College, ColumnSetting, CollegeProfile, FieldHistory, Program, SourceRecord,
                             Student, StudentFile, StudentIdentity)
from sources.profile import get_profile, latest_sources, set_field
from sources.programs import best_list
from sources.students import applicant_counts

SOURCE_LABELS = {
    "cds": "CDS", "ipeds": "IPEDS", "hubspot": "HubSpot", "official_site": "Official site",
    "ai": "AI (LLM)", "manual": "Edited by hand", "niche": "Niche", "ugs": "UGS recommendation", "web": "Web research",
}


def _hubspot_items(college_id=None):
    """{unitid: [SourceRecord]} of HubSpot calls/notes/meetings/tasks, newest first."""
    qs = SourceRecord.objects.filter(source="hubspot").exclude(kind="hubspot_company")
    if college_id is not None:
        qs = qs.filter(college_id=college_id)
    out = defaultdict(list)
    for r in qs.only("id", "college_id", "kind", "title", "raw_text", "raw_json"):
        out[r.college_id].append(r)
    for items in out.values():
        items.sort(key=lambda r: (r.raw_json or {}).get("timestamp") or "", reverse=True)
    return out


def _programs_by_college():
    out = defaultdict(list)
    for p in Program.objects.order_by("position"):
        out[p.college_id].append(p)
    return out


def _sort_value(col, profile, programs, hubspot_items):
    p = profile
    if col.kind == "body":
        return p.student_body
    if col.kind == "det":
        return p.det_minimum or p.det_recommended or ""
    if col.kind == "sat":
        return p.sat_median or ""
    if col.kind == "gpa":
        return float(p.gpa_average) if p.gpa_average is not None else ""
    if col.kind == "perf":
        return p.gpa_375_pct if p.gpa_375_pct is not None else (p.top10_pct if p.top10_pct is not None else "")
    if col.kind == "choice":
        return CHOICE_ORDER.get(getattr(p, col.fields[0]), "")
    if col.kind == "programs":
        return programs[0].name.lower() if programs else ""
    if col.kind == "hubspot":
        return len(hubspot_items)
    if col.kind == "number":
        v = getattr(p, col.fields[0])
        return v if v is not None else ""
    if col.kind == "ugs_avg":
        return p.ugs_admits_avg if p.ugs_admits_avg is not None else ""
    if col.kind == "intl_aid":
        return p.intl_aid_total if p.intl_aid_total is not None else ""
    if col.kind == "full_rides":
        return p.full_rides.lower()
    return (getattr(p, col.fields[0]) or "").lower()[:40]


def render_cell(col, college, profile, programs, hubspot_items, provenance, full=False, applicants=0):
    """{'html', 'sort'} for one dashboard cell. full=True shows texts untruncated (college page)."""
    source = None
    for f in col.fields:
        source = provenance.get((college.unitid, f))
        if source:
            break
    top3 = best_list(programs)[:3] if col.kind == "programs" else []
    html = render_to_string("colleges/_cell.html", {
        "col": col, "college": college, "p": profile, "top3": top3, "hubspot_items": hubspot_items,
        "source": source, "source_label": SOURCE_LABELS.get(source.source, source.source) if source else "",
        "short": 100000 if full else 140, "long": 100000 if full else 260, "applicants": applicants,
    })
    sort = applicants if col.kind == "applicants" else _sort_value(col, profile, top3, hubspot_items)
    return {"html": html, "sort": sort}


def dashboard(request):
    colleges = list(College.objects.order_by("name"))
    profiles = {p.college_id: p for p in CollegeProfile.objects.all()}
    for c in colleges:
        if c.unitid not in profiles:
            profiles[c.unitid] = get_profile(c)
    cols = ordered_columns()
    visible = [(c, s) for c, s in cols if s.visible]
    provenance = latest_sources()
    programs = _programs_by_college()
    hubspot = _hubspot_items()
    counts = applicant_counts()
    rows = []
    for c in colleges:
        cells = []
        for col, setting in visible:
            cell = render_cell(col, c, profiles[c.unitid], programs.get(c.unitid, []), hubspot.get(c.unitid, []), provenance,
                               applicants=counts.get(c.unitid, 0))
            cell["col"] = col
            cells.append(cell)
        rows.append({"college": c, "cells": cells})
    return render(request, "colleges/dashboard.html", {
        "columns": visible, "hidden": [s for c, s in cols if not s.visible], "rows": rows,
        "hidden_keys": json.dumps([s.key for c, s in cols if not s.visible]),
        "sources": SOURCE_LABELS,
    })


def cell_edit(request, unitid, key):
    college = get_object_or_404(College, unitid=unitid)
    col = BY_KEY.get(key)
    if col is None or not col.fields:
        raise Http404
    profile = get_profile(college)
    FormClass = profile_form_class(col.fields)
    if request.method == "POST":
        form = FormClass(request.POST, instance=CollegeProfile.objects.get(pk=profile.pk))
        if form.is_valid():
            user = request.user.get_username()
            for field in form.changed_data:
                set_field(college, field, form.cleaned_data[field], FieldHistory.SOURCE_MANUAL,
                          "Edited on the dashboard", user=user)
            profile.refresh_from_db()
            programs = list(Program.objects.filter(college=college).order_by("position"))
            cell = render_cell(col, college, profile, programs, _hubspot_items(unitid).get(unitid, []),
                               latest_sources([unitid]), full=request.GET.get("full") == "1",
                               applicants=applicant_counts().get(unitid, 0))
            return JsonResponse(cell)
        status = 400
    else:
        form = FormClass(instance=profile)
        status = 200
    history = FieldHistory.objects.filter(college=college, field__in=col.fields)[:8]
    setting = settings_by_key()[col.key]
    return render(request, "colleges/_edit_form.html", {
        "form": form, "title": f"{college.name}: {setting.label}", "help": setting.description,
        "action": request.get_full_path(), "history": history, "sources": SOURCE_LABELS,
    }, status=status)


def column_edit(request, key):
    if key not in BY_KEY:
        raise Http404
    setting = settings_by_key()[key]
    if request.method == "POST":
        form = ColumnSettingForm(request.POST, instance=setting)
        if form.is_valid():
            form.save()
            return JsonResponse({"label": setting.label, "description": setting.description, "visible": setting.visible})
        status = 400
    else:
        form = ColumnSettingForm(instance=setting)
        status = 200
    return render(request, "colleges/_edit_form.html", {
        "form": form, "title": f"Column: {setting.label}", "action": request.path,
        "help": "Rename the column, change its description, or hide it. Changes apply for everyone.",
    }, status=status)


@require_POST
def column_order(request):
    """Save the column order after a drag-and-drop on the dashboard header."""
    keys = json.loads(request.body or "[]")
    save_order(keys)
    return JsonResponse({"ok": True})


def programs_grid(request):
    """One row per college; columns #1..#20 hold its programs from strongest to weakest."""
    from sources.programs import similarity

    similar_to = request.GET.get("similar")
    colleges = list(College.objects.order_by("name"))
    by_college = _programs_by_college()
    lists = {c.unitid: best_list(by_college.get(c.unitid, [])) for c in colleges}
    width = max((len(l) for l in lists.values()), default=0)
    sims = {}
    if similar_to and similar_to.isdigit() and int(similar_to) in lists:
        base = lists[int(similar_to)]
        sims = {u: similarity(base, l) for u, l in lists.items()}
        colleges.sort(key=lambda c: -sims[c.unitid])
    rows = [{"college": c, "sim": sims.get(c.unitid),
             "cells": lists[c.unitid] + [None] * (width - len(lists[c.unitid]))} for c in colleges]
    names = sorted({p.name for l in lists.values() for p in l})
    return render(request, "colleges/programs_grid.html", {
        "rows": rows, "positions": range(1, width + 1), "similar_to": similar_to or "",
        "all_colleges": College.objects.order_by("name"), "program_names": names, "sources": SOURCE_LABELS,
    })


def programs_page(request):
    qs = Program.objects.select_related("college").order_by("college__name", "source", "position")
    college_id = request.GET.get("college")
    source = request.GET.get("source")
    q = request.GET.get("q", "").strip()
    if college_id:
        qs = qs.filter(college_id=college_id)
    if source:
        qs = qs.filter(source=source)
    if q:
        qs = qs.filter(name__icontains=q)
    return render(request, "colleges/programs.html", {
        "programs": qs, "colleges": College.objects.order_by("name"),
        "sources": Program.objects.values_list("source", flat=True).distinct(),
        "college_id": college_id or "", "source": source or "", "q": q,
    })


def program_edit(request, pk):
    program = get_object_or_404(Program, pk=pk)
    if request.method == "POST":
        form = ProgramForm(request.POST, instance=program)
        if form.is_valid():
            program = form.save(commit=False)
            program.updated_by = request.user.get_username()  # imports keep rows edited by hand
            program.save()
            return JsonResponse({"html": render_to_string("colleges/_program_row.html", {"p": program}, request=request)})
        status = 400
    else:
        form = ProgramForm(instance=program)
        status = 200
    return render(request, "colleges/_edit_form.html", {
        "form": form, "title": f"{program.college.name}: program", "action": request.path,
        "delete_url": f"/programs/{program.pk}/delete/",
    }, status=status)


def program_add(request, unitid):
    college = get_object_or_404(College, unitid=unitid)
    if request.method == "POST":
        form = ProgramForm(request.POST)
        if form.is_valid():
            program = form.save(commit=False)
            program.college, program.source = college, "manual"
            program.updated_by = request.user.get_username()
            program.save()
            return JsonResponse({"reload": True})
        status = 400
    else:
        n = Program.objects.filter(college=college, source="manual").count()
        form = ProgramForm(initial={"position": n + 1})
        status = 200
    return render(request, "colleges/_edit_form.html", {
        "form": form, "title": f"{college.name}: add a program",
        "help": "Programs you add form this college's own list, which takes priority over Niche and IPEDS "
                "for the Top 3 column.", "action": request.path,
    }, status=status)


@require_POST
def program_delete(request, pk):
    get_object_or_404(Program, pk=pk).delete()
    return JsonResponse({"reload": True})


def college_detail(request, unitid):
    college = get_object_or_404(College, unitid=unitid)
    profile = get_profile(college)
    provenance = latest_sources([unitid])
    programs = list(Program.objects.filter(college=college).order_by("position"))
    hubspot = SourceRecord.objects.filter(source="hubspot", college=college).exclude(kind="hubspot_company")
    hubspot = sorted(hubspot, key=lambda r: (r.raw_json or {}).get("timestamp") or "", reverse=True)
    cells = []
    for col, setting in ordered_columns():
        cell = render_cell(col, college, profile, programs, hubspot, provenance, full=True,
                           applicants=applicant_counts().get(unitid, 0))
        cells.append({"col": col, "setting": setting, **cell})
    return render(request, "colleges/college.html", {
        "college": college, "cells": cells, "hubspot": hubspot,
        "programs": best_list(programs), "all_programs": programs,
        "ai_answers": AIAnswer.objects.filter(college=college)[:9],
        "history": FieldHistory.objects.filter(college=college)[:60],
        "documents": SourceRecord.objects.filter(college=college, source="cds"),
        "sources": SOURCE_LABELS,
    })


def record_detail(request, pk):
    record = get_object_or_404(SourceRecord.objects.select_related("college"), pk=pk)
    return render(request, "colleges/record.html", {"record": record, "facts": record.facts.order_by("section", "key")})


def record_file(request, pk):
    """Serve the original file (e.g. a CDS PDF) from data/. Local use only."""
    record = get_object_or_404(SourceRecord, pk=pk)
    if not record.file_path:
        raise Http404
    path = (settings.DATA_DIR / record.file_path).resolve()
    if settings.DATA_DIR.resolve() not in path.parents or not path.exists():
        raise Http404
    return FileResponse(open(path, "rb"), filename=Path(path).name)


# ---------------------------------------------------------------- students

def _student_sort(col, st):
    if col.kind in ("s_gpa", "s_perf"):  # by level: GPA (will get in first), class rank (top 10% first)
        from sources import transcript

        level = (transcript.gpa_level(st) if col.kind == "s_gpa" else transcript.class_rank_level(st))[0]
        return {"top": 3, "maybe": 2, "middle": 2, "red": 1, "low": 1}.get(level, "")
    if col.kind == "s_rated":  # by the first level, best first
        v = getattr(st, col.fields[1])
        return {"very_strong": 3, "strong": 2, "moderate": 1, "high": 3, "medium": 2, "low": 1,
                "english": 3, "top_ua": 2, "regular_ua": 1}.get(v, "")
    v = getattr(st, col.fields[0])
    if v is None or v == "":
        return ""
    if hasattr(v, "is_integer") or isinstance(v, (int, float)) or col.kind == "s_number":
        return float(v)
    return str(v).lower()[:40]


def _ratings(col, st):
    """The Gemini-rated levels of an s_rated column: label, level, and Gemini's reason or "set by hand"."""
    from colleges.columns import RATED_FIELDS

    read = (st.attributes or {}).get("profile_read") or {}
    out = []
    for f in col.fields[1:]:
        value, key = getattr(st, f), RATED_FIELDS[f]
        by_gemini = value and read.get(key) == value
        out.append({"label": Student._meta.get_field(f).verbose_name, "value": value,
                    "display": getattr(st, f"get_{f}_display")(),
                    "note": f"Gemini: {read['reasons'].get(key, '')}" if by_gemini else ("set by hand" if value else "")})
    return out


def render_student_cell(col, st, full=False):
    html = render_to_string("colleges/_student_cell.html", {
        "col": col, "s": st, "ratings": _ratings(col, st) if col.kind == "s_rated" else [],
        "short": 100000 if full else 140, "long": 100000 if full else 260,
    })
    return {"html": html, "sort": _student_sort(col, st)}


def _student_name(st):
    from sources.crypto import decrypt

    identity = getattr(st, "identity", None)
    return decrypt(identity.name_encrypted) if identity else ""


def students_page(request):
    from colleges.columns import student_columns

    cols = student_columns()
    rows = []
    for st in (Student.objects.select_related("identity", "user")
               .annotate(n_files=Count("files", distinct=True),
                         n_review=Count("files", filter=Q(files__needs_verification=True), distinct=True))
               .prefetch_related("choices__college")):
        cells = [dict(render_student_cell(c, st), col=c) for c in cols]
        rows.append({"s": st, "name": _student_name(st), "cells": cells, "choices": list(st.choices.all())})
    rows.sort(key=lambda r: r["name"].lower())
    return render(request, "colleges/students.html", {"rows": rows, "columns": cols})


def student_cell_edit(request, code, key):
    from colleges.columns import STUDENT_COLUMNS

    st = get_object_or_404(Student, code=code)
    col = STUDENT_COLUMNS.get(key)
    if col is None:
        raise Http404
    from colleges.forms import SubjectGradesField

    FormClass = forms.modelform_factory(
        Student, fields=list(col.fields),
        widgets={f: forms.Textarea(attrs={"rows": 5}) for f in col.fields
                 if Student._meta.get_field(f).get_internal_type() == "TextField"},
        field_classes={"subject_grades": SubjectGradesField} if "subject_grades" in col.fields else None)
    if request.method == "POST":
        form = FormClass(request.POST, instance=st)
        if form.is_valid():
            st = form.save()
            if st.submitted_at:  # the student's matches follow the edit
                from sources import matching

                matching.refresh_students(Student.objects.filter(pk=st.pk))
            return JsonResponse(render_student_cell(col, st, full=request.GET.get("full") == "1"))
        status = 400
    else:
        form = FormClass(instance=st)
        status = 200
    help_text = col.description
    if "academic_tier" in col.fields:
        from colleges.columns import ACADEMIC_TIER_MEANING

        help_text += " " + " ".join(f"{dict(Student.ACADEMIC_TIER_CHOICES)[k]}: {v}" for k, v in ACADEMIC_TIER_MEANING.items())
    return render(request, "colleges/_edit_form.html", {
        "form": form, "title": f"{_student_name(st) or st.code}: {col.label}", "help": help_text,
        "action": request.get_full_path(),
    }, status=status)


class StudentNameForm(forms.Form):
    name = forms.CharField(max_length=200, help_text="Stored encrypted; never sent to AI models.")


def student_name_edit(request, code=None):
    """Edit a student's name, or create a new student when code is None."""
    from sources.crypto import MissingKey, encrypt

    st = get_object_or_404(Student, code=code) if code else None
    if request.method == "POST":
        form = StudentNameForm(request.POST)
        if form.is_valid():
            try:
                token = encrypt(form.cleaned_data["name"].strip())
            except MissingKey:
                form.add_error(None, "STUDENT_DATA_KEY is not set in .env, so names cannot be stored.")
            else:
                st = st or Student.objects.create()
                identity, _ = StudentIdentity.objects.get_or_create(student=st)
                identity.name_encrypted = token
                identity.save()
                return JsonResponse({"reload": True})
        status = 400
    else:
        form = StudentNameForm(initial={"name": _student_name(st) if st else ""})
        status = 200
    return render(request, "colleges/_edit_form.html", {
        "form": form, "title": "Add a student" if st is None else f"Name of {st.code}",
        "help": "Names are stored encrypted and never sent to AI models.", "action": request.path,
    }, status=status)


@require_POST
def student_delete(request, code):
    from sources.students import delete_student

    delete_student(get_object_or_404(Student, code=code))
    return redirect("/students/")


def student_detail(request, code):
    from colleges.columns import student_columns

    st = get_object_or_404(Student.objects.select_related("identity"), code=code)
    cells = [dict(render_student_cell(c, st, full=True), col=c) for c in student_columns()]
    return render(request, "colleges/student.html", {
        "s": st, "name": _student_name(st), "cells": cells, "files": st.files.all(),
    })


def student_file(request, code, pk):
    """Serve a student's file (login required). Only paths inside data/students/ are allowed."""
    f = get_object_or_404(StudentFile, pk=pk, student__code=code)
    base = settings.STUDENT_FILES_DIR.resolve()
    path = (base / f.file_path).resolve()
    if base not in path.parents or not path.exists():
        raise Http404
    return FileResponse(open(path, "rb"), filename=f.original_name or path.name)


# ---------------------------------------------------------------- match

def match_page(request):
    """Each student's own results: computed when they submit and again whenever any college list changes."""
    from colleges.models import MatchRun
    from sources import matching

    ids = MatchRun.objects.filter(method="student").values_list("results__student_id", flat=True).distinct()
    students = sorted(((st, _student_name(st)) for st in Student.objects.filter(pk__in=ids).select_related("identity")),
                      key=lambda x: x[1].lower())
    code = request.GET.get("student")
    student = next((st for st, _ in students if st.code == code), None) or (students[0][0] if students else None)
    rows, choice_ranks, run = [], {}, None
    if student:
        run = matching.latest_run(student)
        rows = matching.with_crowding(run.results.filter(student=student).select_related("college"))
        choice_ranks = {c.college_id: c.rank for c in student.choices.all()}
    profiles = {p.college_id: p for p in CollegeProfile.objects.filter(college_id__in=[x["r"].college_id for x in rows])}
    for x in rows:
        x["choice"], x["profile"] = choice_ranks.get(x["r"].college_id), profiles.get(x["r"].college_id)
    read = (student.attributes or {}).get("profile_read") if student else None
    profile_read = [(label, getattr(student, f"get_{field}_display")(), read["reasons"].get(key, ""))
                    for key, label, field in [("school_type", "School type", "school_type"),
                                              ("talent", "Talent/ability", "academic_tier"),
                                              ("extracurricular", "Extracurricular", "ec_level"),
                                              ("volunteer", "Volunteer work", "volunteer_level"),
                                              ("work", "Work experience", "work_level")]] if read else []
    return render(request, "colleges/match.html", {
        "students": students, "student": student, "run": run,
        "student_name": _student_name(student) if student else "", "rows": rows, "top_n": matching.LIST_SIZE,
        "listed": [x for x in rows if x["recommended"]],
        "others": [x for x in rows if not x["r"].excluded and not x["recommended"]],
        "excluded": [x for x in rows if x["r"].excluded],
        "vibe_read": (student.attributes or {}).get("vibe_read") if student else None,
        "profile_read": profile_read, "profile_model": read.get("model") if read else "",
        "points": [(matching.LABELS[k], matching.CATEGORY[k], matching.POINTS[k]) for k in matching.ORDER],
        "crowding": {"free": matching.CROWDING[0], "full": matching.CROWDING[1], "cut": round(100 * matching.CROWDING_MAX_CUT)},
        "n_submitted": Student.objects.filter(submitted_at__isnull=False).count(), "n_students": Student.objects.count(),
    })


def _flow_map():
    """Nodes and edges of the "How the match is built" map on College weights: the student's answers -> the metrics
    (CDS C7 factors and majors) -> academic / personal / fit -> preliminary match -> UGS applicants cut -> final match.
    Positions are computed here; the template draws them as SVG."""
    from sources import matching

    H, GAP = 40, 10
    cols = {"input": (0, 200), "metric": (265, 265), "cat": (600, 150), "prelim": (800, 150), "cut": (1000, 165),
            "final": (1215, 115)}
    width = cols["final"][0] + cols["final"][1]
    nodes, edges = {}, []

    def node(nid, col, y, title, sub, cls, help_text, h=H, ai=False, rule=False):
        x, w = cols[col]
        nodes[nid] = {"id": nid, "x": x, "y": round(y), "w": w, "h": h, "title": title, "sub": sub, "cls": cls,
                      "help": help_text, "ai": ai, "rule": rule}

    inputs = [i for i in matching.INPUTS if "crowding" not in i[3]]
    for i, (key, label, ai, targets, note) in enumerate(inputs):
        rule = "rules" in targets
        sub = "rated by Gemini" if ai else ("hard rule only" if targets == ["rules"] else "+ hard rule" if rule else "")
        node(f"in-{key}", "input", i * (H + GAP), label, sub, "input", note, ai=ai, rule=rule)
    height = len(inputs) * (H + GAP) - GAP
    mh, mgap = 44, 9
    top = max(0, (height - len(matching.ORDER) * (mh + mgap) + mgap) / 2)
    for i, k in enumerate(matching.ORDER):
        f = matching.C7_FACTORS.get(k)
        sub = (f"C7: {matching.C7_NAMES[f]}" if f else "same at every college") + f" · {matching.POINTS[k]:.1f} pts"
        node(f"m-{k}", "metric", top + i * (mh + mgap), matching.LABELS[k], sub, matching.CATEGORY[k],
             matching.METRIC_HELP[k], h=mh)
    cat_help = {"Academic": "Test scores and the school record.",
                "Personal": "Character, talent and what the student does outside class.",
                "Fit": "How well the college's strongest programs fit the student's majors."}
    for name, keys in matching.CATEGORIES.items():
        ys = [nodes[f"m-{k}"]["y"] for k in keys]
        mid = (min(ys) + max(ys) + mh) / 2
        node(f"c-{name}", "cat", mid - 24, name, f"{sum(matching.POINTS[k] for k in keys):.1f} pts by default", name,
             cat_help[name] + " Each college's own points follow its CDS C7 (table below).", h=48)
        for k in keys:
            edges.append((f"m-{k}", f"c-{name}", name))
    node("rules", "cat", nodes["c-Fit"]["y"] + 48 + 36, "Hard rules", "before the points: excluded", "rules",
         "Excluded when: DET below the college's minimum or recommended score (or the UGS 135); SAT below a published "
         "minimum, or none / bottom 30% where scores are required; he/him at a women's college; majors with no "
         "relation to the top 20 programs.", h=50)
    mid = (nodes["c-Academic"]["y"] + nodes["c-Fit"]["y"] + 48) / 2
    node("prelim", "prelim", mid - 30, "Preliminary match", "points earned, out of 100", "prelim",
         "The sum of the points the student earned in the ten metrics, out of 100.", h=60)
    node("cut", "cut", mid - 30, "UGS applicants", f"after the match: up to −{round(100 * matching.CROWDING_MAX_CUT)}%",
         "after", f"UGS students with the college on their list against its UGS capacity (average UGS students a year, "
         f"last 3 years): no cut up to {matching.CROWDING[0]}x, then growing evenly to "
         f"−{round(100 * matching.CROWDING_MAX_CUT)}% at {matching.CROWDING[1]}x. Updates live as lists change.", h=60)
    node("final", "final", mid - 30, "Final match", "what students see", "prelim",
         "Preliminary match minus the UGS applicants cut. Students see this, best first. Not a chance of admission.", h=60)
    height = max(height, nodes["rules"]["y"] + 50)
    for name in matching.CATEGORIES:
        edges.append((f"c-{name}", "prelim", "prelim"))
    edges += [("prelim", "cut", "after"), ("cut", "final", "after")]
    for key, label, _, targets, note in matching.INPUTS:
        if "crowding" in targets:   # the other students' lists: below the UGS applicants box, feeding it from below
            node(f"in-{key}", "cut", nodes["cut"]["y"] + 140, label, "every submitted student", "input", note, h=48)
            edges.append((f"in-{key}", "cut", "after"))
            continue
        edges += [(f"in-{key}", f"m-{t}", matching.CATEGORY[t]) for t in targets if t in matching.CATEGORY]
    paths = []
    for a, b, cls in edges:
        na, nb = nodes[a], nodes[b]
        if na["x"] == nb["x"]:   # stacked boxes: straight up
            x = na["x"] + na["w"] / 2
            paths.append({"d": f"M{x:.0f},{na['y']} L{x:.0f},{nb['y'] + nb['h']}", "cls": cls, "a": a, "b": b})
            continue
        x1, y1, x2, y2 = na["x"] + na["w"], na["y"] + na["h"] / 2, nb["x"], nb["y"] + nb["h"] / 2
        dx = (x2 - x1) / 2
        paths.append({"d": f"M{x1:.0f},{y1:.0f} C{x1 + dx:.0f},{y1:.0f} {x2 - dx:.0f},{y2:.0f} {x2:.0f},{y2:.0f}",
                      "cls": cls, "a": a, "b": b})
    return {"nodes": list(nodes.values()), "edges": paths, "width": width, "height": height + 4,
            "headers": [("Student's answers", cols["input"]), ("Metrics (CDS C7) + majors", cols["metric"]),
                        ("Categories", cols["cat"]), ("", cols["prelim"]), ("", cols["cut"]), ("", cols["final"])]}


def college_weights(request):
    """Each college's points out of 100 per metric, from its CDS C7 (what it says matters in admission), grouped
    by category; and, apart, the crowding cut applied after the match."""
    from sources import matching

    counts = applicant_counts()
    rows = []
    for d in sorted(matching.load_colleges().values(), key=lambda d: d.college.name):
        cells = []
        for k in matching.ORDER:
            f = matching.C7_FACTORS.get(k)
            why = f"{matching.C7_NAMES[f]}: {matching.C7_LEVELS[d.c7[f]]}" if f in d.c7 else ""
            if k in matching.FIXED:
                why = "Same for every college (team's points)"
            elif not d.c7:
                why = "No CDS C7: team's points"
            elif not why:
                why = f"{matching.C7_NAMES[f]}: left blank in the CDS, counted as important"
            diff = d.points[k] - matching.POINTS[k]
            cells.append({"points": d.points[k], "why": why, "category": matching.CATEGORY[k],
                          "diff": "more" if diff > 0.05 else "less" if diff < -0.05 else ""})
        n, cap = counts.get(d.college.unitid, 0), d.profile.ugs_capacity or 1
        rows.append({"college": d.college, "source": f"CDS {d.c7_year} C7" if d.c7 else "team default points",
                     "chunks": [(name, sum(d.points[k] for k in ks)) for name, ks in matching.CATEGORIES.items()],
                     "cells": cells, "applicants": n, "capacity": cap,
                     "cut": round(100 * matching.crowding_cut(n, cap), 1)})
    return render(request, "colleges/college_weights.html", {
        "rows": rows,
        "metrics": [(matching.LABELS[k], matching.POINTS[k], matching.CATEGORY[k]) for k in matching.ORDER],
        "chunks": [(name, sum(matching.POINTS[k] for k in ks)) for name, ks in matching.CATEGORIES.items()],
        "multipliers": [(matching.C7_LEVELS[lvl], m) for lvl, m in matching.C7_MULTIPLIER.items()],
        "crowding": {"free": matching.CROWDING[0], "full": matching.CROWDING[1], "cut": round(100 * matching.CROWDING_MAX_CUT)},
        "flow": _flow_map(),
    })


def ugs_results(request):
    """UGS's admissions results by college and year: our colleges and the others in the team's sheet."""
    from sources import ugs_history

    stored = ugs_history.stored_table()
    if not stored:
        return render(request, "colleges/ugs_results.html", {"rows": [], "years": []})
    years = [str(y) for y in stored["years"]]
    ours = {c.unitid: c for c in College.objects.select_related("profile")}
    counts = applicant_counts()
    rows, seen = [], set()
    for name, admits in stored["colleges"].items():
        college = ours.get(stored["unitids"].get(name))
        if college:
            seen.add(college.unitid)
        rows.append({"name": college.name if college else name.rstrip("* ").strip(), "sheet_name": name,
                     "college": college, "admits": [admits.get(y, 0) for y in years]})
    for unitid, college in ours.items():   # on our list, never in the sheet
        if unitid not in seen:
            rows.append({"name": college.name, "sheet_name": "", "college": college, "admits": [0] * len(years)})
    for r in rows:
        r["total"] = sum(r["admits"])
        r["avg"] = r["total"] / len(years)
        r["capacity"] = r["college"].profile.ugs_capacity if r["college"] and hasattr(r["college"], "profile") else None
        r["applicants"] = counts.get(r["college"].unitid, 0) if r["college"] else None
    rows.sort(key=lambda r: (-r["total"], r["name"]))
    totals = [sum(r["admits"][i] for r in rows) for i in range(len(years))]
    return render(request, "colleges/ugs_results.html", {
        "rows": rows, "years": years, "totals": totals, "grand_total": sum(totals), "file": stored["file"],
        "n_ours": sum(1 for r in rows if r["college"]), "recent": years[-ugs_history.RECENT_YEARS:],
    })


def majors_graph(request):
    """The majors graph (sources/majors.py) used by the Majors metric of the matching engine."""
    from collections import Counter

    from colleges.models import Program
    from sources import majors

    wanted = Counter(majors.node(m) for st in Student.objects.all() for m in (st.major_1, st.major_2, st.major_3) if m)
    rows = [{"name": name, "family": family, "aliases": aliases, "subjects": subjects,
             "students": wanted.get(name, 0), "links": majors.neighbours(name)}
            for name, (family, aliases, subjects) in sorted(majors.MAJORS.items(), key=lambda x: (x[1][0], x[0]))]
    unplaced = sorted({n for n in Program.objects.filter(source="niche").values_list("name", flat=True)
                       if majors.node(n) is None})
    return render(request, "colleges/majors_graph.html", {"rows": rows, "unplaced": unplaced,
                                                          "same_family": majors.SAME_FAMILY})
