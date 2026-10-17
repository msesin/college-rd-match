"""Rules for reading priority CDS items from flat (non-form) PDFs.

Input: pages of words with positions (from pdfplumber). Labels are matched on
"squashed" text (lowercase, letters and digits only) because some PDFs glue
words together ("Totalfirst-time") and others split them.

Tables are read by position: each number is assigned to the column header
closest to it horizontally, so blank cells don't shift values into the wrong
column. Every rule result is sanity-checked; failures are returned in `review`
so the dashboard can flag them for a human.

Returns (values, review, log): values {official CDS tag: raw string},
review {tag: reason}, log [str].
"""

import re
from dataclasses import dataclass, field

from sources.parsing import to_number

NUM_RX = re.compile(r"^\(?\$?-?(\d[\d,]*\.?\d*|\.\d+)%?\)?:?$")
CHECK_GLYPHS = set("✔✓☒■●√⌧✗✘ü")


def squash(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def is_num(token):
    return bool(NUM_RX.match(token))


BOX_GLYPHS = set("☐□֜")


def is_mark(word):
    """A tick or cross: X, a check glyph, or any glyph in a dingbat font (ZapfDingbats '4' is ✔)."""
    t = word["text"].strip() if isinstance(word, dict) else word.strip()
    if not t or all(ch in BOX_GLYPHS for ch in t):
        return False
    if t in ("X", "x") or any(ch in CHECK_GLYPHS for ch in t):
        return True
    font = (word.get("fontname") or "").lower() if isinstance(word, dict) else ""
    return any(f in font for f in ("dingbat", "wingding")) and len(t) <= 2


def _merge_split_numbers(words):
    """Rejoin numbers that a PDF split into pieces: "3 8,023" -> "38,023", "1 ,665" -> "1,665"."""
    out = []
    for w in words:
        prev = out[-1] if out else None
        if (
            prev is not None
            and re.fullmatch(r"\d{1,3}", prev["text"])
            and w["x0"] - prev["x1"] < 3
            and re.fullmatch(r",?\d{1,3}(,\d{3})*%?", w["text"])
            and re.fullmatch(r"\d{1,3}(,\d{3})+%?", prev["text"] + w["text"])
        ):
            out[-1] = {**prev, "text": prev["text"] + w["text"], "x1": w["x1"]}
            continue
        out.append(w)
    return out


@dataclass
class Line:
    page: int
    top: float
    words: list
    text: str = ""
    sq: str = ""

    def __post_init__(self):
        self.words.sort(key=lambda w: w["x0"])
        self.words = _merge_split_numbers(self.words)
        self.text = " ".join(w["text"] for w in self.words)
        self.sq = squash(self.text)

    def numbers_after_label(self):
        """Numeric words to the right of the last word that contains letters."""
        last_alpha = -1
        for i, w in enumerate(self.words):
            if re.search(r"[A-Za-z]", w["text"]):
                last_alpha = i
        return [w for w in self.words[last_alpha + 1 :] if is_num(w["text"])]

    def numbers_after(self, pattern):
        """Numeric words after the part of the line matched by `pattern` (on squashed text)."""
        m = re.search(pattern, self.sq)
        if not m:
            return self.numbers_after_label()
        covered, out = 0, []
        for w in self.words:
            if covered >= m.end() and is_num(w["text"]):
                out.append(w)
            covered += len(squash(w["text"]))
        return out

    def numeric_only(self):
        toks = [w["text"] for w in self.words]
        return bool(toks) and all(is_num(t) or t.upper() in ("NA", "N/A") for t in toks)


def build_lines(pages):
    lines = []
    for pi, page in enumerate(pages):
        words = sorted(page["words"], key=lambda w: w["top"])
        current, ref = [], None
        for w in words:
            if ref is not None and abs(w["top"] - ref) > 3:
                lines.append(Line(pi, ref, current))
                current = []
            if not current:
                ref = w["top"]
            current.append(w)
        if current:
            lines.append(Line(pi, ref, current))
    return lines


# Standard item titles, used when a PDF has no item codes (e.g. Occidental).
ANCHOR_TITLES = {
    "c1": r"firsttimefirstyear(freshman)?studentsprovidethenumber",
    "c2": r"waitlistedstudents",
    "c3": r"highschoolcompletionrequirement",
    "c7": r"relativeimportanceofeachofthefollowing",
    "c8": r"^satandactpolicies",
    "c9": r"^percentandnumberoffirsttimefirstyear",
    "c10": r"whohadhighschoolclassrankwithin",
    "c11": r"whohadhighschoolgradepointaverages",
    "c12": r"^averagehighschoolgpaofall",
    "c13": r"^(doesyourinstitutionhavean)?applicationfee",
    "c21": r"offeranearlydecisionplan",
    "c22": r"^earlyaction",
    "h6": r"policyregardinginstitutionalscholarshipandgrantaid",
    "h7": r"checkoffallfinancialaidformsnonresident",
    "h8": r"financialaidformsdomestic",
    "b22": r"forthecohortofallfulltimebachelors",
}


@dataclass
class Doc:
    pages: list
    lines: list
    values: dict = field(default_factory=dict)
    review: dict = field(default_factory=dict)
    log: list = field(default_factory=list)

    def find(self, pattern, start=0, end=None):
        rx = re.compile(pattern)
        end = len(self.lines) if end is None else end
        for i in range(start, end):
            if rx.search(self.lines[i].sq):
                return i
        return None

    def anchor(self, item, start=0):
        """Index of the line where CDS item `item` (e.g. 'c7') starts.

        The code must be followed by a space or punctuation, so mapping notes
        like "(c7_state_residency...)" on cover pages don't count.
        """
        rx = re.compile(rf"^{item}(?:[\s.:\-–]|$)", re.IGNORECASE)
        hits = [i for i in range(start, len(self.lines)) if rx.match(self.lines[i].text)]
        title = ANCHOR_TITLES.get(item)
        if title:
            # Instructions sometimes mention an item ("report in H6 below"); prefer
            # the occurrence that has the item's title nearby.
            for i in hits:
                near = "".join(l.sq for l in self.lines[max(i - 2, 0) : i + 4])
                if re.search(title.lstrip("^"), near):
                    return i
        if hits:
            return hits[0]
        # Some PDFs drop the item codes; fall back to the item's standard title.
        if title:
            return self.find(title, start)
        return None

    def set(self, tag, token, note=None):
        if tag in self.values:
            return
        self.values[tag] = token.strip().rstrip(":")
        if note:
            self.review[tag] = note


def _span(doc, start_item, end_items):
    start = doc.anchor(start_item)
    if start is None:
        return None, None
    ends = [doc.anchor(e, start + 1) for e in end_items]
    ends = [e for e in ends if e is not None]
    return start, (min(ends) if ends else min(start + 200, len(doc.lines)))


def _row_value(doc, tag, pattern, start, end, last=False, window=1):
    """Single value on a label row: first number after the label, else on the next numeric-only line.

    The first number is used because some templates print helper notes to the
    right ("Top half + bottom half = 100%").
    """
    i = doc.find(pattern, start, end)
    if i is None:
        return None
    nums = doc.lines[i].numbers_after(pattern)
    if nums:
        doc.set(tag, (nums[-1] if last else nums[0])["text"])
        return i
    for j in range(i + 1, min(i + 1 + window, len(doc.lines))):
        if doc.lines[j].numeric_only():
            toks = [w["text"] for w in doc.lines[j].words if is_num(w["text"])]
            if toks:
                doc.set(tag, toks[-1] if last else toks[0])
                return i
    return i


def _value_near(doc, tag, pattern, start, end, window=3, accept=is_num):
    """First acceptable number on the label line (after the label) or the next `window` lines."""
    i = doc.find(pattern, start, end)
    if i is None:
        return None
    candidates = [w["text"] for w in doc.lines[i].numbers_after_label()]
    for j in range(i + 1, min(i + 1 + window, end or len(doc.lines))):
        candidates += [w["text"] for w in doc.lines[j].words if is_num(w["text"])]
    for tok in candidates:
        if accept(tok):
            doc.set(tag, tok)
            return i
    return i


def _center(words):
    return (min(w["x0"] for w in words) + max(w["x1"] for w in words)) / 2


# ---------------------------------------------------------------- C1

C1_GENDER_ROWS = [
    ("AP_RECD_1ST_MEN_N", r"firstyear(degreeseeking|freshman)?(men|males)whoapplied"),
    ("AP_RECD_1ST_WMN_N", r"firstyear(degreeseeking|freshman)?(women|females)whoapplied"),
    ("AP_RECD_1ST_OTH_N", r"firstyear(degreeseeking|freshman)?anothergenderwhoapplied"),
    ("AP_RECD_1ST_UNK_N", r"firstyear(degreeseeking|freshman)?(studentsof)?unknown(gender|sex)whoapplied"),
    ("AP_ADMT_1ST_MEN_N", r"firstyear(degreeseeking|freshman)?(men|males)whowereadmitted"),
    ("AP_ADMT_1ST_WMN_N", r"firstyear(degreeseeking|freshman)?(women|females)whowereadmitted"),
    ("AP_ADMT_1ST_OTH_N", r"firstyear(degreeseeking|freshman)?anothergenderwhowereadmitted"),
    ("AP_ADMT_1ST_UNK_N", r"firstyear(degreeseeking|freshman)?(studentsof)?unknown(gender|sex)whowereadmitted"),
    ("EN_TOT_1ST_FT_MEN_N", r"fulltimefirsttimefirstyear(degreeseeking|freshman)?(men|males)whoenrolled"),
    ("EN_TOT_1ST_PT_MEN_N", r"parttimefirsttimefirstyear(degreeseeking|freshman)?(men|males)whoenrolled"),
    ("EN_TOT_1ST_FT_WMN_N", r"fulltimefirsttimefirstyear(degreeseeking|freshman)?(women|females)whoenrolled"),
    ("EN_TOT_1ST_PT_WMN_N", r"parttimefirsttimefirstyear(degreeseeking|freshman)?(women|females)whoenrolled"),
]
C1_RESIDENCY_ROWS = [
    ("AP_RECD", r"totalfirsttimefirstyear(degreeseeking|freshman)?(students)?whoapplied"),
    ("AP_ADMT", r"totalfirsttimefirstyear(degreeseeking|freshman)?(students)?whowereadmitted"),
    ("EN_TOT", r"totalfirsttimefirstyear(degreeseeking|freshman)?(students)?(who)?enrolled"),
]
C1_RESIDENCY_COLUMNS = [
    ("STATE", r"^instate"),
    ("NRES", r"^outof"),
    ("INTL", r"^international"),
    ("UNK", r"^unknown"),
    ("TOTAL", r"^total$"),
]


def _c1(doc):
    start, end = _span(doc, "c1", ["c2", "c3"])
    if start is None:
        doc.log.append("C1 not found")
        return
    for tag, pattern in C1_GENDER_ROWS:
        _row_value(doc, tag, pattern, start, end)

    # Residency table, read by column position.
    # The residency table follows its own header; search below it so the gender
    # table's similar "Total ... who applied" rows aren't picked up instead.
    header = doc.find(r"(instate|outofstate).*international|international.*(instate|outofstate)", start, end)
    row_start = header if header is not None else start
    rows = [(prefix, doc.find(p, row_start, end)) for prefix, p in C1_RESIDENCY_ROWS]
    rows = [(p, i) for p, i in rows if i is not None]
    if not rows:
        doc.log.append("C1 residency table not found")
    else:
        first = min(i for _, i in rows)
        page = doc.lines[first].page
        header_words = []
        for j in range(max(start, first - 4), first):
            if doc.lines[j].page == page:
                header_words += doc.lines[j].words
        columns = {}
        for name, rx in C1_RESIDENCY_COLUMNS:
            hits = [w for w in header_words if re.search(rx, squash(w["text"]))]
            if hits:
                columns[name] = _center([hits[-1]])
        if len(columns) < 3:
            doc.log.append(f"C1 residency header not recognised (found {sorted(columns)})")
        else:
            for prefix, i in rows:
                line = doc.lines[i]
                taken = {}
                for w in line.numbers_after_label():
                    col = min(columns, key=lambda c: abs(columns[c] - _center([w])))
                    if col in taken:
                        doc.review[f"{prefix}_?"] = "two numbers fell in one residency column"
                    taken[col] = w["text"]
                for col, tok in taken.items():
                    tag = f"{prefix}_1ST_N" if col == "TOTAL" else f"{prefix}_{col}_1ST_N"
                    doc.set(tag, tok)

    for prefix in ("AP_RECD", "AP_ADMT"):
        total = to_number(doc.values.get(f"{prefix}_1ST_N"))
        parts = [to_number(doc.values.get(f"{prefix}_{c}_1ST_N")) for c in ("STATE", "NRES", "INTL", "UNK")]
        if total and any(parts):
            s = sum(p for p in parts if p)
            if abs(total - s) / total > 0.02:
                for c in ("STATE", "NRES", "INTL", "UNK"):
                    if f"{prefix}_{c}_1ST_N" in doc.values:
                        doc.review[f"{prefix}_{c}_1ST_N"] = f"residency columns add up to {s:,.0f}, not the total {total:,.0f}"


# ---------------------------------------------------------------- C2

def _c2(doc):
    start, end = _span(doc, "c2", ["c3", "c4", "c5"])
    if start is None:
        return
    _row_value(doc, "AP_RECD_WAIT_N", r"offeredaplaceon(the)?waitinglist", start, end)
    _row_value(doc, "AP_ACPT_WAIT_N", r"acceptingaplaceon(the)?waitinglist", start, end)
    _row_value(doc, "AP_ADMT_WAIT_N", r"waitlistedstudentsadmitted", start, end)


# ---------------------------------------------------------------- C7

C7_ROWS = [
    ("Q111_1", r"^rigor"),
    ("Q111_2", r"^classrank"),
    ("Q111_3", r"^academicgpa"),
    ("Q111_4", r"^standardized"),
    ("Q111_5", r"^(application)?essay"),
    ("Q111_6", r"^recommendation"),
    ("Q112_1", r"^interview"),
    ("Q112_2", r"^extracurricular"),
    ("Q112_3", r"^talent"),
    ("Q112_4", r"^character"),
    ("Q112_5", r"^firstgeneration"),
    ("Q112_6", r"^alumn"),
    ("Q112_7", r"^geographic"),
    ("Q112_8", r"^stateresidency"),
    ("Q112_9", r"^religious"),
    ("Q112_11", r"^volunteer"),
    ("Q112_12", r"^workexperience"),
    ("Q112_13", r"^levelof"),
]
C7_HEADER_TOKENS = {"very", "important", "considered", "not", "veryimportant", "notconsidered"}


def _header_token(text):
    """Normalise clipped header words ("Importa", "Consid") to full tokens."""
    t = squash(text)
    for full in ("veryimportant", "notconsidered", "important", "considered"):
        if len(t) >= 5 and full.startswith(t):
            return full
    return t if t in C7_HEADER_TOKENS else None
C7_COLUMN_ORDER = ["VI", "I", "C", "NC"]


def _is_header_line(line):
    """Mostly header words, so text like "(not including programs...)" is ignored."""
    other = {"academic", "nonacademic", "factors", "c7"}
    hits = sum(bool(_header_token(w["text"])) or squash(w["text"]) in other for w in line.words)
    return hits >= max(1, len(line.words) / 2)


def _c7_header_columns(doc, seed):
    """Column centres from the header band around line `seed`.

    Header cells wrap differently in every PDF ("Very" above "Important",
    "Not" above "Considered", or clipped to one word per cell), so header words
    are clustered by horizontal overlap and the 4 clusters are taken in order
    left to right: Very Important, Important, Considered, Not Considered.
    """
    page = doc.lines[seed].page
    top = doc.lines[seed].top
    words = [
        w for l in doc.lines
        if l.page == page and abs(l.top - top) <= 15 and _is_header_line(l)
        for w in l.words if _header_token(w["text"])
    ]
    words.sort(key=lambda w: (w["x0"], w["top"]))
    clusters = []
    for w in words:
        for c in clusters:
            overlaps = w["x0"] < c["x1"] and w["x1"] > c["x0"]
            # "Very Important" / "Not Considered" side by side on one line form one header.
            adjacent = (
                (c["text"], _header_token(w["text"])) in (("very", "important"), ("not", "considered"))
                and abs(w["top"] - c["top"]) < 2 and 0 <= w["x0"] - c["x1"] < 8
            )
            if overlaps or adjacent:
                c["x0"], c["x1"] = min(c["x0"], w["x0"]), max(c["x1"], w["x1"])
                c["text"] += _header_token(w["text"])
                break
        else:
            clusters.append({"x0": w["x0"], "x1": w["x1"], "top": w["top"], "text": _header_token(w["text"])})
    if len(clusters) != 4 or "very" not in clusters[0]["text"] or "not" not in clusters[3]["text"]:
        return None
    return {code: (c["x0"] + c["x1"]) / 2 for code, c in zip(C7_COLUMN_ORDER, clusters)}


def _c7(doc):
    start, end = _span(doc, "c7", ["c8"])
    if start is None:
        doc.log.append("C7 not found")
        return
    seeds = [
        i for i in range(start, end)
        if _is_header_line(doc.lines[i])
        and sum(bool(_header_token(w["text"])) for w in doc.lines[i].words) >= 2
    ]
    headers = [(i, cols) for i in seeds if (cols := _c7_header_columns(doc, i))]
    # Rows may be prefixed with the item code or group name ("C7 Rigor...", "Academic Factors Rigor...").
    prefix = r"^(c7(\d\d)?)?((non)?academic(factors)?)?"
    rows = [(tag, doc.find(prefix + pattern.lstrip("^"), start, end)) for tag, pattern in C7_ROWS]
    rows = [(tag, i) for tag, i in rows if i is not None]
    found = 0
    for n, (tag, i) in enumerate(rows):
        line = doc.lines[i]
        # Some colleges write the answer as text: "Class rank Very Important".
        m = re.search(r"(veryimportant|notconsidered|important|considered)$", line.sq)
        if m:
            doc.set(tag, {"veryimportant": "VI", "important": "I", "considered": "C", "notconsidered": "NC"}[m.group(1)])
            found += 1
            continue
        if not headers:
            doc.review[tag] = "C7 column headers not found"
            continue
        # Use the nearest header above; when the table continues on the next page
        # without repeating its header, the previous page's columns still apply.
        above = [c for hi, c in headers if hi < i]
        if not above:
            doc.review[tag] = "no C7 header above this row"
            continue
        cols = above[-1]
        width = min(abs(a - b) for a in cols.values() for b in cols.values() if a != b)
        left_edge = min(cols.values()) - width / 2 - 5
        right_edge = max(cols.values()) + width / 2 + 5
        # Marks can sit a few points above or below the label's baseline.
        gaps = [abs(doc.lines[j].top - line.top) for _, j in rows[max(n - 1, 0) : n + 2] if j != i and doc.lines[j].page == line.page]
        tol = min(8, 0.6 * min(gaps)) if gaps else 6
        page = doc.pages[line.page]
        def in_row(m):
            return abs(m["top"] - line.top) <= tol and left_edge <= _center([m]) <= right_edge

        # Prefer text marks (X, ✔); filled shapes are only used when there are none,
        # because some PDFs also draw the empty boxes as filled shapes.
        marks = [w for w in page["words"] if is_mark(w) and in_row(w)]
        if not marks:
            marks = [m for m in page.get("shapes", []) if in_row(m)]
        per_col = {}
        for m in marks:
            col = min(cols, key=lambda c: abs(cols[c] - _center([m])))
            per_col[col] = per_col.get(col, 0) + 1
        cols_hit = set(per_col)
        if len(cols_hit) > 1 and marks and marks[0].get("text") == "[shape]":
            # Empty boxes drawn as shapes appear in every column; the ticked one has extra.
            top = max(per_col.values())
            leaders = [c for c, n in per_col.items() if n == top]
            if len(leaders) == 1 and len(per_col) == len(cols):
                cols_hit = {leaders[0]}
        if len(cols_hit) == 1:
            doc.set(tag, cols_hit.pop())
            found += 1
        elif not cols_hit:
            doc.review[tag] = "no mark found in the C7 row"
        else:
            doc.review[tag] = f"marks in {len(cols_hit)} columns of one C7 row"
    doc.log.append(f"C7: {found}/{len(C7_ROWS)} factors read")


# ---------------------------------------------------------------- C9

C9_SCORE_ROWS = [
    ("SAT1_COMP", r"^satcomposite", 400, 1600),
    ("SAT1_VERB", r"^satevidencebased", 200, 800),
    ("SAT1_MATH", r"^satmath", 200, 800),
    ("ACT_COMP", r"^actcomposite", 1, 36),
    ("ACT_MATH", r"^actmath", 1, 36),
    ("ACT_ENG", r"^actenglish", 1, 36),
    ("ACT_WRITING", r"^actwriting", 1, 12),
    ("ACT_SCIENCE", r"^actscience", 1, 36),
    ("ACT_READING", r"^actreading", 1, 36),
]


def _c9(doc):
    start, end = _span(doc, "c9", ["c10", "c11"])
    if start is None:
        doc.log.append("C9 not found")
        return
    for test, pattern in (("SAT1", r"submittingsatscores"), ("ACT", r"submittingactscores")):
        i = doc.find(pattern, start, end)
        if i is not None:
            nums = [w["text"] for w in doc.lines[i].numbers_after_label()]
            pct = [n for n in nums if n.endswith("%")] or nums[:1]
            cnt = [n for n in nums if not n.endswith("%") and n not in pct]
            if pct:
                doc.set(f"SUBMIT_{test}_P", pct[0])
            if cnt:
                doc.set(f"SUBMIT_{test}_N", cnt[0])

    for prefix, pattern, lo, hi in C9_SCORE_ROWS:
        i = doc.find(pattern, start, end)
        if i is None:
            continue
        nums = [w["text"] for w in doc.lines[i].numbers_after_label()]
        if not nums and i + 1 < len(doc.lines) and doc.lines[i + 1].numeric_only():
            nums = [w["text"] for w in doc.lines[i + 1].words if is_num(w["text"])]
        if not nums:
            continue
        vals = [to_number(n) for n in nums]
        note = None
        if len(nums) != 3:
            note = f"expected 3 percentiles, found {len(nums)}"
        elif not all(v is not None and lo <= v <= hi for v in vals) or not vals[0] <= vals[1] <= vals[2]:
            note = "percentiles out of range or not in order"
        for pct, tok in zip(("25TH", "50TH", "75TH"), nums[:3]):
            doc.set(f"{prefix}_{pct}_P", tok, note)


# ---------------------------------------------------------------- C10-C12

C10_ROWS = [
    ("FRSH_HS_RANK_10_P", r"percentintoptenth"),
    ("FRSH_HS_RANK_25_P", r"percentintopquarter"),
    ("FRSH_HS_RANK_50_P", r"percentintophalf"),
    ("FRSH_HS_RANK_LESS50_P", r"percentinbottomhalf"),
    ("FRSH_HS_RANK_LESS25_P", r"percentinbottomquarter"),
]
C11_ROWS = [
    (1, r"gpaof40"),
    (2, r"gpabetween375and399"),
    (3, r"gpabetween350and374"),
    (4, r"gpabetween325and349"),
    (5, r"gpabetween300and324"),
    (6, r"gpabetween250and299"),
    (7, r"gpabetween20{0,2}and249"),
    (8, r"gpabetween10{0,2}and199"),
    (9, r"gpabelow10"),
]
C11_COLUMNS = ["FRSH_GPA_SUBMIT_{}_P", "FRSH_GPA_NO_SUB_{}_P", "EN_FRSH_GPA_{}_P"]


def _c10_c12(doc):
    start, end = _span(doc, "c10", ["c11", "c12", "c13"])
    if start is not None:
        for tag, pattern in C10_ROWS:
            _row_value(doc, tag, pattern, start, end)
        _value_near(doc, "FRSH_HS_RANK_SUBMIT_P", r"submittedhighschoolclassrank|whosubmittedhighschool", start, end, 2)

    start, end = _span(doc, "c11", ["c12", "c13"])
    if start is not None:
        rows = {}
        for k, pattern in C11_ROWS:
            i = doc.find(pattern, start, end)
            if i is not None:
                nums = doc.lines[i].numbers_after_label()[1:]  # first number is part of the label (e.g. "3.99")
                rows[k] = nums
        widest = max((len(v) for v in rows.values()), default=0)
        if widest == 3:
            ref = next(v for v in rows.values() if len(v) == 3)
            centers = [_center([w]) for w in ref]
            for k, nums in rows.items():
                for w in nums:
                    col = min(range(3), key=lambda c: abs(centers[c] - _center([w])))
                    doc.set(C11_COLUMNS[col].format(k), w["text"])
        elif widest == 1:
            for k, nums in rows.items():
                if nums:
                    doc.set(C11_COLUMNS[2].format(k), nums[0]["text"], "single GPA column: assumed to be all enrolled students")
        elif widest:
            doc.log.append(f"C11: unexpected {widest} columns, not read")
        for col in C11_COLUMNS:
            tags = [col.format(k) for k in range(1, 10) if col.format(k) in doc.values]
            total = sum(to_number(doc.values[t]) or 0 for t in tags)
            if tags and not (97 <= total <= 103 or 0.97 <= total <= 1.03):
                for t in tags:
                    doc.review.setdefault(t, f"GPA bands add up to {total:g}, not 100%")

    start, end = _span(doc, "c12", ["c13", "c14"])
    if start is not None:
        gpa = lambda t: (v := to_number(t)) is not None and 1.0 <= v <= 5.0 and "." in t and "%" not in t  # noqa: E731
        _value_near(doc, "FRSH_GPA", r"averagehighschoolgpa", start, end, 3, gpa)
        _value_near(doc, "FRSH_GPA_SUBMIT_P", r"whosubmittedhighschool", start, end, 2)


# ---------------------------------------------------------------- C21

def _c21(doc):
    start, end = _span(doc, "c21", ["c22"])
    if start is None:
        return
    _row_value(doc, "AP_RECD_EDEC_N", r"numberofearlydecisionapplications", start, end)
    _row_value(doc, "AP_ADMT_EDEC_N", r"numberofapplicantsadmittedunderearlydecision", start, end)


# ---------------------------------------------------------------- H6

def _h6(doc):
    start, end = _span(doc, "h6", ["h7", "h8"])
    if start is None:
        doc.log.append("H6 not found")
        return
    checks = [
        ("INTL_NB", r"institutionalneedbasedscholarship"),
        ("INTL_NN", r"institutionalnonneedbasedscholarship"),
        ("INTL_NO", r"institutionalscholarship(or|and)grantaidisnotavailable"),
    ]
    marked = 0
    for tag, pattern in checks:
        i = doc.find(pattern, start, end)
        if i is None:
            continue
        has_mark = any(is_mark(w) for w in doc.lines[i].words)
        doc.values[tag] = "Yes" if has_mark else "No"
        marked += has_mark
    if not marked:
        for tag, _ in checks:
            if tag in doc.values:
                doc.review[tag] = "no box ticked in H6: check the PDF"

    integer = lambda t: is_num(t) and "%" not in t and "$" not in t and "." not in t  # noqa: E731
    _value_near(doc, "INTL_RECD_N", r"providethenumber", start, end, 3, integer)
    _value_near(doc, "INTL_AVG_D", r"averagedollaramountofinstitutional", start, end, 3)
    _value_near(doc, "INTL_TOT_D", r"totaldollaramountofinstitutional", start, end, 3)
    n, avg, tot = (to_number(doc.values.get(t)) for t in ("INTL_RECD_N", "INTL_AVG_D", "INTL_TOT_D"))
    if n and avg and tot and abs(n * avg - tot) / tot > 0.15:
        for t in ("INTL_RECD_N", "INTL_AVG_D", "INTL_TOT_D"):
            doc.review[t] = f"number x average ({n * avg:,.0f}) does not match the total ({tot:,.0f})"


# ---------------------------------------------------------------- B

def _b(doc):
    i = doc.find(r"sixyeargraduationrate")
    if i is not None:
        nums = doc.lines[i].numbers_after_label()
        if nums:
            tok = nums[-1]["text"]
            v = to_number(tok)
            note = None if v is not None and (0.3 <= v <= 1 or 30 <= v <= 100) else "graduation rate out of range"
            doc.set("GRS_BACH_TOT_P", tok, note)

    start = doc.anchor("b22")
    if start is not None:
        def pct(t):
            v = to_number(t)
            return v is not None and (t.endswith("%") and 50 <= v <= 100 or 0.5 <= v <= 1 and "." in t)
        _value_near(doc, "RETENTION_FRSH_P", r"^b22", start, start + 10, 8, pct)


def extract(pages):
    doc = Doc(pages=pages, lines=build_lines(pages))
    for rule in (_c1, _c2, _c7, _c9, _c10_c12, _c21, _h6, _b):
        try:
            rule(doc)
        except Exception as exc:  # one broken section must not lose the others
            doc.log.append(f"{rule.__name__} failed: {exc!r}")
    review = {k: v for k, v in doc.review.items() if k in doc.values}
    for k, v in doc.review.items():
        if k not in doc.values:
            doc.log.append(f"not read: {k}: {v}")
    doc.log.append(f"{len(doc.values)} values read by text rules, {len(review)} flagged for review")
    return doc.values, review, doc.log
