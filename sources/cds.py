"""Common Data Set (CDS) files: find, extract and structure.

CDS files arrive in three technical shapes, each with its own extractor:

1. Excel (official CDS template): the "Answer Sheet" tab lists every answer
   with its official tag. Exact.
2. Fillable PDF (official template saved as a form): every answer sits in a
   named form field whose name is the same official tag. Exact. The page text
   of these files is the blank template, so text extraction alone finds nothing.
3. Flat PDF (everything else): only text and word positions. A set of rules
   (sources/cds_text_rules.py) extracts the priority items; checkbox grids like
   C7 are read by matching each mark to its column header by x position.

Every value is mapped to the official CDS tag (e.g. AP_ADMT_INTL_1ST_N), so all
three shapes produce the same keys. The field dictionary in cds_fields.json was
built from the official 2025-26 Excel template (see build_field_dictionary).
"""

import hashlib
import json
import re
from pathlib import Path

from sources.parsing import to_number

FIELDS_PATH = Path(__file__).with_name("cds_fields.json")

# File name stem (text before " CDS ") -> team list name, where they differ.
FILE_ALIASES = {
    "Caltech": "California Institute of Technology (Caltech)",
    "Columbia College and Columbia Engineering": "Columbia",
    "Columbia General Studies": "Columbia",
    "Sewanee The University of the South": "Sewanee University of the South",
    "Massachusetts Institute of Technology": "MIT",
}
# Secondary documents: kept and shown, but not the main CDS for the college.
SECONDARY_FILES = {"Columbia General Studies"}

C7_VALUES = {"VI": "Very Important", "I": "Important", "C": "Considered", "NC": "Not Considered"}
# Ordinal code so C7 values can be sorted; not a weight.
C7_ORDINAL = {"Very Important": 3, "Important": 2, "Considered": 1, "Not Considered": 0}


# ---------------------------------------------------------------- dictionary

def build_field_dictionary(xlsx_path):
    """Build cds_fields.json from an official CDS Excel template's Answer Sheet.

    Only the questions are kept, never the answers.
    """
    import openpyxl

    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    rows = list(wb["Answer Sheet"].iter_rows(values_only=True))
    header = rows[0]
    fields = []
    for raw in rows[1:]:
        d = dict(zip(header, raw))
        qn = str(d.get("Question Number") or "").strip()
        m = re.match(r"^([A-J])\.(\d+[A-Z]?)(\d\d)$", qn) or re.match(r"^([A-J])\.(\d*[A-Z]?)()$", qn)
        if not m:
            continue
        context = [
            str(d[k]).strip()
            for k in ("Category", "Student Group", "Cohort", "Residency", "Unit load", "Gender")
            if d.get(k) not in (None, "", "None", "All")
        ]
        fields.append(
            {
                "qn": qn,
                "item": m.group(1) + m.group(2),
                "tag": str(d.get("US News PDF Tag") or "").strip(),
                "question": re.sub(r"\s+", " ", str(d.get("Question") or "")).strip(),
                "section": str(d.get("Section") or ""),
                "subsection": str(d.get("Sub-Section") or ""),
                "context": ", ".join(context),
                "value_type": str(d.get("Value type") or ""),
            }
        )
    FIELDS_PATH.write_text(json.dumps(fields, indent=1))
    return fields


_FIELDS = None


def fields_by_key():
    """Dictionary entries keyed by official tag (or question number when a tag is missing)."""
    global _FIELDS
    if _FIELDS is None:
        entries = json.loads(FIELDS_PATH.read_text())
        _FIELDS = {}
        question_counts = {}
        for e in entries:
            question_counts[(e["item"], e["question"])] = question_counts.get((e["item"], e["question"]), 0) + 1
        for e in entries:
            label = e["question"] or e["subsection"]
            # Repeated question texts ("Total") need their context to be readable.
            if question_counts[(e["item"], e["question"])] > 1 and e["context"]:
                label = f"{label} ({e['context']})"
            e["label"] = label
            _FIELDS[e["tag"] or f"Q{e['qn']}"] = e
    return _FIELDS


# ---------------------------------------------------------------- files

def discover_files(cds_dir):
    """Yield dicts describing each CDS file in the folder."""
    for path in sorted(Path(cds_dir).iterdir()):
        if path.suffix.lower() not in (".pdf", ".xlsx"):
            continue
        m = re.match(r"^(.*?) CDS (\d{4}-\d{2})$", path.stem)
        if not m:
            yield {"path": path, "stem": path.stem, "college_name": None, "year": ""}
            continue
        stem, year = m.groups()
        yield {
            "path": path,
            "stem": stem,
            "college_name": FILE_ALIASES.get(stem, stem),
            "year": year,
            "is_primary": stem not in SECONDARY_FILES,
        }


