"""The UGS applicants column now also shows (and edits) the college's UGS capacity: update its description,
unless the team has already rewritten it."""

from django.db import migrations

OLD = "How many UGS students listed this college among their 12 choices (counted from submitted forms)."
NEW = ("How many UGS students have this college on their list (submitted forms), against its UGS capacity: how "
       "many UGS students it usually admits a year (average of the last 3 years in UGS's admissions results, at "
       "least 1; editable). Up to 2x capacity, crowding gives full points; up to 4x half; more none.")


def forwards(apps, schema_editor):
    apps.get_model("colleges", "ColumnSetting").objects.filter(key="ugs_applicants", description=OLD).update(description=NEW)


def backwards(apps, schema_editor):
    apps.get_model("colleges", "ColumnSetting").objects.filter(key="ugs_applicants", description=NEW).update(description=OLD)


class Migration(migrations.Migration):
    dependencies = [("colleges", "0012_talent_activities_work_school_ugs_history")]
    operations = [migrations.RunPython(forwards, backwards)]
