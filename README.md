# College Match: a counseling platform for US college applications

> **Try the demo:** sign in as a fictional student at **https://ugs-match.pp.ua/login/**
>
> **Username:** `demo` &nbsp; **Password:** `ugs-demo-2026`
>
> Review the pre-filled application, press **Submit**, and see the student's matches: sort them, filter to the
> student's own list, and add or remove colleges right in the table. The demo shows 15 well-known colleges (the Ivy
> League, Duke, MIT, Stanford and a few more); a real installation has its organisation's whole list. The student is
> invented, the account resets every hour, and other visitors may be using it at the same time, so please don't type
> anything real into it.

A Django web app that helps a counseling team guide students through applying to US colleges. Counselors get a
shared, editable table of college profiles built from public data. Students fill in one profile and see how well they
match every college on the list, with the reasons, and keep their own college list up to date.

It was built for Ukraine Global Scholars (UGS), a non-profit that helps low-income Ukrainian students win full or
near-full financial aid at US colleges. It is shared so that other people and organisations can run their own: an NGO
with its own college list, a school counseling office, or an independent counselor.

## What it does

**For counselors (staff accounts)**
- **Colleges:** one editable table: test policy and SAT ranges, English test minimums, GPA and class-rank figures,
  international admit rate, aid to international students, top programs, an AI-written "vibe" of each college, and how
  many of your students went there in past years. Every value shows where it came from; edits are kept with their
  history and are never overwritten by re-imports.
- **Students:** every applicant's profile; names and emails stored encrypted.
- **Match:** each student's results with a point-by-point breakdown, and a map of how the match is built.
- **College weights:** each college's own points per metric, from what it says matters in admission.

**For students**
- Sign up with an email address in the organisation's domain, or one the team has loaded (one-time link), review
  and complete the profile (tests, grades by
  subject, school, majors, awards, activities, work, a short self-description, transcript upload), and choose 12-20
  colleges.
- Type in their grades for the past 2 years, or press "Autofill with a transcript": photos, scans, screenshots or
  PDFs, Ukrainian or English, printed or handwritten, are read by a fast model and, when it is unsure or the page is
  handwritten, by a precise one; what neither reads confidently goes to a counselor's review queue. The GPA is
  calculated (Ukrainian 12-point averages converted to 4.0).
- See their matches as soon as they submit: one sortable table with an "Only my list" filter, the reasons for each
  college, and add/remove buttons. Matches update live as other students change their lists.

## How the match works

1. **Hard rules** exclude a college the student cannot apply to: English test below the college's minimum, SAT below
   a required level, a single-sex college, or no relation at all between the student's majors and the college's
   strongest programs.