def file_checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------- extraction

def extract(path):
    """Extract raw text and tagged values from one CDS file.

    Returns dict: method, status, text, values {tag: raw value}, review {tag: reason}, log [str].
    """
    path = Path(path)
    result = check_totals(_extract_xlsx(path) if path.suffix.lower() == ".xlsx" else _extract_pdf(path))
    if result["status"] is None:
        v = result["values"]
        c7 = sum(1 for k in v if k.startswith(("Q111_", "Q112_")))
        result["status"] = "ok" if v.get("AP_RECD_1ST_N") and c7 >= 15 else "partial"
    return result


def _extract_xlsx(path):
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    rows = list(wb["Answer Sheet"].iter_rows(values_only=True))
    header = rows[0]
    values, lines = {}, []
    for raw in rows[1:]:
        d = dict(zip(header, raw))
        answer = d.get("Answer")
        if answer in (None, "", "None") or str(answer).startswith("#"):
            continue
        key = str(d.get("US News PDF Tag") or "").strip() or f"Q{d.get('Question Number')}"
        values[key] = answer
        lines.append(f"{d.get('Question Number')}\t{key}\t{d.get('Question')}\t{answer}")
    return {
        "method": "xlsx",
        "status": "ok",
        "text": "\n".join(lines),
        "values": values,
        "log": [f"{len(values)} answers read from the Answer Sheet"],
    }


def _decode_cid(text):
    """Some PDFs (Caltech, Tufts) use fonts whose glyph codes are ASCII + 29."""
    return re.sub(r"\(cid:(\d+)\)", lambda m: chr(int(m.group(1)) + 29), text)


def _filled_marks(page):
    """Ticks drawn as graphics: small filled shapes, smaller than a checkbox (~10pt).

    Colour is not used: some PDFs use colour spaces where the numbers don't
    mean dark/light, and boxes themselves can be "filled".
    """
    marks = []
    for obj in list(page.rects) + list(page.curves):
        w, h = obj["x1"] - obj["x0"], obj["bottom"] - obj["top"]
        if obj.get("fill") and 2 <= w <= 7.5 and 2 <= h <= 7.5:
            marks.append({"x0": obj["x0"], "x1": obj["x1"], "top": obj["top"], "text": "[shape]"})
    return marks


def _extract_pdf(path):
    import logging

    import pdfplumber
    from pypdf import PdfReader

    from sources import cds_text_rules

    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    log = []

    # 1. Fillable form?
    form_values = {}
    try:
        fields = PdfReader(path).get_fields() or {}
    except Exception as exc:  # damaged form dictionaries are common; fall back to text
        fields = {}
        log.append(f"form fields unreadable: {exc}")
    for name, f in fields.items():
        v = f.get("/V")
        if v in (None, "", "/Off", " "):
            continue
        v = str(v)
        if v.startswith("/"):
            v = v[1:].strip()
        form_values[name.strip()] = v

    # 2. Text and word positions (needed for flat PDFs; kept as raw text for all).
    pages = []
    text_parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=1.5, y_tolerance=2, keep_blank_chars=False, extra_attrs=["fontname"])
            for w in words:
                w["text"] = _decode_cid(w["text"])
            pages.append({"words": words, "chars": len(page.chars), "shapes": _filled_marks(page)})
            text_parts.append(_decode_cid(page.extract_text() or ""))
    text = "\n\f".join(text_parts)

    avg_chars = sum(p["chars"] for p in pages) / max(len(pages), 1)
    known = fields_by_key()
    form_hits = sum(1 for k in form_values if k in known)
    if form_hits >= 50:
        log.append(f"fillable form: {len(form_values)} filled fields, {form_hits} match official tags")
        return {"method": "pdf_form", "status": "ok", "text": text, "values": form_values, "log": log}

    values, review, rule_log = cds_text_rules.extract(pages)
    log.extend(rule_log)
    # A blank CDS template is ~1.6% digits; a filled one is more. Less than that
    # means the numbers were exported as shapes and only OCR can recover them.
    digit_share = sum(ch.isdigit() for ch in text) / max(len(text), 1)
    if avg_chars < 400 or digit_share < 0.013:
        log.append(f"numbers are missing from the text layer ({digit_share:.1%} digits): needs OCR or manual entry")
        review.update({k: "document needs OCR: verify against the PDF" for k in values})
        return {"method": "pdf_text", "status": "needs_ocr", "text": text, "values": values, "review": review, "log": log}
    return {"method": "pdf_text", "status": None, "text": text, "values": values, "review": review, "log": log}


