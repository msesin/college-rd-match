"""Write CollegeProfile fields with provenance.

Every write goes through set_field(), which records a FieldHistory row and
never overwrites a value someone edited by hand (unless force=True).
"""

from decimal import Decimal

from django.db import transaction

from colleges.models import CollegeProfile, FieldHistory


def get_profile(college):
    profile, _ = CollegeProfile.objects.get_or_create(college=college)
    return profile


def latest_sources(college_ids=None):
    """{(unitid, field): FieldHistory} for the newest history row of each field."""
    qs = FieldHistory.objects.order_by("college_id", "field", "-created_at", "-id")
    if college_ids is not None:
        qs = qs.filter(college_id__in=college_ids)
    out = {}
    for h in qs:
        out.setdefault((h.college_id, h.field), h)
    return out


def is_manual(college, field):
    last = FieldHistory.objects.filter(college=college, field=field).order_by("-created_at", "-id").first()
    return bool(last and last.source == FieldHistory.SOURCE_MANUAL)


def _same(a, b):
    if isinstance(a, Decimal) or isinstance(b, Decimal):
        try:
            return Decimal(str(a)) == Decimal(str(b))
        except Exception:
            return False
    return a == b


@transaction.atomic
def set_field(college, field, value, source, detail="", user="", force=False):
    """Set one profile field. Returns True if written, False if skipped.

    Skipped when the current value was entered by hand and force is False, or
    when the value and source are unchanged.
    """
    profile = get_profile(college)
    if source != FieldHistory.SOURCE_MANUAL and not force and is_manual(college, field):
        return False
    if value is None and CollegeProfile._meta.get_field(field).get_internal_type() in ("CharField", "TextField"):
        value = ""
    last = FieldHistory.objects.filter(college=college, field=field).order_by("-created_at", "-id").first()
    if _same(getattr(profile, field), value) and last and last.source == source and last.detail == detail:
        return False
    setattr(profile, field, value)
    profile.save(update_fields=[field, "updated_at"])
    FieldHistory.objects.create(
        college=college, field=field, value="" if value is None else str(value),
        source=source, detail=detail[:2000], user=user,
    )
    return True