2. **Ten metrics** give points out of 100, grouped as academic (SAT, rigor, GPA, class rank), personal (character,
   talent, extracurriculars, volunteering, work) and fit (majors). Each college's points follow section C7 of its
   [Common Data Set](https://commondataset.org/), so a college that rates test scores "very important" weighs the SAT
   more than one that only "considers" them.
3. **Crowding** cuts the result by up to 20% when many more of your students list a college than it usually admits
   from your organisation. It uses the current lists, so it updates live.

The engine is plain Python (`sources/matching.py`); every rule, point and threshold is a constant at the top of the
file. An LLM (Google Gemini) only rates the student's own texts (school type, talent, activities, work, and the
self-description against each college's vibe), and those ratings are saved before the engine runs. Full explanation,
metric by metric: [docs/algorithm.md](docs/algorithm.md). It is a **match %**, not a chance of admission.

## Run it on your computer

Python 3.12+ (developed on 3.14).

```bash
git clone <this repository> college-match && cd college-match
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# In .env, set at least:
#   DJANGO_SECRET_KEY  python -c "import secrets; print(secrets.token_urlsafe(50))"
#   DJANGO_DEBUG=1
#   STUDENT_DATA_KEY   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
#                      (keep a copy: without it, stored names cannot be read)

python manage.py migrate
python manage.py createsuperuser          # your staff login
```

Then give it a college list. The smallest working setup needs only a CSV and an internet connection:

```bash
cat > data/cds_decisions.csv <<'CSV'
College,Has CDS?,Latest CDS year (only for colleges that stopped publishing)
Amherst College,Yes,
Bowdoin College,Yes,
Rice University,Yes,
CSV
python manage.py import_colleges                 # matches each name to its IPEDS ID
python manage.py import_ipeds                    # admissions, SAT ranges, cost and aid (public API, no key)
python manage.py import_programs --source ipeds  # each college's largest majors
python manage.py build_profiles                  # fills the dashboard
python manage.py create_sample_students          # 8 fictional students; one is the demo login
python manage.py runserver                       # http://127.0.0.1:8000
```

Log in with your staff account to see the dashboard, and as `demo` / `ugs-demo-2026` (in a private window) to see the
student side. Sign-up emails are printed in the terminal until you set `EMAIL_HOST`.

**More data, when you have it** (every import is safe to re-run and keeps values edited by hand):

| Data | Where it goes | Command |
|---|---|---|
| Common Data Set PDFs (international admits, C7 factors, GPA bands, aid) | `data/Common Data Sets/<College name> CDS <year>.pdf` | `import_cds`, then `build_profiles` |
| Program rankings from Niche (better than "largest majors") | a JSON file, collected with [docs/niche_prompt.md](docs/niche_prompt.md) | `import_programs --source niche --file <file>` |
| College vibe and other AI-written columns | needs `GEMINI_API_KEY` | `generate_college_answers` |
| Your organisation's past results (students per college per year) | an .xlsx, format in [docs/algorithm.md](docs/algorithm.md) | `import_ugs_history --file <file>` |
| Your research on full rides and aid to international students | `data/research/full_rides.json`, format in `sources/full_rides.py` | `build_profiles` |
| AI ratings of students' texts | needs `GEMINI_API_KEY` | `run_matching --sample` (sample students) |

## Adapting it to your organisation

| What | Where |
|---|---|
| Who can create an account (e.g. anyone `@yourorg.org`, and only them) | `STUDENT_EMAIL_DOMAINS` in `.env` |
| Rules, points out of 100, thresholds, crowding lines | constants at the top of `sources/matching.py` |
| The demo account's 15 colleges | `DEMO_COLLEGES` in `sources/demo.py` |
| Default English test minimum where a college publishes none (UGS uses DET 135) | `UGS_DET_RECOMMENDATION` in `colleges/management/commands/build_profiles.py` |
| Majors and how closely they relate | `sources/majors.py` (the majors graph; also viewable in the app) |
| GPA rules per curriculum (Ukrainian 12-point, IB, A-levels, US) | `sources/transcript.py` |
| What the AI is asked | `sources/student_ai.py` (students) and `sources/college_ai.py` (colleges) |
| The name "UGS" in pages and emails | the templates in `colleges/templates/colleges/` |
| College names that do not match IPEDS, or your past-results sheet | matched automatically; fixes go in `data/college_name_overrides.json` and `data/ugs_history_names.json` (formats in `sources/college_list.py` and `sources/ugs_history.py`) |

UGS also kept notes about colleges in a CRM (HubSpot) and showed them on the dashboard. That integration is specific to
UGS and is not included here; the two dashboard columns it fed stay hidden when there is no CRM data, and everything
else works without it.

## Privacy

The app was built for minors' data (grades, family income, displacement status), so:

- **No data lives in the repository**, including the college list and any research about it. The database, source
  files, research and student uploads go in `data/`, and secrets in
  `.env`; both are git-ignored, as are spreadsheets, databases, PDFs and keys anywhere in the tree.
- Student names and emails are stored encrypted (`STUDENT_DATA_KEY`); emails are looked up by a one-way fingerprint.
- Nothing sent to an AI model includes names or emails (`for_ai` in `sources/students.py`). By default only the
  fictional sample students are sent. Set `ALLOW_STUDENT_DATA_TO_GEMINI=1` only on a paid plan whose terms do not use
  your inputs for training.
- A student sees only their own data; staff pages are closed to students.
- Prompt injection: students' texts and transcripts are data, never instructions. Prompts wrap them in tags they cannot
  close, the transcript reader must answer in a strict schema and flags text addressed to an AI, the code checks every
  grade against its scale, flagged answers are never accepted automatically, and counselors see the flags.
- The public demo account cannot upload files, never calls the AI, and does not affect real students' matches.

## Deploy

[docs/deploy.md](docs/deploy.md) walks through a small Linux server (written for Oracle Cloud's free tier, but any
Ubuntu VPS works): gunicorn behind Caddy with automatic HTTPS, a systemd service, email for sign-up links, and daily
database backups. Files for it are in `deploy/`.

## Tests

```bash
python manage.py test colleges
```

The tests cover sign-up and privacy, the profile form, the matching rules, crowding, the college list editor, the demo
account's limits and the past-results import. They use a temporary database and generate their own passwords.

## Commands

| Command | What it does |
|---|---|
| `import_colleges` | Loads your college list and matches each college to its IPEDS ID |
| `import_ipeds` | Admissions, test scores, cost and aid from the IPEDS API (Urban Institute Education Data Portal) |
| `import_cds` | Registers Common Data Set files, keeps their text and extracts values |
| `import_programs` | Each college's strongest programs (Niche rankings, or IPEDS largest majors) |
| `build_profiles` | Fills the dashboard's college profiles from all sources |
| `generate_college_answers` | College vibe and other AI-written columns |
| `import_ugs_history` | Your students per college and year; sets each college's capacity for crowding |
| `create_sample_students` | Creates, resets (`--demo-only` for the demo) or deletes the fictional students |
| `download_transcripts` | Downloads transcript files linked in a spreadsheet (names are never read) |
| `run_matching` | Asks the AI for missing ratings and refreshes match results |

## Layout

```
config/       Django settings (everything secret comes from .env)
colleges/     models, views (dashboard, students, match, student portal), templates, commands, tests
sources/      plain Python: imports and parsing, the matching engine, AI prompts, encryption
deploy/       server files: systemd service, Caddyfile, backup script
docs/         algorithm, deployment guide, Niche collection prompt
data/         yours, not in git: database, source files, student uploads
```

## License

MIT: see [LICENSE](LICENSE).
