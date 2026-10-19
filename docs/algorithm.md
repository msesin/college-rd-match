# Matching algorithm (engine v3, crowding after the match)

Status: built 2026-10-14 (`sources/matching.py`, `sources/transcript.py`, `sources/majors.py`, `sources/student_ai.py`).
The rules, points and thresholds were set by the UGS team for its students; numbers marked *proposal* filled gaps
where the rules gave none. All of them are constants at the top of the files above, so another organisation can change
them without touching the logic.

## What the engine produces: student match %

For each student and each of the 71 colleges, a **match %** out of 100: how well the student's tests, grades,
school, interests, activities and character fit what the college looks for. **It is not a chance of admission.** A 100%
match can still be turned down, especially when the student asks for full financial aid.

**When it runs.** As soon as a student submits the form, the engine runs for them and they see their results on the
"My matches" tab: their 12 best matches, the other colleges and the excluded ones, each with a plain "Why" (where the
college gave full points and where points were lost), how many UGS students have the college on their list, the
international admit rate and how many UGS students went there per year on average (both for context). It is one
table, sortable by any column, with an "Only my list" filter; excluded colleges are listed apart. Students add or remove
colleges right in the table ("My list" column; added at the end; 1-20 colleges). On submit, Gemini rates the student's
texts first (about 10 seconds; the page says so), so the first results already use the ratings. If Gemini is busy or
fails, the results come anyway and a background retry updates them a minute later. That is the **preliminary match**. The **crowding cut** (below) is applied on top
whenever results are shown, from the current lists, so the final match changes live: when any student adds or removes
a college, or a new student submits, everyone's numbers update (the "My matches" page checks every 20 seconds and
reloads itself). Students see only the final %. After submitting, students keep their college list up to date (up to
20 colleges). A counselor's edit on the Students tab updates that student's match. Counselors see each student's
preliminary and final match on the Match tab; there is nothing to run or release.
`python manage.py run_matching [--sample] [--explain]` asks Gemini for missing ratings and refreshes the results.

On the form, students choose 12 to 20 colleges (UGS college counseling recommends 12, and adding more once those
applications are done). This is their starting list, for them and their counselor. It is not part of the match, only
of crowding once submitted. The "My matches" tab appears only after the student submits.

## Gemini rates the student's own texts; everything else is code

| What | Input | Output, saved on the student |
|---|---|---|
| School type | The school's name and city, and the IB/AP/A-levels answer | English curriculum (incl. Ukrainian schools teaching IB, AP or A-levels) / top Ukrainian school (well-known lyceum, gymnasium or specialised school) / regular Ukrainian school |
| Talent/ability | Awards, olympiads and research, and the activities | very strong (international level, consistent) / strong (national or regional) / moderate (local, online, or nothing notable) |
| Extracurricular activities | The activities | high (sustained, leadership or impact) / medium (regular, some responsibility) / low |
| Volunteer work | The activities | high / medium / low |
| Work experience | The work experience | high (substantial and sustained) / medium / low |
| Self-summary vs college vibe | The self-summary (300 words max) and every college vibe | high / moderate / none per college |

The first five come from one request per student; each has a short reason, shown on the Students and Match tabs. An
empty answer is rated "low" (talent "moderate") in code, without asking. For the vibe, "high" is kept for the closest
matches (at most about a quarter of the colleges), "moderate" is the default, "none" means the traits clash. Ratings
are redone only when the text, a college vibe or the prompt changes. A level changed by hand on the Students tab is
kept. Privacy: text goes through `for_ai()` (no names or emails, contacts scrubbed); only the "sample" cohort is sent
unless `.env` has `ALLOW_STUDENT_DATA_TO_GEMINI=1`. Until a rating exists (for example, real students while that is
off), the metric gets half points; a counselor can set the level by hand.

## Step 1: hard rules (college requirements)

| Rule | Excluded when |
|---|---|
| Pronouns | A student who uses he/him and a women's college. |
| DET | Below the college's minimum **or** recommended score, whichever is higher; for colleges that publish neither, below the UGS recommendation of 135. All are treated as the bare minimum. Students in IB, AP or A-levels are exempt. |
| SAT | Below a published SAT minimum; or the college **requires** the SAT and the student has none or is in its bottom 30%. |
| Majors | None of the student's majors is related to any of the college's top 20 programs (majors graph: 0). Any relation above 0 gives the Majors points below. Not applied when the college has no program list or none of the student's majors is in the graph yet (half points instead). |

## Step 2: ten metrics, 100 points

Three categories, shown in colour on the College weights and Match tabs: **academic** (blue), **personal** (purple)
and **fit** (green). Default points (colleges without a CDS C7): the team's points with crowding's former 5 spread over
the nine C7 metrics.