# ---------------------------------------------------------------- checks

TOTALS = [
    ("AP_RECD_1ST_N", ["AP_RECD_1ST_MEN_N", "AP_RECD_1ST_WMN_N", "AP_RECD_1ST_OTH_N", "AP_RECD_1ST_UNK_N"]),
    ("AP_ADMT_1ST_N", ["AP_ADMT_1ST_MEN_N", "AP_ADMT_1ST_WMN_N", "AP_ADMT_1ST_OTH_N", "AP_ADMT_1ST_UNK_N"]),
    ("EN_TOT_1ST_N", ["EN_TOT_1ST_FT_MEN_N", "EN_TOT_1ST_PT_MEN_N", "EN_TOT_1ST_FT_WMN_N", "EN_TOT_1ST_PT_WMN_N",
                      "EN_TOT_1ST_FT_UNK_N", "EN_TOT_1ST_PT_UNK_N"]),
]


def check_totals(result):
    """Fill missing or zero C1 totals from the gender rows, and flag totals that don't add up."""
    values, review = result["values"], result.setdefault("review", {})
    for total_tag, parts in TOTALS:
        part_sum = sum(to_number(values.get(p)) or 0 for p in parts)
        total = to_number(values.get(total_tag))
        if part_sum and not total:
            values[total_tag] = str(int(part_sum))
            review[total_tag] = "computed by adding the gender rows (total was blank or 0)"
        elif part_sum and total and abs(total - part_sum) / total > 0.02:
            review[total_tag] = f"gender rows add up to {part_sum:,.0f}, not {total:,.0f}"
    # H6: many colleges give the average and total aid to nonresidents but not the count.
    avg, tot = to_number(values.get("INTL_AVG_D")), to_number(values.get("INTL_TOT_D"))
    if not to_number(values.get("INTL_RECD_N")) and avg and tot:
        values["INTL_RECD_N"] = str(round(tot / avg))
        review["INTL_RECD_N"] = "computed as total aid / average aid (count was blank)"
    return result


# ---------------------------------------------------------------- facts

def _normalise(tag, raw, method, field):
    """Return (value_num, value_text) for one raw answer."""
    text = str(raw).strip()
    if tag.startswith(("Q111_", "Q112_")):
        label = C7_VALUES.get(text.upper(), text)
        return C7_ORDINAL.get(label), label
    if text.upper() in ("Y", "YES"):
        return None, "Yes"
    if text.upper() in ("N", "NO"):
        return None, "No"
    if text.upper() == "X" or text == "✔":
        return None, "Yes"
    num = to_number(text)
    if num is None:
        return None, text
    # Tags ending in _P are percentages, except score percentiles like SAT1_COMP_25TH_P.
    is_percent = (tag.endswith("_P") and not tag.endswith("TH_P")) or text.endswith("%")
    # Excel stores percentages as fractions (0.443 = 44.3%); forms mix both.
    if is_percent:
        if method == "xlsx" and 0 <= num <= 1:
            num = round(num * 100, 4)
        elif method in ("pdf_form", "pdf_text") and 0 < num < 1 and "." in text and not text.endswith("%"):
            num = round(num * 100, 4)
    return num, text


def to_facts(result, period):
    """Turn an extraction result into fact dicts for sources.store.replace_facts."""
    known = fields_by_key()
    review = result.get("review", {})
    facts = []
    for tag, raw in result["values"].items():
        field = known.get(tag)
        if field is None:
            if result["method"] == "pdf_form":
                continue  # layout-only form fields (checkers, helper boxes)
            field = {"item": tag.split("_")[0], "label": tag}
        if field["item"].startswith("A") and field["item"] in ("A0", "A0A"):
            continue  # respondent's personal contact details: not needed
        value_num, value_text = _normalise(tag, raw, result["method"], field)
        facts.append(
            {
                "section": field["item"],
                "key": tag,
                "label": field["label"],
                "value_num": value_num,
                "value_text": value_text,
                "method": result["method"],
                "period": period,
                "needs_review": tag in review,
                "review_note": review.get(tag, ""),
            }
        )
    return facts
