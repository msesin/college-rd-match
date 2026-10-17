"""Crowding is now a cut applied after the match (decision 42): update the UGS applicants column's description,
unless the team has already rewritten it."""

from django.db import migrations

OLD = ("How many UGS students have this college on their list (submitted forms), against its UGS capacity: how "
       "many UGS students it usually admits a year (average of the last 3 years in UGS's admissions results, at "
       "least 1; editable). Up to 2x capacity, crowding gives full points; up to 4x half; more none.")
NEW = ("How many UGS students have this college on their list (submitted forms), against its UGS capacity: how "
       "many UGS students it usually admits a year (average of the last 3 years in UGS's admissions results, at "
       "least 1; editable). Applied after the match: no cut up to 2x capacity, then a cut growing evenly to 20% "
       "of the match at 4x and above.")


def forwards(apps, schema_editor):
    apps.get_model("colleges", "ColumnSetting").objects.filter(key="ugs_applicants", description=OLD).update(description=NEW)


def backwards(apps, schema_editor):
    apps.get_model("colleges", "ColumnSetting").objects.filter(key="ugs_applicants", description=NEW).update(description=OLD)


class Migration(migrations.Migration):
    dependencies = [("colleges", "0013_ugs_applicants_column_text")]
    operations = [migrations.RunPython(forwards, backwards)]
