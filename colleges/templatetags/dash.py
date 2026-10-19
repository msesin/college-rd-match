import os

from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def qs(context, **changes):
    """Current query string with some parameters changed (None or '' removes one)."""
    params = context["request"].GET.copy()
    for k, v in changes.items():
        if v in (None, ""):
            params.pop(k, None)
        else:
            params[k] = v
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else "?"


@register.simple_tag(takes_context=True)
def sort_link(context, column):
    """Link that sorts by `column`, toggling direction if already sorted by it."""
    current, direction = context.get("sort"), context.get("dir", "asc")
    new_dir = "asc" if str(current) == str(column) and direction == "desc" else "desc"
    if str(column) == "name" and str(current) != "name":
        new_dir = "asc"
    return qs(context, sort=column, dir=new_dir)


@register.filter
def get_item(d, key):
    return d.get(key)


@register.filter
def attr_of(obj, name):
    return getattr(obj, name, None)


@register.filter
def choice_label(obj, name):
    return getattr(obj, f"get_{name}_display")()


@register.filter
def choice_rank(value):
    from colleges.columns import CHOICE_ORDER

    return CHOICE_ORDER.get(value, 0)


@register.filter
def transcript_levels(student):
    """{"gpa": (level, reason), "rank": ..., "coursework": ...} as the matching engine sees them."""
    from sources import transcript

    return {"gpa": transcript.gpa_level(student), "rank": transcript.class_rank_level(student),
            "coursework": transcript.coursework_level(student)}


@register.filter
def grades_text(grades):
    """{"Biology": 11} -> 'Biology 11 · ...'"""
    return " · ".join(f"{k} {v}" for k, v in (grades or {}).items())


@register.filter
def pct(value):
    """12.5 -> '12.5%', 25.0 -> '25%'."""
    return f"{float(value):g}%"


@register.filter
def num(value):
    """12.50 -> '12.5', 25.0 -> '25', 6.25 -> '6.25'."""
    return f"{float(value):g}"


@register.filter
def money(value):
    """5066953 -> '5.07M', 820000 -> '820k'."""
    v = float(value)
    return f"{v / 1e6:.2f}M" if v >= 1e6 else f"{v / 1e3:.0f}k"


@register.filter
def mul(value, factor):
    try:
        return value * factor
    except TypeError:
        return value


@register.filter
def dictsort_items(d):
    """A dict's (key, value) pairs sorted by key."""
    return sorted((d or {}).items())


@register.filter
def sum_values(values):
    return sum(values or [])


@register.simple_tag(takes_context=True)
def demo_user(context):
    """True when the public demo account (sources/demo.py) is logged in."""
    from sources.demo import DEMO_USERNAME

    request = context.get("request")
    return bool(request and request.user.is_authenticated and request.user.username == DEMO_USERNAME)


@register.simple_tag
def gemini_warnings():
    """Why Gemini may be silently off, for staff pages: no key, real students not allowed, or .env changed after
    the site started (Django reads .env only at start)."""
    from datetime import datetime

    from django.conf import settings

    out = []
    if not os.environ.get("GEMINI_API_KEY"):
        out.append("No Gemini key: students' answers are not rated and transcripts are not read.")
    elif os.environ.get("ALLOW_STUDENT_DATA_TO_GEMINI") != "1":
        out.append("Gemini is off for real students (ALLOW_STUDENT_DATA_TO_GEMINI is not 1): their answers are not "
                   "rated, their transcripts are not read, and they do not see the transcript autofill (\"Click to autofill\").")
    if not os.environ.get("STUDENT_EMAIL_DOMAINS", "").strip():
        out.append("Sign-up is open only to students whose email was added in the admin. To let anyone with your "
                   "organisation's email sign up (and only them), set STUDENT_EMAIL_DOMAINS (e.g. ugs.foundation) in .env.")
    env = getattr(settings, "ENV_FILE", None)
    if env and env.exists() and env.stat().st_mtime > getattr(settings, "STARTED_AT", 0) + 2:
        changed = datetime.fromtimestamp(env.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        out.append(f".env was changed ({changed}) after the site started, so the change is not in use yet: restart "
                   "the site (on the server: sudo systemctl restart ugs).")
    return out


@register.simple_tag
def beta_notice():
    from django.conf import settings

    return getattr(settings, "BETA_NOTICE", False)


@register.simple_tag
def demo_reset_seconds():
    """Seconds until the next demo reset (cron runs every RESET_MINUTES on the clock: :00, :10, :20, ...)."""
    import time

    from sources.demo import RESET_MINUTES

    period = RESET_MINUTES * 60
    return int(period - time.time() % period)
