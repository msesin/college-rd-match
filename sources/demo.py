"""The public demo login: one fictional sample student, with the password published in README.md.

`create_sample_students` gives this student (and only this one) a login; `create_sample_students --demo-only`
resets it every RESET_MINUTES from cron on the server: the application goes back to "not submitted", and everyone using
the demo is logged out (setting the password again ends every open demo session). Since anyone can use it, the demo account:
- does not count towards other students' crowding (no sample student does; sources/students.py);
- cannot upload or delete files;
- never sends anything to Gemini (its ratings are the saved ones);
- sees only DEMO_COLLEGES (well-known colleges, not the organisation's whole list).
"""

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "ugs-demo-2026"
RESET_MINUTES = 10   # cron: */10 * * * *  (docs/deploy.md)
DEMO_STUDENT = "Solomiya Solomiya"   # the fictional sample student behind the login
# IPEDS UNITID: the 8 Ivy League colleges and 7 other well-known ones. Colleges missing from the database are skipped;
# if none of them is there, the demo sees every college.
DEMO_COLLEGES = {
    217156: "Brown", 190150: "Columbia", 190415: "Cornell", 182670: "Dartmouth", 166027: "Harvard",
    215062: "Penn", 186131: "Princeton", 130794: "Yale", 198419: "Duke", 166683: "MIT", 243744: "Stanford",
    144050: "UChicago", 110404: "Caltech", 147767: "Northwestern", 162928: "Johns Hopkins",
}


def is_demo(student):
    user = getattr(student, "user", None)
    return bool(user and user.username == DEMO_USERNAME)


def demo_college_ids():
    """The demo colleges that are in the database (empty if none is)."""
    from colleges.models import College

    return set(College.objects.filter(unitid__in=DEMO_COLLEGES).values_list("unitid", flat=True))


def visible_college_ids(student):
    """The colleges this student may see and choose: None = all of them; the demo sees only DEMO_COLLEGES."""
    if not is_demo(student):
        return None
    return demo_college_ids() or None