| Metric | Category | Default points | CDS C7 factor | Full | Half | None |
|---|---|---|---|---|---|---|
| SAT | Academic | 18.6 | Standardized test scores | top 30% | middle; bottom 30% or no SAT at a test-optional college (apply without it); test-blind | (required and bottom 30% or none = excluded). Strongly preferred and bottom 30% or none: a quarter |
| Rigor of school record | Academic | 13.3 | Rigor of secondary school record | English curriculum and strong coursework | | regular Ukrainian school and weak coursework |
| GPA | Academic | 10.6 | Academic GPA | at or above the college's GPA bar | one level below; no grades | two levels below |
| Class rank | Academic | 5.3 | Class rank | at or above the college's class-rank bar | one level below; no rank | two levels below |
| Character | Personal | 13.3 | Character/personal qualities | vibe high | moderate; not judged yet | none |
| Talent/ability | Personal | 10.6 | Talent/ability | very strong | strong; not rated yet | moderate |
| Extracurricular activities | Personal | 10.6 | Extracurricular activities | high | medium; not rated yet | low |
| Volunteer work | Personal | 2.7 | Volunteer work | high | medium; not rated yet | low |
| Work experience | Personal | 2.7 | Work experience | high | medium; not rated yet | low |
| Majors | Fit | 12.5 | none (same everywhere) | graded by the majors graph (below) | | (0 = excluded) |

**Preliminary match %** = the points earned. The worst level of a metric gives **0** points, so a match can go from 0 to 100. The
only floors are for missing or unrated data (half) and for the SAT at test-optional and test-blind colleges (half, as
the student can apply without it). A student at the worst level of everything gets only those SAT points: 8.75 of 100
at a test-optional college.

**Rigor** is the average of two halves. School type: English curriculum 1, top Ukrainian 0.5, regular Ukrainian 0 (not
rated yet: 0.5, or 1 for an IB, AP or A-levels student). Relevant coursework: strong 1, okay 0.5, weak 0 (below).

**Each college gets its own points.** Section C7 of the college's Common Data Set rates each factor as very important,
important, considered or not considered. The rating scales the default points of the metric that measures that factor
(x1.5, x1, x0.5, x0; a factor the college left blank counts as important), and the nine C7 metrics are rescaled to
share 87.5 points. Majors (12.5) are the same at every college, so every college adds up to 100.
Example: Pitzer is test-blind, so SAT is worth 0 there. Brown and WashU have no C7 in the CDS we hold and use the
defaults. The "College weights" tab lists every college (*proposal*: the multipliers).

## Step 3: crowding, after the match

Not one of the points: it is applied to the preliminary match, in code, every time results are shown.

- **Applicants**: how many submitted UGS students have the college on their list (the student included, once they
  add it).
- **UGS capacity**: how many UGS students the college usually admits a year, the average of the last 3 years in UGS's
  admissions results (2023-2025), rounded, at least 1 (`import_ugs_history`; editable on the dashboard's UGS
  applicants column).
- **The cut**: none up to 2x capacity; above that it grows evenly, reaching 20% of the match at 4x capacity and
  stays at 20% beyond (*proposal*: the 2x and 4x).

**Final match %** = preliminary match x (1 - cut). Example, Harvard (capacity 4): up to 8 applicants no cut; 10
applicants -5%; 12 applicants -10%; 14 applicants -15%; 16 or more -20%, so a preliminary 80% becomes 64%.

### UGS results by year

`import_ugs_history` reads the organisation's past results: an .xlsx file whose sheet "General" has one row per
college and one column per year (header `College | 2018 | 2019 | ...`), each cell the number of students who went
there (no names). It sets each college's capacity (above), the "UGS students / year" column (average over all years) on
the Colleges dashboard, the "UGS track record" column in the students' matches (UGS students there since the first year,
and the latest year one went), and the UGS results page (linked from Colleges; colleges that are
not on the list are kept and shown too). Sheet names are matched to the colleges on the list automatically; names that differ go in
`data/ugs_history_names.json` (see `sources/ugs_history.py`).

### Reading transcripts (OCR)

Students can type their grades or press "Click to autofill" to read them from a transcript (`sources/ocr.py`). Each file (PNG, JPEG, PDF,
HEIC; photo, scan or screenshot; Ukrainian or English; printed or handwritten) is read in two tiers, one request each:

1. **Fast model** (`GEMINI_MODEL`, gemini-3.5-flash-lite), JSON mode, temperature 0: subjects and grades per school
   year, `is_handwritten`, `confidence_score` (0-1), the class rank if printed, and the trend between years (transcript
   performance, in the same request).
