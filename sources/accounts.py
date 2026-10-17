"""Student accounts: usernames, sign-up eligibility and one-time sign-up links. No AI involved."""

import hashlib
import os
import re
import unicodedata

from django.contrib.auth.models import User
from django.core import signing

from sources.crypto import decrypt, email_fingerprint, normalise_email

TOKEN_SALT = "ugs-student-signup"
TOKEN_MAX_AGE = 48 * 3600  # sign-up links work for 48 hours

# Ukrainian official transliteration (Cabinet of Ministers, 2010), simplified to lower case.
UK = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ie", "ж": "zh", "з": "z",
    "и": "y", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh",
    "щ": "shch", "ь": "", "ю": "iu", "я": "ia", "'": "", "’": "",
    # Russian letters sometimes found in records
    "ё": "e", "ы": "y", "э": "e", "ъ": "",
}


def latin(text):
    text = "".join(UK.get(ch, ch) for ch in (text or "").lower())
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", text)


def make_username(first_name, last_name):
    """First letter of the first name + last name: McKayla Collins -> mcollins (mcollins2 if taken)."""
    base = (latin(first_name)[:1] + latin(last_name)) or "student"
    username, n = base, 1
    while User.objects.filter(username=username).exists():
        n += 1
        username = f"{base}{n}"
    return username


def split_name(full_name):
    parts = (full_name or "").split()
    if len(parts) < 2:
        return "", ""
    return parts[0], parts[-1]


def allowed_domains():
    return [d.strip().lower().lstrip("@") for d in os.environ.get("STUDENT_EMAIL_DOMAINS", "").split(",") if d.strip()]


def find_student(email):
    """The Student whose stored email matches, else None."""
    from colleges.models import StudentIdentity

    identity = StudentIdentity.objects.filter(email_hash=email_fingerprint(email)).select_related("student").first()
    return identity.student if identity else None


def domain_allowed(email):
    """With STUDENT_EMAIL_DOMAINS set, only addresses in those domains may sign up (exact domain, no subdomains)."""
    domains = allowed_domains()
    return not domains or normalise_email(email).rsplit("@", 1)[-1] in domains


def eligible(email):
    """(student or None, allowed). With STUDENT_EMAIL_DOMAINS set: any address in those domains, and only those
    (a loaded student is linked to their record). Without it: only students whose email UGS has loaded."""
    email = normalise_email(email)
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or not domain_allowed(email):
        return None, False
    student = find_student(email)
    if student:
        return student, True
    return None, bool(allowed_domains())


def _password_state(student):
    """Changes when the student's password changes, so a used link stops working."""
    user = getattr(student, "user", None) if student else None
    return hashlib.sha256((user.password if user else "new").encode()).hexdigest()[:12]


def make_token(email, student):
    return signing.dumps({"e": normalise_email(email), "p": _password_state(student)}, salt=TOKEN_SALT)


def read_token(token):
    """(email, student) for a valid, unused, unexpired link; raises signing.BadSignature otherwise."""
    data = signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
    student = find_student(data["e"])
    if data["p"] != _password_state(student):
        raise signing.BadSignature("link already used")
    return data["e"], student


def stored_name(student):
    identity = getattr(student, "identity", None)
    return decrypt(identity.name_encrypted) if identity else ""
