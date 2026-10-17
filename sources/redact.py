"""Remove sentences that may name people from free text before it leaves the machine.

HubSpot calls and notes mention past applicants (minors) by name together with
admissions judgments. Names cannot be detected reliably, so this filter is
deliberately conservative: a sentence is kept only if every capitalised word
in it is a known dictionary word that is not a first name, or is on an
allowlist (college names, places, tests). Everything else is dropped.

It needs a word list and a first-name list (on macOS: /usr/share/dict/words
and /usr/share/dict/propernames). If they are missing it refuses to return
any text (fails closed).
"""

import re
from functools import lru_cache
from pathlib import Path

WORDS_PATH = Path("/usr/share/dict/words")
NAMES_PATH = Path("/usr/share/dict/propernames")

ALLOW = {
    # tests, programs, organisations commonly mentioned in counselling notes
    "duolingo", "det", "toefl", "ielts", "sat", "act", "ap", "ib", "initialview", "vericant",
    "questbridge", "common", "app", "coalition", "uwc", "uwcs", "css", "profile", "fafsa", "idoc",
    "ed", "ea", "rd", "rea", "scea", "ed1", "ed2", "f1", "visa", "covid", "zoom", "google", "linkedin",
    # places
    "ukraine", "ukrainian", "ukrainians", "kyiv", "kiev", "lviv", "kharkiv", "odesa", "dnipro", "europe",
    "european", "asia", "asian", "africa", "african", "america", "american", "americas", "us", "usa", "uk",
    "ghana", "nigeria", "kenya", "china", "chinese", "korea", "korean", "india", "indian", "japan",
    "vietnam", "pakistan", "brazil", "canada", "mexico", "germany", "poland", "polish", "russia", "turkey",
    "dc", "nyc", "boston", "chicago", "philadelphia", "california", "virginia", "new", "york",
    # calendar
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday",
}


@lru_cache(maxsize=1)
def _lexicon():
    if not WORDS_PATH.exists() or not NAMES_PATH.exists():
        return None
    words = {w.strip().lower() for w in WORDS_PATH.read_text(errors="ignore").splitlines()}
    names = {w.strip().lower() for w in NAMES_PATH.read_text(errors="ignore").splitlines()}
    return words, names


CAPITALISED = re.compile(r"\b[A-Z][a-zA-Z'’\-]*[a-z][a-zA-Z'’\-]*\b")


def _variants(word):
    """The word plus simple base forms: the word list has no plurals or inflections."""
    out = {word}
    for suffix, repl in (("ies", "y"), ("es", ""), ("s", ""), ("ed", ""), ("ed", "e"), ("ing", ""), ("ing", "e"), ("ly", "")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            out.add(word[: -len(suffix)] + repl)
    return out


def _safe_word(token, words, names, extra_allow):
    t = re.sub(r"['’]s$", "", token).lower()
    parts = [p for p in re.split(r"[-'’]", t) if p]
    for p in parts:
        if p in ALLOW or p in extra_allow:
            continue
        if p in names or not (_variants(p) & words):
            return False
    return True


def split_segments(text):
    """Sentences, bullet lines and semicolon-separated clauses."""
    pieces = re.split(r"(?<=[.!?])\s+|\n+|;\s*|\s+-\s+(?=[A-Z])", text or "")
    return [p.strip(" -•\t") for p in pieces if p and p.strip(" -•\t")]


def filter_names(text, extra_allow=()):
    """Return (kept_text, kept_count, dropped_count). Fails closed without word lists."""
    lex = _lexicon()
    segments = split_segments(text)
    if lex is None:
        return "", 0, len(segments)
    words, names = lex
    allow = {w.lower() for w in extra_allow}
    kept = [
        s for s in segments
        if all(_safe_word(tok, words, names, allow) for tok in CAPITALISED.findall(s))
    ]
    return "\n".join(kept), len(kept), len(segments) - len(kept)


EMAIL_PHONE_PATTERNS = [
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    re.compile(r"(?<!\d)\+?\d[\d\s().-]{7,}\d(?!\d)"),
]


def scrub_contacts(text):
    """Replace email addresses and phone numbers (9+ digits) in free text."""
    if not text:
        return text
    text = EMAIL_PHONE_PATTERNS[0].sub("[email removed]", text)
    return EMAIL_PHONE_PATTERNS[1].sub(
        lambda m: "[phone removed]" if sum(c.isdigit() for c in m.group(0)) >= 9 else m.group(0), text)