2. **Routing:** printed and confidence >= 0.95 -> accepted. Handwritten or confidence < 0.95 -> the same file goes to
   the **precise model** (`GEMINI_MODEL_PRO`, gemini-3.1-pro-preview) with the same instructions and schema.
3. Precise model >= 0.95 -> accepted. Below, or unavailable -> stored with `needs_verification` (the counselors'
   review queue: Admin, Student files, filter "needs verification"; "Transcript: check by hand" on the Students tab),
   and the student is asked for another format or to type the grades in.

The model's own confidence is not enough (in tests it said 0.95 for a photo it had read one row off), so the code
checks too, and any problem caps the confidence below 0.95: every grade must fit its scale; each year's grades read
straight down the column must match the subject rows; in a printed transcript, a year whose only missing grade is in
the first or last row is checked again (a row read one off; blanks elsewhere are normal, for subjects not taught that
year); text addressed to an AI is flagged. Gemini's raw answers are kept with each reading; a file that failed under
older checks is read again the next time. Empty or struck-through cells are null. The two most recent years fill the form (one
grading scale only); the GPA is the average out of 12 converted proportionally to 4.0 (average / 12 x 4: 10.97 ->
3.66), or the 4.0 average of US letter grades. Class rank: only a rank printed on the transcript is read (Gemini does
not guess it from grades); it becomes a level, top 1%, 5%, 10%, 25% or 50%, rounding to the next level up (3rd of 30
= 10% -> top 10%; 4th of 30 = 13% -> top 25%), which the student can change in a dropdown with the same levels. Nothing is saved until the student
checks the grades and saves. A file already read is never sent again; at most 10 autofill runs per student per day.
On submit, transcript files uploaded without autofill are read too, at the same time as the ratings: grade answers
the student left empty are filled from them (typed answers are never replaced), before the first match.

### Transcript, from grades by subject

Grades are stored by subject on the school's own scale (Students tab, GPA column; the portal asks for them too):
Ukrainian 1-12, IB 1-7 plus "Core (TOK/EE)" bonus points, A-levels A*-E, US letter grades with AP courses marked "AP".

**GPA level** (the team's rules):

| Curriculum | Will get in | Maybe | Red flags |
|---|---|---|---|
| Ukrainian | every grade 10+ | a few 8-9s (at most a third), nothing below 8 | consistent 8-9s or anything lower |
| IB | 42+/45 | 36-41 | below 36 |
| A-levels | more A* than A, nothing below A | at most one B | two or more B, or lower |
| AP / US | GPA 3.85+ with A/A- in every AP course (close to 5.0 weighted) | about 3.5 with advanced courses | Bs and Cs in two or more AP courses, or GPA below 3.3 |

Compared with the college's **GPA bar** (high / medium / low) from the dashboard's Average HS GPA (3.9+ high, 3.75+
medium) and % with GPA 3.75+ (80%+ high, 60%+ medium); without figures, the overall admit rate (10% or less high,
25% or less medium) (*proposal*).

**Class rank**: top 10% / top 10-25% / lower, against the college's share of first-years in the top 10% of their class
(85%+ high bar, 60%+ medium) (*proposal*).

**Relevant coursework**: grades in the subjects that matter for the student's first major (the graph lists them, e.g.
Biology: biology and chemistry; Engineering: maths and physics). Strong / okay / weak: Ukrainian average 10.5+ with
nothing below 10 / average 9+ / lower; IB all 6-7 / average 5+ / lower; A-levels all A or A* / at most one B / lower;
US average 3.7+ with nothing below B+ / 3.0+ / lower (*proposal*).

### SAT lines

Colleges publish the 25th, 50th and 75th percentiles of enrolled first-years (CDS C9; IPEDS gives the same per section).
The engine needs the 30th (below it: bottom 30%) and the 70th (from it: top 30%). They are estimated on a normal curve
between the published figures, rounded to 10. Shown in the dashboard's SAT column; can be edited by hand.

### Majors graph (in code)

`sources/majors.py`; readable on the Match tab, "Majors graph". 44 majors in 9 families with hand-set links: 1.0 the
same major, 0.8 very close, 0.6 closely related, 0.4 related, 0.2 same family. The student's majors count 50% / 30% /
20%; each takes the best of the college's top 20 programs, where #1 counts fully and #20 counts 0.525. Majors carry the
same 12.5 points at every college, whatever its size. A match of 0 (no relation at all) excludes the college.

## Step 4: the list

All colleges the student is not excluded from, best final match first (ties: preliminary match). The first 12 are the
student's best matches. Selectivity is not part of the match: the international admit rate is shown next to it.

