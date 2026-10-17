# Prompt for the Claude desktop app (Chrome extension): collect Niche program rankings

Paste everything below the line into ONE new chat in the Claude desktop app with the Chrome extension on.
The prompt makes Claude work through all your colleges in order, in groups of 10, and hand you the JSON after each
group, so nothing is lost if the chat stops. Save each JSON block as `data/programs/niche_batch1.json`,
`niche_batch2.json`, ... (or one file, if Claude can create files), then run:

    python manage.py import_programs --source niche --file data/programs

If the chat stops midway, start a new one and change the "Where to start" line at the end.

---

You will collect subject rankings from niche.com for a list of US colleges, using the Chrome browser.
You have no other context; everything you need is below.

## Goal
For each college, find the academic programs (majors) where Niche ranks it nationally, and record the
college's rank in each. I want each college's strongest programs, up to 20, strongest first.

## Where to look
1. Open https://www.niche.com/ and use its search to find the college's page (for example
   https://www.niche.com/colleges/harvard-university/). Check it is the right college using the city and
   state in my list (several colleges share similar names).
2. On the college page, open its rankings: the "Rankings" section or link on the page (often
   https://www.niche.com/colleges/<college-slug>/rankings/). It lists lines such as
   "#4 Best Colleges for Economics in America". Scroll to the end and open any "show more" or
   "see all rankings" control so that you see every ranking, not only the first few.
3. If a college's page shows no ranking list, look at its "Academics" section for ranked majors.
   If Niche really shows none, return an empty list for that college (do not invent any).

## What counts
- Keep only rankings of the form "Best Colleges for <Subject> in America": national rankings of a single
  academic subject or major. The subject is the program name.
- Skip: state, regional or city rankings; overall rankings ("Best Colleges in America", "Best Value",
  "Best Campus Food", "Best Student Life", dorms, party, athletics and similar); and rankings of
  categories rather than subjects (for example "Best Colleges for Athletes").
- Record the rank number exactly as shown. Sort each college's programs by rank, lowest number first,
  and keep the first 20.
- Copy the rank and subject only as they appear on the page. If you cannot read a number, leave that
  program out rather than guessing.
- Do not use any site other than niche.com.

## How to work
- Go one college at a time and work at a normal human pace; wait for each page to load fully.
- If Niche shows a CAPTCHA, a login wall, or "access denied", stop and tell me. Do not try to get
  around it.
- If you cannot find a college, say so in the output instead of guessing a different one.

## Output
For each group, reply with one JSON code block (one object per college in that group), in exactly this shape:

```json
[
  {
    "unitid": 166027,
    "programs": [
      {"name": "Economics", "rank": 4, "ranking": "#4 Best Colleges for Economics in America", "url": "https://www.niche.com/colleges/harvard-university/rankings/"},
      {"name": "Political Science", "rank": 7, "ranking": "#7 Best Colleges for Political Science in America", "url": "https://www.niche.com/colleges/harvard-university/rankings/"}
    ]
  }
]
```

Rules for the JSON:
- `unitid` is the number from my list, as a number.
- `name` is the subject only ("Economics", not "Best Colleges for Economics").
- `rank` is a whole number; `ranking` is the exact text of the ranking line.
- `url` is the page where you read it.
- If a college could not be found or has no subject rankings, include it with `"programs": []`.

## The colleges (unitid | name | city, state)

(Paste your list here, one college per line: `unitid | name | city, state`. To print it from your database:
`python manage.py shell -c "from colleges.models import College; [print(c.unitid, '|', c.name, '|', f'{c.city}, {c.state}') for c in College.objects.order_by('name')]"`)

## How much to do, and how
Work through the colleges in the order of the list above, in groups of 10 (1-10, 11-20, ... to the end).
After each group, output that group's JSON block as described under "Output", then continue with the next
group without waiting for me. Say "Group N done" in one short line after each block.

If you can run several helper agents in parallel and each can use the browser, you may split the groups
between them. Otherwise just do it yourself, one college at a time: they would share my one Chrome window
and get in each other's way.

Where to start: position 1
